import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from phage_lab.agents import AgentError, OpenRouterAgent, RuleAgent
from phage_lab.biology import mock_candidates, read_fasta
from phage_lab.devices import Command, DeviceError, FaultInjector, OPERATIONS, SimulatedDevice
from phage_lab.workflow import Scheduler, WorkflowError, run_demo, validate_recovery
from phage_lab.records import RunRecords

ROOT = Path(__file__).resolve().parent.parent
GENOME = ROOT / "examples" / "toy_genome.fasta"
PAYLOAD = {"sample_id": "SIM-SAMPLE-test", "candidate_ids": ["SIM-PHAGE-A", "SIM-PHAGE-B"]}


class RunTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.output = Path(self.temporary.name)

    async def run_case(self, **kwargs):
        return await run_demo(GENOME, self.output, time_scale=0.01, echo=False, **kwargs)

    def events(self, directory):
        return [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines()]

    async def test_normal_run_and_reports(self):
        report, directory = await self.run_case(fault="none")
        self.assertEqual(report["status"], "succeeded")
        self.assertEqual(list(report["results"]), list(OPERATIONS))
        self.assertEqual(sum(report["effects_by_device"].values()), 5)
        self.assertEqual(report["evaluation"]["biological_conclusion"], "not_assessed")
        self.assertEqual(json.loads((directory / "report.json").read_text()), report)
        self.assertIn("模拟", (directory / "report.md").read_text())
        events = self.events(directory)
        self.assertEqual([e["seq"] for e in events], list(range(1, len(events) + 1)))
        self.assertEqual(events[-1]["event"], "run_finished")

    async def test_hang_recovers_at_every_workflow_step(self):
        for step in OPERATIONS:
            with self.subTest(step=step):
                report, directory = await self.run_case(fault="hang", fault_step=step)
                self.assertEqual(report["status"], "succeeded")
                self.assertEqual(report["fault"]["injected_count"], 1)
                self.assertEqual(sum(report["effects_by_device"].values()), 5)
                self.assertEqual(report["effects_by_device"][step + "-primary"], 0)
                self.assertEqual(report["effects_by_device"][step + "-backup"], 1)
                events = self.events(directory)
                cancelled = next(e["seq"] for e in events if e["event"] == "cancellation_acknowledged")
                retried = next(e["seq"] for e in events if e["event"] == "job_submitted" and e["details"]["attempt"] == 2)
                self.assertLess(cancelled, retried)
                ids = [e["details"]["command_id"] for e in events
                       if e["event"] == "job_submitted" and e["details"]["step"] == step]
                self.assertEqual(ids[0], ids[1])

    async def test_lost_response_reuses_completion_without_resubmission(self):
        report, directory = await self.run_case(fault="response-lost", fault_step="synthesize")
        self.assertEqual(report["status"], "succeeded")
        self.assertEqual(report["recoveries"][0]["outcome"], "completed_result_reused")
        self.assertEqual(sum(report["effects_by_device"].values()), 5)
        self.assertEqual(sum(e["event"] == "job_submitted" for e in self.events(directory)), 5)
        self.assertFalse(any(e["event"] == "recovery_requested" for e in self.events(directory)))

    async def test_unreachable_device_stops_without_duplicate_work(self):
        report, directory = await self.run_case(fault="unreachable", fault_step="prepare")
        self.assertEqual(report["status"], "failed")
        self.assertEqual(list(report["results"]), ["synthesize"])
        self.assertEqual(report["evaluation"]["quality"], "incomplete")
        self.assertEqual(report["effects_by_device"]["prepare-backup"], 0)
        self.assertIn("cannot confirm", report["error"])
        self.assertEqual(self.events(directory)[-1]["details"]["status"], "failed")

    async def test_same_seed_preserves_values_across_failover_and_runs(self):
        normal, first_directory = await self.run_case(seed=17, fault="none")
        recovered, _ = await self.run_case(seed=17, fault="hang")
        replay, replay_directory = await self.run_case(seed=17, fault="hang")
        self.assertEqual(normal["results"], recovered["results"])
        self.assertEqual(recovered["results"], replay["results"])
        self.assertEqual(recovered["fault"], replay["fault"])
        self.assertNotEqual(first_directory, replay_directory)

    async def test_invalid_agent_plan_is_rejected_before_device_writes(self):
        class InvalidAgent(RuleAgent):
            async def plan(self, context):
                plan = await super().plan(context)
                plan["device_assignments"]["synthesize"] = "measure-primary"
                return plan
        report, directory = await self.run_case(agent=InvalidAgent())
        self.assertEqual(report["status"], "failed")
        self.assertEqual(sum(report["effects_by_device"].values()), 0)
        self.assertFalse(any(e["event"] == "job_submitted" for e in self.events(directory)))

    async def test_invalid_recovery_cannot_skip_cancellation_or_choose_wrong_device(self):
        class InvalidAgent(RuleAgent):
            async def recover(self, context):
                return {"action": "cancel_and_failover", "replacement_device_id": "unknown",
                        "reason": "invalid choice"}
        report, directory = await self.run_case(agent=InvalidAgent(), fault_step="synthesize")
        self.assertEqual(report["status"], "failed")
        self.assertEqual(sum(e["event"] == "job_submitted" for e in self.events(directory)), 1)

    async def test_agent_can_choose_same_device_retry(self):
        class RetryAgent(RuleAgent):
            async def recover(self, context):
                return {"action": "cancel_and_retry", "replacement_device_id": None, "reason": "retry after cancellation"}
        report, _ = await self.run_case(agent=RetryAgent(), fault_step="infect")
        self.assertEqual(report["status"], "succeeded")
        self.assertEqual(report["effects_by_device"]["infect-primary"], 1)
        self.assertEqual(report["effects_by_device"]["infect-backup"], 0)

    async def test_missing_api_configuration_is_not_silent_offline_fallback(self):
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "", "OPENROUTER_MODEL": ""}):
            report, _ = await self.run_case(agent_mode="openrouter")
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["agent"], "openrouter")
        self.assertIn("OPENROUTER_API_KEY", report["error"])
        self.assertNotIn("plan", report)

    async def test_communication_exception_leaves_partial_report(self):
        class BrokenAgent(RuleAgent):
            async def recover(self, context):
                raise AgentError("Simulated provider outage")
        report, directory = await self.run_case(agent=BrokenAgent(), fault_step="infect")
        self.assertEqual(report["status"], "failed")
        self.assertEqual(list(report["results"]), ["synthesize", "prepare", "transfer"])
        self.assertTrue((directory / "report.json").is_file())

    async def test_cancellation_retains_report(self):
        class CancelledAgent(RuleAgent):
            async def plan(self, context):
                raise asyncio.CancelledError()
        report, directory = await self.run_case(agent=CancelledAgent())
        self.assertEqual(report["status"], "cancelled")
        self.assertTrue((directory / "report.md").exists())

    async def test_openrouter_mode_runs_plan_and_recovery_through_validation(self):
        agent = OpenRouterAgent("not-a-real-key", "test-model")
        def fake_request(tool_name, schema, context):
            if tool_name == "submit_plan":
                return {"candidate_ids": [item["id"] for item in context["candidates"][:2]],
                        "device_assignments": {operation: f"{operation}-primary" for operation in OPERATIONS},
                        "reason": "Mock model selected compatible devices."}
            return {"action": "cancel_and_failover", "replacement_device_id": context["alternatives"][0],
                    "reason": "Mock model selected a compatible backup."}
        with patch.object(agent, "_request", side_effect=fake_request) as api:
            report, directory = await self.run_case(agent=agent, fault_step="measure")
        self.assertEqual(report["status"], "succeeded")
        self.assertEqual(report["agent"], "openrouter")
        self.assertEqual(report["model"], "test-model")
        self.assertEqual(api.call_count, 2)
        self.assertNotIn("not-a-real-key", (directory / "events.jsonl").read_text())


class DeviceTests(unittest.IsolatedAsyncioTestCase):
    def device(self, mode="none"):
        device = SimulatedDevice("test", "synthesize", FaultInjector(1, mode, "synthesize"),
                                 lambda *args, **kwargs: None, 1, 0.01)
        self.addAsyncCleanup(device.close)
        return device

    async def test_idempotency_rejects_changed_payload_and_never_duplicates_effects(self):
        device = self.device()
        command = Command("one-order", "synthesize", PAYLOAD)
        first = await device.write(command)
        self.assertEqual(first, await device.write(command))
        await device.wait(first)
        self.assertEqual(first, await device.write(Command("one-order", "synthesize", PAYLOAD, 2)))
        changed = {**PAYLOAD, "candidate_ids": ["SIM-PHAGE-A", "SIM-PHAGE-C"]}
        with self.assertRaises(DeviceError):
            await device.write(Command("one-order", "synthesize", changed))
        self.assertEqual(device.effect_count, 1)

    async def test_busy_device_refuses_second_logical_job(self):
        device = self.device("hang")
        await device.write(Command("a", "synthesize", PAYLOAD))
        with self.assertRaises(DeviceError):
            await device.write(Command("b", "synthesize", PAYLOAD))

    async def test_wait_timeout_does_not_cancel_device_job(self):
        device = self.device("hang")
        job = await device.write(Command("a", "synthesize", PAYLOAD))
        with self.assertRaises(TimeoutError):
            await asyncio.wait_for(device.wait(job), timeout=0.01)
        self.assertEqual((await device.read(job))["state"], "running")
        self.assertTrue(await device.cancel(job))
        self.assertEqual((await device.read(job))["state"], "cancelled")

    async def test_retry_limit_is_enforced_when_faults_persist(self):
        class AlwaysHang:
            def take(self, operation):
                return "hang"
        with tempfile.TemporaryDirectory() as temporary:
            records = RunRecords(Path(temporary), echo=False)
            self.addCleanup(records.close)
            devices = {key: SimulatedDevice(key, "synthesize", AlwaysHang(), records.emit, 1, 0.01)
                       for key in ("a", "b")}
            for device in devices.values():
                self.addAsyncCleanup(device.close)
            scheduler = Scheduler(devices, RuleAgent(), records, {"recoveries": []}, 0.01)
            with self.assertRaisesRegex(WorkflowError, "two-attempt"):
                await scheduler.execute("synthesize", "a", PAYLOAD)
            self.assertEqual(sum(len(device.jobs) for device in devices.values()), 2)

    async def test_unacknowledged_cancellation_cannot_trigger_retry(self):
        device = self.device("hang")
        async def refuse_cancel(job_id):
            return False
        device.cancel = refuse_cancel
        with tempfile.TemporaryDirectory() as temporary:
            records = RunRecords(Path(temporary), echo=False)
            self.addCleanup(records.close)
            scheduler = Scheduler({"test": device}, RuleAgent(), records, {"recoveries": []}, 0.01)
            with self.assertRaisesRegex(WorkflowError, "not acknowledged"):
                await scheduler.execute("synthesize", "test", PAYLOAD)
            self.assertEqual(len(device.jobs), 1)

    async def test_completion_during_agent_decision_is_not_repeated(self):
        device = self.device()
        original_wait = device.wait
        async def lost_wait(job_id):
            await original_wait(job_id)
            await asyncio.Event().wait()
        # Make the first wait timeout before completion, then let the job finish during deliberation.
        device.time_scale = 1.0
        device.wait = lost_wait
        class SlowAgent(RuleAgent):
            async def recover(self, context):
                await asyncio.sleep(0.55)
                return await super().recover(context)
        with tempfile.TemporaryDirectory() as temporary:
            records = RunRecords(Path(temporary), echo=False)
            self.addCleanup(records.close)
            report = {"recoveries": []}
            scheduler = Scheduler({"test": device}, SlowAgent(), records, report, 0.01)
            result = await scheduler.execute("synthesize", "test", PAYLOAD)
            self.assertTrue(result["simulated"])
            self.assertEqual(device.effect_count, 1)
            self.assertEqual(report["recoveries"][0]["outcome"], "completed_during_recovery")


class InputTests(unittest.TestCase):
    def test_fasta_is_case_and_linewrap_independent_but_contig_sensitive(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "test.fa"
            path.write_text(">one\nacgt\nacgt\n")
            first = read_fasta(path)
            path.write_text(">different_header\nACGTACGT\n")
            self.assertEqual(first, read_fasta(path))
            path.write_text(">one\nACGT\n>two\nACGT\n")
            self.assertNotEqual(first.sha256, read_fasta(path).sha256)

    def test_invalid_fasta_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "test.fa"
            for content in ("", "ACGT", ">one\n", ">one\nA!CG\n", ">one\n>two\nACGT", ">\nACGT"):
                with self.subTest(content=content):
                    path.write_text(content)
                    with self.assertRaises(ValueError):
                        read_fasta(path)

    def test_toy_candidates_are_explicitly_unvalidated(self):
        candidates = mock_candidates(read_fasta(GENOME))
        self.assertTrue(all(item["source"] == "synthetic_fixture" and item["validated"] is False for item in candidates))
        self.assertTrue(all("probability" not in item for item in candidates))

    def test_bad_recovery_shapes_are_rejected(self):
        for decision in ({}, [], {"action": "execute_code", "reason": "x", "replacement_device_id": None},
                         {"action": "abort", "reason": "x", "replacement_device_id": "a"}):
            with self.subTest(decision=decision), self.assertRaises(WorkflowError):
                validate_recovery(decision, ["a"])


class ApiContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_openrouter_adapter_uses_structured_tools_without_raw_sequence(self):
        # Mock transport verifies serialization only; this is NOT a live API test.
        agent = OpenRouterAgent("not-a-real-key", "test-model")
        context = {"genome": read_fasta(GENOME).public_metadata(), "candidates": [{"id": "SIM-PHAGE-A"}],
                   "devices": [{"device_id": f"{operation}-primary", "operations": [operation]} for operation in OPERATIONS]}
        decision = {"candidate_ids": ["SIM-PHAGE-A", "SIM-PHAGE-B"],
                    "device_assignments": {operation: f"{operation}-primary" for operation in OPERATIONS}, "reason": "mock API decision"}
        response = {"choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": [{"type": "function", "function": {"name": "submit_plan", "arguments": json.dumps(decision)}}]}}]}
        with patch("phage_lab.agents.request.build_opener") as opener:
            opener.return_value.open.return_value.__enter__.return_value.read.return_value = json.dumps(response).encode()
            result = await agent.plan(context)
            req = opener.return_value.open.call_args.args[0]
            payload = json.loads(req.data)
        self.assertEqual(req.full_url, "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(req.get_header("Authorization"), "Bearer not-a-real-key")
        self.assertIsNone(req.get_header("X-api-key"))
        self.assertEqual(payload["messages"][0]["role"], "system")
        self.assertEqual(result, decision)
        self.assertEqual(payload["tools"][0]["function"]["name"], "submit_plan")
        self.assertTrue(payload["tools"][0]["function"]["strict"])
        self.assertIn("Call submit_plan", payload["messages"][1]["content"])
        self.assertNotIn("ACGTACGT", json.dumps(payload))
        self.assertNotIn("SYNTHETIC_TOY_INPUT", json.dumps(payload))

    async def test_openrouter_rejects_text_only_or_multiple_tools(self):
        agent = OpenRouterAgent("not-a-real-key", "test-model")
        tool = {"type": "function", "function": {"name": "choose_recovery", "arguments": "{}"}}
        def response(calls, finish="tool_calls", **extra):
            return {"choices": [{"finish_reason": finish, "message": {"tool_calls": calls, **extra}}]}
        bodies = [response([]), response([tool, tool]), response([tool], "length"),
                  response([tool], "content_filter"), response([tool], refusal="declined"),
                  {"error": {"message": "secret-test-value"}}, {}, [],
                  {"choices": [None]}, response([None]), response([tool], "error")]
        for arguments in ("{", "[]", "null", {}, 42):
            bodies.append(response([{"type": "function", "function": {
                "name": "choose_recovery", "arguments": arguments}}]))
        bodies.append(response([{"type": "function", "function": {"name": "wrong", "arguments": "{}"}}]))
        for body in bodies:
            with self.subTest(body=body), patch("phage_lab.agents.request.build_opener") as opener:
                opener.return_value.open.return_value.__enter__.return_value.read.return_value = json.dumps(body).encode()
                with self.assertRaises(AgentError) as caught:
                    await agent.recover({"alternatives": []})
                self.assertNotIn("secret-test-value", str(caught.exception))

    async def test_openrouter_transport_errors_are_sanitized(self):
        from urllib.error import HTTPError, URLError
        agent = OpenRouterAgent("secret-test-value", "provider/model")
        for failure in (HTTPError("https://openrouter.ai", 401, "secret-test-value", {}, None),
                        URLError("secret-test-value"), TimeoutError("secret-test-value")):
            with self.subTest(failure=type(failure)), patch("phage_lab.agents.request.build_opener") as opener:
                opener.return_value.open.side_effect = failure
                with self.assertRaises(AgentError) as caught:
                    await agent.recover({"alternatives": []})
                self.assertNotIn("secret-test-value", str(caught.exception))

    async def test_openrouter_recovery_parses_function_arguments(self):
        decision = {"action": "abort", "replacement_device_id": None, "reason": "No safe recovery."}
        body = {"choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": [
            {"type": "function", "function": {"name": "choose_recovery", "arguments": json.dumps(decision)}}]}}]}
        with patch("phage_lab.agents.request.build_opener") as opener:
            opener.return_value.open.return_value.__enter__.return_value.read.return_value = json.dumps(body).encode()
            self.assertEqual(await OpenRouterAgent("test", "provider/model").recover({"alternatives": []}), decision)


if __name__ == "__main__":
    unittest.main()


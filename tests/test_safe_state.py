"""The apparatus-safety contract.

These tests exist because stopping the software is not the same as the bench
being safe. They check that a real driver must declare what its hardware does
when a step is abandoned, that the controller asks for it on every stop path,
and that a device which cannot confirm is reported as unknown rather than
quietly treated as fine.
"""

from pathlib import Path
import tempfile
import unittest

from phage_lab.devices import (
    Command,
    DeviceError,
    DeviceUnavailable,
    SafeStateError,
    validate_safe_state,
)
from phage_lab.records import RunRecords
from phage_lab.workflow import (
    PhysicalStateLedger,
    Scheduler,
    WorkflowError,
    run_experiment,
    validate_experiment_inputs,
)

from support import CANDIDATES, WORKFLOW, AlwaysHang, FaultInjector, RealDeviceDouble, make_test_fleet

PAYLOAD = {"sample_id": "sample-test", "candidate_ids": [CANDIDATES[0]["id"]]}


class StaticAgent:
    name = "static-test-agent"

    async def plan(self, context):
        return {"candidate_ids": [context["candidates"][0]["id"]],
                "device_assignments": {
                    operation: next(device["device_id"] for device in context["devices"]
                                    if operation in device["operations"])
                    for operation in context["workflow"]},
                "reason": "Static plan for the safe-state tests."}

    async def recover(self, context):
        return {"action": "abort", "replacement_device_id": None,
                "reason": "Stop rather than repeat a physical action."}


def genome_at(root: Path) -> Path:
    path = root / "host.fasta"
    path.write_text(">host\nACGTACGT\n")
    return path


class ManifestTests(unittest.TestCase):
    def test_a_real_driver_must_declare_a_safe_state(self):
        devices = {"prepare-1": RealDeviceDouble("prepare-1", "prepare", safe_state=None)}
        with self.assertRaisesRegex(WorkflowError, "does not declare safe_state"):
            validate_experiment_inputs(CANDIDATES, devices, "real_hardware")

    def test_the_policy_must_be_one_the_controller_understands(self):
        manifest = {"safe_state": {"policy": "probably_fine", "retains_hazard": False,
                                   "description": "x"}}
        with self.assertRaisesRegex(DeviceError, "unknown safe_state policy"):
            validate_safe_state(manifest, "prepare-1")

    def test_retains_hazard_must_be_stated_explicitly(self):
        manifest = {"safe_state": {"policy": "park_and_release", "description": "x"}}
        with self.assertRaisesRegex(DeviceError, "retains_hazard"):
            validate_safe_state(manifest, "prepare-1")

    def test_holding_position_cannot_claim_to_retain_no_hazard(self):
        # A device frozen mid-step is still holding what it held. Letting a
        # driver claim otherwise would understate someone's exposure.
        for policy in ("contained_hold", "operator_required"):
            manifest = {"safe_state": {"policy": policy, "retains_hazard": False,
                                       "description": "frozen in place"}}
            with self.subTest(policy=policy), self.assertRaisesRegex(DeviceError, "still"):
                validate_safe_state(manifest, "prepare-1")

    def test_the_safe_state_must_be_described_in_words(self):
        manifest = {"safe_state": {"policy": "park_and_release", "retains_hazard": False}}
        with self.assertRaisesRegex(DeviceError, "describe its safe state"):
            validate_safe_state(manifest, "prepare-1")

    def test_a_declared_safe_state_is_accepted(self):
        devices = {"prepare-1": RealDeviceDouble("prepare-1", "prepare")}
        validate_experiment_inputs(CANDIDATES, devices, "real_hardware")

    def test_virtual_twins_declare_one_too(self):
        # The safe-state path has to be exercised before real hardware exists.
        fleet = make_test_fleet(lambda *a, **k: None, replicas=1)
        for device in fleet.values():
            validate_safe_state(device.describe(), device.device_id)


class LedgerTests(unittest.IsolatedAsyncioTestCase):
    def ledger(self):
        self.events = []
        return PhysicalStateLedger(
            lambda event, **details: self.events.append({"event": event, **details}))

    async def test_a_confirmed_hazard_free_state_reports_safe(self):
        ledger = self.ledger()
        device = RealDeviceDouble("prepare-1", "prepare")
        ledger.touched_device("prepare-1", device)
        await ledger.settle("run failed")
        summary = ledger.summary(physical_execution=True)
        self.assertEqual(summary["status"], "safe")
        self.assertFalse(summary["operator_action_required"])
        self.assertEqual(device.safe_state_requests, ["run failed"])

    async def test_an_unconfirmed_safe_state_reports_unknown(self):
        ledger = self.ledger()
        device = RealDeviceDouble("prepare-1", "prepare", safe_state_entered=False)
        ledger.touched_device("prepare-1", device)
        await ledger.settle("run failed")
        summary = ledger.summary(physical_execution=True)
        self.assertEqual(summary["status"], "unknown")
        self.assertTrue(summary["operator_action_required"])
        self.assertIn("potentially holding hazardous material", summary["note"])

    async def test_a_hazard_retaining_policy_reports_hazard_retained(self):
        ledger = self.ledger()
        device = RealDeviceDouble(
            "prepare-1", "prepare",
            safe_state={"policy": "contained_hold", "retains_hazard": True,
                        "description": "Freezes in place inside the enclosure."})
        ledger.touched_device("prepare-1", device)
        await ledger.settle("run failed")
        summary = ledger.summary(physical_execution=True)
        self.assertEqual(summary["status"], "hazard_retained")
        self.assertTrue(summary["operator_action_required"])

    async def test_the_worst_device_decides_the_overall_status(self):
        ledger = self.ledger()
        ledger.touched_device("a", RealDeviceDouble("a", "prepare"))
        ledger.touched_device("b", RealDeviceDouble("b", "infect", safe_state_entered=False))
        await ledger.settle("run failed")
        self.assertEqual(ledger.summary(physical_execution=True)["status"], "unknown")

    async def test_a_driver_without_the_hook_is_unknown_not_assumed_safe(self):
        class NoSafeState(RealDeviceDouble):
            enter_safe_state = None

        ledger = self.ledger()
        ledger.touched_device("prepare-1", NoSafeState("prepare-1", "prepare"))
        await ledger.settle("run failed")
        summary = ledger.summary(physical_execution=True)
        self.assertEqual(summary["status"], "unknown")
        self.assertIn("no enter_safe_state", summary["devices"]["prepare-1"]["detail"])

    async def test_a_raising_driver_is_unknown_not_a_crash(self):
        for failure in (SafeStateError("no confirmation"), DeviceUnavailable("gone"),
                        RuntimeError("driver bug")):
            with self.subTest(failure=type(failure).__name__):
                class Raising(RealDeviceDouble):
                    async def enter_safe_state(self, reason):
                        raise failure

                ledger = self.ledger()
                ledger.touched_device("prepare-1", Raising("prepare-1", "prepare"))
                await ledger.settle("run failed")
                self.assertEqual(ledger.summary(physical_execution=True)["status"], "unknown")

    async def test_a_lying_driver_cannot_report_safe_without_a_confirmation(self):
        class Vague(RealDeviceDouble):
            async def enter_safe_state(self, reason):
                return {"policy": "park_and_release"}  # no `entered`

        ledger = self.ledger()
        ledger.touched_device("prepare-1", Vague("prepare-1", "prepare"))
        await ledger.settle("run failed")
        self.assertEqual(ledger.summary(physical_execution=True)["status"], "unknown")


class SchedulerStopPathTests(unittest.IsolatedAsyncioTestCase):
    """Every way a step can be abandoned must leave a physical-state record."""

    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def records(self):
        records = RunRecords(self.root / "runs", echo=False)
        self.addCleanup(records.close)
        return records

    async def test_an_unreachable_device_is_recorded_as_unknown(self):
        records = self.records()
        fleet = make_test_fleet(records.emit, FaultInjector(1, "unreachable", "prepare"),
                                operations=("prepare",))
        for device in fleet.values():
            self.addAsyncCleanup(device.close)
        ledger = PhysicalStateLedger(records.emit)
        scheduler = Scheduler(fleet, StaticAgent(), records, {"recoveries": []},
                              timeout_seconds=0.05, ledger=ledger)
        with self.assertRaises(WorkflowError):
            await scheduler.execute("prepare", "virtual-prepare-1", PAYLOAD)
        summary = ledger.summary(physical_execution=True)
        self.assertEqual(summary["status"], "unknown")
        self.assertIn("unreachable", summary["devices"]["virtual-prepare-1"]["detail"])

    async def test_an_unacknowledged_cancellation_is_recorded_as_unknown(self):
        records = self.records()
        fleet = make_test_fleet(records.emit, AlwaysHang(), operations=("prepare",), replicas=1)
        device = fleet["virtual-prepare"]
        self.addAsyncCleanup(device.close)

        async def refuse_cancel(job_id):
            return False
        device.cancel = refuse_cancel

        ledger = PhysicalStateLedger(records.emit)
        scheduler = Scheduler(fleet, _RetryAgent(), records, {"recoveries": []},
                              timeout_seconds=0.05, ledger=ledger)
        with self.assertRaisesRegex(WorkflowError, "not acknowledged"):
            await scheduler.execute("prepare", "virtual-prepare", PAYLOAD)
        summary = ledger.summary(physical_execution=True)
        self.assertEqual(summary["status"], "unknown")
        self.assertIn("may still be executing",
                      summary["devices"]["virtual-prepare"]["detail"])


class _RetryAgent:
    name = "retry-agent"

    async def plan(self, context):
        raise AssertionError("not used")

    async def recover(self, context):
        return {"action": "cancel_and_retry", "replacement_device_id": None,
                "reason": "Retry only after cancellation is acknowledged."}


class RunReportTests(unittest.IsolatedAsyncioTestCase):
    async def run_case(self, devices, agent=None, **kwargs):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report, directory = await run_experiment(
                genome_at(root), root / "runs", sample_id="sample-001",
                candidates=CANDIDATES, devices=devices,
                workflow={"prepare": ()}, agent=agent or StaticAgent(),
                execution_mode="real_hardware", timeout_seconds=1, echo=False, **kwargs)
            return report, (directory / "report.md").read_text()

    async def test_a_successful_run_makes_no_safe_state_request(self):
        devices = {"prepare-1": RealDeviceDouble("prepare-1", "prepare")}
        report, rendered = await self.run_case(devices)
        self.assertEqual(report["status"], "succeeded")
        self.assertEqual(report["physical_state"]["status"], "not_requested")
        self.assertFalse(report["physical_state"]["operator_action_required"])
        self.assertEqual(devices["prepare-1"].safe_state_requests, [])

    async def test_a_failed_run_requests_safe_state_and_reports_it(self):
        class Failing(RealDeviceDouble):
            async def wait(self, job_id):
                raise DeviceError("instrument reported a fault")

        devices = {"prepare-1": Failing("prepare-1", "prepare")}
        report, rendered = await self.run_case(devices)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["physical_state"]["status"], "safe")
        self.assertEqual(len(devices["prepare-1"].safe_state_requests), 1)
        self.assertIn("设备物理状态", rendered)

    async def test_an_unconfirmed_safe_state_is_flagged_in_the_report(self):
        class Failing(RealDeviceDouble):
            async def wait(self, job_id):
                raise DeviceError("instrument reported a fault")

        devices = {"prepare-1": Failing("prepare-1", "prepare", safe_state_entered=False)}
        report, rendered = await self.run_case(devices)
        self.assertEqual(report["physical_state"]["status"], "unknown")
        self.assertTrue(report["physical_state"]["operator_action_required"])
        self.assertTrue(any("did not confirm" in item for item in report["limitations"]))
        self.assertIn("需要人工处理", rendered)

    async def test_virtual_runs_say_no_apparatus_was_involved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            class Failing(StaticAgent):
                async def plan(self, context):
                    raise RuntimeError("stop before any device work")

            report, _ = await run_experiment(
                genome_at(root), root / "runs", sample_id="sample-001",
                candidates=CANDIDATES, devices=None, workflow=WORKFLOW,
                agent=Failing(), execution_mode="virtual_hardware",
                timeout_seconds=1, echo=False)
            self.assertEqual(report["status"], "failed")
            self.assertIn("Virtual hardware", report["physical_state"]["note"])


class ExampleAdapterTests(unittest.IsolatedAsyncioTestCase):
    """The shipped example adapter must satisfy the contract it demonstrates."""

    def setUp(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples" / "adapters"))
        from http_instrument import HttpInstrument, _serve_stub
        self.HttpInstrument = HttpInstrument
        self.server, _, self.base_url = _serve_stub()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def device(self, **kwargs):
        return self.HttpInstrument(
            "liquid-handler-1", ["prepare"], self.base_url,
            safe_state_policy=kwargs.get("policy", "park_and_release"),
            safe_state_retains_hazard=kwargs.get("retains", False),
            safe_state_description="Parks axes clear and ejects the tip to waste.")

    async def test_the_example_manifest_passes_real_hardware_validation(self):
        device = self.device()
        self.addAsyncCleanup(device.close)
        validate_experiment_inputs(CANDIDATES, {"liquid-handler-1": device}, "real_hardware")

    async def test_the_example_adapter_runs_a_real_hardware_experiment(self):
        device = self.device()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report, _ = await run_experiment(
                genome_at(root), root / "runs", sample_id="sample-001",
                candidates=CANDIDATES, devices={"liquid-handler-1": device},
                workflow={"prepare": ()}, agent=StaticAgent(),
                execution_mode="real_hardware", timeout_seconds=5, echo=False)
            self.assertEqual(report["status"], "succeeded")
            self.assertTrue(report["physical_execution"])

    async def test_the_example_adapter_is_idempotent_per_command_id(self):
        device = self.device()
        self.addAsyncCleanup(device.close)
        command = Command("run:prepare", "prepare", PAYLOAD)
        first = await device.write(command)
        self.assertEqual(first, await device.write(command))

    async def test_an_unreachable_example_adapter_raises_device_unavailable(self):
        device = self.HttpInstrument(
            "liquid-handler-1", ["prepare"], "http://127.0.0.1:1",
            safe_state_policy="park_and_release", safe_state_retains_hazard=False,
            safe_state_description="x")
        self.addAsyncCleanup(device.close)
        with self.assertRaises(DeviceUnavailable):
            await device.read("job-1")
        # And its safe-state request must surface as unconfirmed, not as success.
        with self.assertRaises(SafeStateError):
            await device.enter_safe_state("test")


if __name__ == "__main__":
    unittest.main()

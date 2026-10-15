import asyncio
from html.parser import HTMLParser
import http.client
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from phage_lab.agents import RuleAgent
from phage_lab.dashboard import DashboardServer, RunManager, WEB
from phage_lab.provenance import source_identity


class SourceIdentityTests(unittest.TestCase):
    def test_zip_identity_needs_no_git_and_ignores_run_data_and_line_endings(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "phage_lab").mkdir()
            file = root / "phage_lab" / "main.py"
            file.write_bytes(b"print('demo')\n")
            first = source_identity(root)
            self.assertIsNone(first["git_commit"])
            self.assertEqual(first["source_files"], 1)
            (root / "runs").mkdir()
            (root / "runs" / "report.json").write_text('{"status":"succeeded"}')
            file.write_bytes(b"print('demo')\r\n")
            self.assertEqual(first["source_sha256"], source_identity(root)["source_sha256"])
            file.write_text("print('edited')\n")
            self.assertNotEqual(first["source_sha256"], source_identity(root)["source_sha256"])

    def test_web_assets_are_part_of_source_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "phage_lab" / "web").mkdir(parents=True)
            file = root / "phage_lab" / "web" / "app.js"
            file.write_text("const version = 1;\n")
            before = source_identity(root)
            file.write_text("const version = 2;\n")
            self.assertNotEqual(before["source_sha256"], source_identity(root)["source_sha256"])


class DashboardTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict("os.environ", {"OPENROUTER_API_KEY": "", "OPENROUTER_MODEL": ""})
        environment.start()
        self.addCleanup(environment.stop)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.manager = RunManager(self.root, time_scale=0.05)
        self.server = DashboardServer(0, self.manager)
        self.worker = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True)
        self.worker.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        if self.manager.thread:
            self.manager.thread.join(timeout=5)
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=5)

    def request(self, method, path, data=None, authorized=True, headers=None):
        request_headers = {}
        if authorized:
            request_headers["X-Lab-Token"] = self.manager.token
        if data is not None:
            request_headers["Content-Type"] = "application/json"
        request_headers.update(headers or {})
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request(method, path, body=None if data is None else json.dumps(data), headers=request_headers)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def start_and_finish(self, **options):
        code, _, body = self.request("POST", "/api/runs", {"seed": 42, "fault": "hang", **options})
        self.assertEqual(code, 202, body)
        self.manager.thread.join(timeout=5)
        self.assertFalse(self.manager.busy)
        self.assertIsNone(self.manager.last_error)
        return self.manager.active_run

    def test_static_assets_and_literal_dom_targets_exist(self):
        for path in ("/", "/app.js", "/style.css"):
            code, headers, body = self.request("GET", path)
            self.assertEqual(code, 200)
            self.assertTrue(body)
            self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        class IdParser(HTMLParser):
            ids = set()
            def handle_starttag(self, tag, attrs):
                self.ids.update(value for key, value in attrs if key == "id")
        parser = IdParser()
        parser.feed((WEB / "index.html").read_text())
        referenced = set(re.findall(r'\$\("([\w-]+)"\)', (WEB / "app.js").read_text()))
        self.assertFalse(referenced - parser.ids)

    def test_mutations_require_local_origin_and_session_token(self):
        for endpoint in ("/api/runs", "/api/config"):
            self.assertEqual(self.request("POST", endpoint, {}, authorized=False)[0], 403)
            self.assertEqual(self.request("POST", endpoint, {}, headers={"Origin": "https://other.example"})[0], 403)
            self.assertEqual(self.request("POST", endpoint, {}, headers={"X-Lab-Token": "é"})[0], 403)
        self.assertEqual(self.request("GET", "/api/status", headers={"Host": "hostile.example"})[0], 403)

    def test_status_does_not_expose_api_key(self):
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "secret-test-value", "OPENROUTER_MODEL": "test-model"}):
            self.manager = self.server.manager = RunManager(self.root)
            code, _, body = self.request("GET", "/api/status")
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(body)["openrouter_ready"])
        self.assertNotIn(b"secret-test-value", body)

    def test_panel_api_config_drives_both_openrouter_decisions_without_logging_secret(self):
        key = "fake-panel-key-for-test"
        code, _, body = self.request("POST", "/api/config", {"api_key": key, "model": "test-model"})
        self.assertEqual(code, 200, body)
        self.assertTrue(json.loads(body)["openrouter_ready"])
        self.assertEqual(json.loads(body)["api_config_source"], "panel")
        self.assertNotIn(key.encode(), body)
        # Saving config should neither invoke the API nor create run/config files.
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertEqual(os.environ.get("OPENROUTER_API_KEY"), "")
        calls = []
        def reply(agent, tool, schema, context):
            self.assertEqual(agent._api_key, key)
            self.assertEqual(agent.model, "test-model")
            calls.append(tool)
            rule = RuleAgent()
            return asyncio.run(rule.plan(context) if tool == "submit_plan" else rule.recover(context))
        with patch("phage_lab.agents.OpenRouterAgent._request", autospec=True, side_effect=reply):
            run_id = self.start_and_finish(agent="openrouter", fault_step="synthesize")
        self.assertEqual(calls, ["submit_plan", "choose_recovery"])
        snapshot = self.manager.snapshot(run_id)
        self.assertEqual(snapshot["report"]["status"], "succeeded")
        self.assertEqual(snapshot["report"]["agent"], "openrouter")
        self.assertEqual(snapshot["report"]["model"], "test-model")
        self.assertNotIn(key, json.dumps(snapshot))
        for path in ("/api/status", "/api/runs", f"/api/runs/{run_id}"):
            self.assertNotIn(key.encode(), self.request("GET", path)[2])
        for path in self.root.rglob("*"):
            if path.is_file():
                self.assertNotIn(key.encode(), path.read_bytes())

    def test_short_model_config_reaches_openrouter_and_is_reused_for_recovery(self):
        # Mock only HTTP transport: exercise config, resolution, serialization and validation.
        requests = []
        def reply(req, timeout):
            requests.append(req)
            if req.get_method() == "GET":
                self.assertEqual(req.full_url, "https://openrouter.ai/api/v1/models")
                self.assertIsNone(req.get_header("Authorization"))
                body = {"data": [{"id": "openai/gpt-6-astra"}]}
            else:
                self.assertEqual(req.get_header("Authorization"), "Bearer fake-panel-key")
                payload = json.loads(req.data)
                self.assertEqual(payload["model"], "openai/gpt-6-astra")
                name = payload["tools"][0]["function"]["name"]
                context = json.loads(payload["messages"][1]["content"].split("<context>\n")[1].split("\n</context>")[0])
                rule = RuleAgent()
                decision = asyncio.run(rule.plan(context) if name == "submit_plan" else rule.recover(context))
                body = {"choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": [
                    {"type": "function", "function": {"name": name, "arguments": json.dumps(decision)}}]}}]}
            response = MagicMock()
            response.__enter__.return_value.read.return_value = json.dumps(body).encode()
            return response
        with patch("phage_lab.agents.request.build_opener") as opener:
            opener.return_value.open.side_effect = reply
            code, _, body = self.request("POST", "/api/config", {"api_key": "fake-panel-key", "model": "gpt-6-astra"})
            self.assertEqual(code, 200, body)
            opener.assert_not_called()
            run_id = self.start_and_finish(agent="openrouter", fault_step="synthesize")
        report = self.manager.snapshot(run_id)["report"]
        self.assertEqual(report["status"], "succeeded")
        self.assertEqual(report["model"], "gpt-6-astra")
        self.assertEqual(report["resolved_model"], "openai/gpt-6-astra")
        self.assertEqual([req.get_method() for req in requests], ["GET", "POST", "POST"])

    def test_panel_accepts_short_full_and_variant_model_names(self):
        for model in ("gpt-6-astra", "claude-opus-5-5", "provider/model", "provider/model:free"):
            with self.subTest(model=model):
                code, _, body = self.request("POST", "/api/config", {"api_key": "fake-key", "model": model})
                self.assertEqual(code, 200, body)
                self.assertEqual(json.loads(body)["model"], model)

    def test_config_can_retain_replace_clear_and_is_not_persisted(self):
        self.assertEqual(self.request("POST", "/api/config", {"api_key": "fake-first-key", "model": "model-a"})[0], 200)
        self.assertEqual(self.request("POST", "/api/config", {"api_key": "", "model": "model-b"})[0], 200)
        self.assertEqual(self.manager._api_key, "fake-first-key")
        self.assertEqual(self.manager.status()["model"], "model-b")
        self.assertEqual(self.request("POST", "/api/config", {"api_key": "fake-replacement", "model": "model-b"})[0], 200)
        self.assertEqual(self.manager._api_key, "fake-replacement")
        # Reloads read the same manager; a new process/manager starts without the panel secret.
        self.assertTrue(json.loads(self.request("GET", "/api/status")[2])["api_key_configured"])
        self.assertFalse(RunManager(self.root).status()["openrouter_ready"])
        self.assertEqual(self.request("POST", "/api/config", {"clear": True})[0], 200)
        self.assertEqual(self.manager._api_key, "")
        self.assertFalse(self.manager.status()["api_key_configured"])
        self.assertEqual(self.request("POST", "/api/runs", {"agent": "openrouter"})[0], 400)

    def test_invalid_config_leaves_existing_config_unchanged_and_does_not_echo_secrets(self):
        self.manager.configure_api({"api_key": "fake-valid-key", "model": "test-model"})
        for options in ([], {"clear": 1}, {"clear": True, "api_key": "fake-hidden-secret"},
                        {"api_key": "fake-hidden-secret\nheader", "model": "test-model"},
                        {"api_key": "fake-hidden-secreté", "model": "test-model"},
                        {"api_key": "fake-hidden-secret", "model": "bad model"},
                        {"api_key": 123, "model": "test-model"}):
            code, _, body = self.request("POST", "/api/config", options)
            self.assertEqual(code, 400, body)
            self.assertNotIn(b"fake-hidden-secret", body)
            self.assertEqual(self.manager._api_key, "fake-valid-key")
            self.assertEqual(self.manager.status()["model"], "test-model")

    def test_config_changes_rejected_during_run(self):
        self.manager.configure_api({"api_key": "fake-valid-key", "model": "test-model"})
        self.assertEqual(self.request("POST", "/api/runs", {"fault_step": "measure"})[0], 202)
        for options in ({"clear": True}, {"api_key": "fake-new-key", "model": "other-model"}):
            self.assertEqual(self.request("POST", "/api/config", options)[0], 409)
        self.assertEqual(self.manager._api_key, "fake-valid-key")

    def test_clear_does_not_reload_environment_credentials_until_restart(self):
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "fake-env-key", "OPENROUTER_MODEL": "env-model"}):
            manager = RunManager(self.root)
            self.assertTrue(manager.status()["openrouter_ready"])
            manager.configure_api({"clear": True})
            self.assertFalse(manager.status()["openrouter_ready"])
            self.assertTrue(RunManager(self.root).status()["openrouter_ready"])

    def test_full_http_run_recovery_history_cursor_and_downloads(self):
        run_id = self.start_and_finish(fault_step="synthesize")
        code, _, body = self.request("GET", f"/api/runs/{run_id}")
        self.assertEqual(code, 200)
        snapshot = json.loads(body)
        report, events = snapshot["report"], snapshot["events"]
        self.assertEqual(report["status"], "succeeded")
        self.assertEqual(len(report["results"]), 5)
        self.assertEqual(len(report["source"]["source_sha256"]), 64)
        cancelled = next(event["seq"] for event in events if event["event"] == "cancellation_acknowledged")
        retry = next(event["seq"] for event in events if event["event"] == "job_submitted" and event["details"]["attempt"] == 2)
        self.assertLess(cancelled, retry)
        code, _, body = self.request("GET", f"/api/runs/{run_id}?after={events[-1]['seq']}")
        self.assertEqual(json.loads(body)["events"], [])
        self.assertEqual(json.loads(self.request("GET", "/api/runs")[2])["runs"][0]["run_id"], run_id)
        for filename in ("report.md", "report.json", "events.jsonl"):
            code, headers, body = self.request("GET", f"/api/runs/{run_id}/download/{filename}")
            self.assertEqual(code, 200)
            self.assertIn("attachment", headers["Content-Disposition"])
            self.assertTrue(body)

    def test_unreachable_run_stays_failed_and_downloadable(self):
        run_id = self.start_and_finish(fault="unreachable", fault_step="prepare")
        report = json.loads(self.request("GET", f"/api/runs/{run_id}")[2])["report"]
        self.assertEqual(report["status"], "failed")
        self.assertEqual(list(report["results"]), ["synthesize"])

    def test_uploaded_fasta_is_used_and_temporary_sequence_is_removed(self):
        run_id = self.start_and_finish(fault="none", genome_text=">private-header\nACGTACGT\n")
        snapshot = self.manager.snapshot(run_id)
        self.assertEqual(snapshot["report"]["genome"]["bases"], 8)
        self.assertNotIn("private-header", json.dumps(snapshot))
        self.assertFalse(list(self.root.glob(".input-*")))

    def test_missing_live_config_invalid_parameters_and_duplicate_start(self):
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "", "OPENROUTER_MODEL": ""}):
            self.assertEqual(self.request("POST", "/api/runs", {"agent": "openrouter"})[0], 400)
        for invalid in ({"seed": True}, {"seed": 2**32}, {"agent": "other"}, {"fault_step": "unknown"}, {"path": "/etc/passwd"}, {"genome_text": ""}):
            self.assertEqual(self.request("POST", "/api/runs", invalid)[0], 400)
        self.assertEqual(self.request("POST", "/api/runs", {"fault_step": "measure"})[0], 202)
        self.assertEqual(self.request("POST", "/api/runs", {})[0], 409)

    def test_unknown_paths_and_nonrun_directories_are_not_served(self):
        (self.root / "private.txt").write_text("private")
        self.assertEqual(self.request("GET", "/private.txt")[0], 404)
        self.assertEqual(self.request("GET", "/api/runs/../download/report.json")[0], 400)

    def test_old_runs_without_source_remain_readable_after_restart(self):
        run_id = self.start_and_finish(fault="none")
        path = self.root / run_id / "report.json"
        report = json.loads(path.read_text())
        report.pop("source")
        path.write_text(json.dumps(report))
        restarted = RunManager(self.root)
        self.assertEqual(restarted.history()[0]["status"], "succeeded")
        self.assertNotIn("source", restarted.snapshot(run_id)["report"])


if __name__ == "__main__":
    unittest.main()



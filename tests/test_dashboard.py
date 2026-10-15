from html.parser import HTMLParser
import http.client
import json
from pathlib import Path
import re
import tempfile
import threading
import unittest
from unittest.mock import patch

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
        self.assertEqual(self.request("POST", "/api/runs", {}, authorized=False)[0], 403)
        self.assertEqual(self.request("POST", "/api/runs", {}, headers={"Origin": "https://other.example"})[0], 403)
        self.assertEqual(self.request("POST", "/api/runs", {}, headers={"X-Lab-Token": "é"})[0], 403)
        self.assertEqual(self.request("GET", "/api/status", headers={"Host": "hostile.example"})[0], 403)

    def test_status_does_not_expose_api_key(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "secret-test-value", "ANTHROPIC_MODEL": "test-model"}):
            code, _, body = self.request("GET", "/api/status")
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(body)["anthropic_ready"])
        self.assertNotIn(b"secret-test-value", body)

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
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "", "ANTHROPIC_MODEL": ""}):
            self.assertEqual(self.request("POST", "/api/runs", {"agent": "anthropic"})[0], 400)
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

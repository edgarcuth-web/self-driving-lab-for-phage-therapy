"""Read-only dashboard boundaries; no domain execution or user-data upload."""

from http.client import HTTPConnection
from threading import Thread
import json
import unittest

from phage_lab.dashboard import create_server


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.server = create_server(0)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path, method="GET", headers=None, body=None):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def test_serves_ui_and_assets_with_security_headers(self):
        for path, marker in [("/", "临床样本"), ("/app.js", "render"),
                             ("/workflow-model.js", "not_estimated"), ("/style.css", ":root")]:
            status, headers, body = self.request(path)
            self.assertEqual(status, 200)
            self.assertIn(marker, body.decode("utf-8"))
            self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
            self.assertEqual(headers["X-Content-Type-Options"], "nosniff")

    def test_does_not_expose_repository_files_or_mutations(self):
        for path in ("/AGENTS.md", "/../AGENTS.md", "/%2e%2e/AGENTS.md", "/api/runs", "/web/"):
            self.assertEqual(self.request(path)[0], 404)
        self.assertEqual(self.request("/", "POST")[0], 405)
        self.assertEqual(self.request("/", "HEAD")[2], b"")

    def test_rejects_untrusted_host_and_origin(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        self.assertEqual(self.request("/", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.request("/", headers={"Origin": "https://evil.example"})[0], 403)

    def test_report_configuration_requires_token_and_does_not_echo_secrets(self):
        status, _, body = self.request('/api/report-config')
        self.assertEqual(status, 200)
        config = json.loads(body)
        payload = json.dumps({'api_key': 'test-private-key'})
        self.assertEqual(self.request('/api/report-config', 'POST', body=payload)[0], 403)
        headers = {'X-Lab-Token': config['token'], 'Content-Type': 'application/json'}
        status, _, body = self.request('/api/report-config', 'POST', headers, payload)
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)['configured'])
        self.assertNotIn(b'test-private-key', body)
        self.assertNotIn(b'test-private-key', self.request('/api/report-config')[2])
        headers['Origin'] = 'https://evil.example'
        self.assertEqual(self.request('/api/report-config', 'POST', headers, payload)[0], 403)

    def test_report_api_rejects_unbounded_bodies_and_unsupported_inputs(self):
        token = json.loads(self.request('/api/report-config')[2])['token']
        headers = {'X-Lab-Token': token, 'Content-Type': 'application/json'}
        self.assertEqual(self.request('/api/reports', 'POST', headers, '{}')[0], 400)
        self.assertEqual(self.request('/api/reports', 'POST', headers, 'x' * 100_001)[0], 413)
        self.assertEqual(self.request('/api/reports/not-a-report')[0], 404)

"""Loopback workflow presentation and optional Kimi report drafts; no experiments."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import re
import secrets
from urllib.parse import urlsplit
import webbrowser

from .clinical_reports import ReportService


WEB = Path(__file__).resolve().parent / "web"
ASSETS = {"/": ("index.html", "text/html"), "/index.html": ("index.html", "text/html"),
          "/style.css": ("style.css", "text/css"), "/app.js": ("app.js", "text/javascript"),
          "/report-ui.js": ("report-ui.js", "text/javascript"),
          "/workflow-model.js": ("workflow-model.js", "text/javascript")}


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Metadata and URLs must not become patient-data logs.

    def _trusted(self):
        port = self.server.server_port
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host") not in allowed:
            self.send_error(403, "Loopback Host required")
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in {f"http://{host}" for host in allowed}:
            self.send_error(403, "Same-origin access required")
            return False
        return True

    def _respond(self, status, content, mime='application/json', head=False):
        if not isinstance(content, bytes):
            content = json.dumps(content, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header("Content-Type", f"{mime}; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; "
                         "object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        if not head:
            self.wfile.write(content)

    def _serve(self, head=False):
        if not self._trusted():
            return
        path = urlsplit(self.path).path
        if path == '/api/report-config':
            self._respond(200, {**self.server.report_service.configuration(), 'token': self.server.token}, head=head)
            return
        if path.startswith('/api/reports/'):
            job_id = path.rsplit('/', 1)[-1]
            try:
                if not re.fullmatch('[0-9a-f]{32}', job_id):
                    raise KeyError()
                self._respond(200, self.server.report_service.get(job_id), head=head)
            except KeyError:
                self._respond(404, {'error': '报告不存在或已过期。'}, head=head)
            return
        asset = ASSETS.get(path)
        if asset is None:
            self.send_error(404)
            return
        filename, mime = asset
        content = (WEB / filename).read_bytes()
        self._respond(200, content, mime, head)

    def do_GET(self):
        self._serve()

    def do_HEAD(self):
        self._serve(head=True)

    def do_POST(self):
        if not self._trusted():
            return
        path = urlsplit(self.path).path
        if path not in {'/api/report-config', '/api/reports'}:
            self.send_error(405, 'Unknown mutation')
            return
        if not secrets.compare_digest(self.headers.get('X-Lab-Token', ''), self.server.token):
            self._respond(403, {'error': '本次服务令牌无效，请刷新页面。'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 100_000:
                self._respond(413, {'error': '请求必须为 1–100000 字节。'})
                return
            if self.headers.get_content_type() != 'application/json':
                raise ValueError('请求必须为 JSON。')
            body = json.loads(self.rfile.read(length))
            if path == '/api/report-config':
                self._respond(200, self.server.report_service.configure(body))
            else:
                if not isinstance(body, dict) or set(body) - {'snapshot', 'retry'} or 'snapshot' not in body:
                    raise ValueError('缺少工作流快照。')
                if type(body.get('retry', False)) is not bool:
                    raise ValueError('重试标记必须为布尔值。')
                self._respond(202, self.server.report_service.start(body['snapshot'], body.get('retry', False)))
        except (ValueError, UnicodeError) as error:
            # JSON parse messages do not include request data; never echo configuration.
            message = (
                '请求 JSON 格式不正确。'
                if isinstance(error, (json.JSONDecodeError, UnicodeError))
                else str(error)
            )
            self._respond(400, {'error': message})
        except RuntimeError as error:
            self._respond(409, {'error': str(error)})


def create_server(port=8765):
    server = ThreadingHTTPServer(("127.0.0.1", port), DashboardHandler)
    server.report_service = ReportService()
    server.token = secrets.token_urlsafe(32)
    return server


def dashboard(args, parser):
    if not 0 <= args.port <= 65535:
        parser.error("port must be between 0 and 65535")
    try:
        server = create_server(args.port)
    except OSError as error:
        parser.error(f"Cannot start dashboard: {error}. Try --port 8766.")
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"Phage Lab · simulated presentation: {url}", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0

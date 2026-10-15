"""Loopback-only web UI for the existing scheduler. No extra dependencies."""

import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
from urllib.parse import parse_qs, urlsplit
import webbrowser

from .agents import AnthropicAgent
from .devices import FAULT_MODES, OPERATIONS
from .provenance import source_identity
from .workflow import run_demo

ROOT = Path(__file__).resolve().parent.parent
WEB = Path(__file__).resolve().parent / "web"
RUN_ID = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{10}")
MAX_INPUT = 1_000_000
MAX_BODY = 2_000_000
MAX_LOG = 5_000_000


class RunManager:
    def __init__(self, output_root: Path, time_scale: float = 1.0):
        self.output_root = output_root.resolve()
        self.time_scale = time_scale
        self.token = secrets.token_urlsafe(32)
        self.source = source_identity()
        self.lock = threading.Lock()
        self.busy = False
        self.active_run = None
        self.last_error = None
        self.thread = None
        self._api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        self._model = os.environ.get("ANTHROPIC_MODEL", "").strip()
        self._config_source = "environment" if self._api_key or self._model else None

    def status(self) -> dict:
        with self.lock:
            return {"busy": self.busy, "active_run": self.active_run, "last_error": self.last_error,
                    "token": self.token, "source": self.source,
                    "anthropic_ready": bool(self._api_key and self._model),
                    "api_key_configured": bool(self._api_key),
                    "api_config_source": self._config_source, "model": self._model}

    def configure_api(self, options: dict) -> None:
        if not isinstance(options, dict):
            raise ValueError("API 配置格式不正确。")
        with self.lock:
            if self.busy:
                raise RuntimeError("实验运行中，请结束后再修改 API 配置。")
            if set(options) == {"clear"} and options["clear"] is True:
                self._api_key, self._model, self._config_source = "", "", None
                return
            if set(options) != {"api_key", "model"}:
                raise ValueError("请填写 API Key 和模型 ID。")
            key, model = options["api_key"], options["model"]
            if not isinstance(key, str) or not isinstance(model, str):
                raise ValueError("API Key 和模型 ID 必须为文本。")
            key, model = key.strip(), model.strip()
            # A blank key keeps the existing secret; never send it back to the browser.
            key = key or self._api_key
            if not key or len(key) > 4096 or any(not 33 <= ord(char) <= 126 for char in key):
                raise ValueError("请输入有效的 API Key，不能包含空格、换行或非 ASCII 字符。")
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}", model):
                raise ValueError("请输入模型 ID（最长 200 字符，不能包含空格）。")
            self._api_key, self._model, self._config_source = key, model, "panel"

    def directory(self, run_id: str) -> Path:
        if not RUN_ID.fullmatch(run_id):
            raise ValueError("Invalid run ID.")
        directory = self.output_root / run_id
        if directory.is_symlink() or directory.resolve().parent != self.output_root:
            raise ValueError("Run must belong to the configured output folder.")
        return directory

    def read_file(self, run_id: str, filename: str) -> bytes:
        if filename not in {"report.json", "report.md", "events.jsonl"}:
            raise ValueError("Unknown report file.")
        path = self.directory(run_id) / filename
        if path.is_symlink():
            raise ValueError("Report symlinks are not supported.")
        with path.open("rb") as handle:
            content = handle.read(MAX_LOG + 1)
        if len(content) > MAX_LOG:
            raise ValueError("Report exceeds the dashboard size limit.")
        return content

    def snapshot(self, run_id: str, after: int = 0) -> dict:
        events = []
        content = self.read_file(run_id, "events.jsonl").decode("utf-8")
        for line in content.splitlines(keepends=True):
            if not line.endswith("\n"):
                continue  # A writer may not have flushed the final line yet.
            event = json.loads(line)
            if event.get("run_id") != run_id or type(event.get("seq")) is not int:
                raise ValueError("Invalid event record.")
            if event["seq"] > after:
                events.append(event)
        try:
            report = json.loads(self.read_file(run_id, "report.json"))
        except FileNotFoundError:
            report = None
        return {"run_id": run_id, "events": events, "report": report}

    def history(self) -> list[dict]:
        if not self.output_root.exists():
            return []
        ids = sorted((path.name for path in self.output_root.iterdir()
                      if RUN_ID.fullmatch(path.name) and not path.is_symlink()), reverse=True)
        result = []
        for run_id in ids:
            try:
                snapshot = self.snapshot(run_id)
            except (OSError, ValueError, UnicodeError):
                continue
            report = snapshot["report"]
            if report:
                status = report.get("status", "unknown")
            else:
                status = "running" if self.busy and run_id == self.active_run else "interrupted"
            result.append({"run_id": run_id, "status": status,
                           "agent": report.get("agent") if report else None})
            if len(result) >= 20:
                break
        return result

    def start(self, options: dict) -> None:
        if not isinstance(options, dict) or set(options) - {"seed", "agent", "fault", "fault_step", "genome_text"}:
            raise ValueError("Unknown run options.")
        seed, agent, fault = options.get("seed", 42), options.get("agent", "rule"), options.get("fault", "hang")
        step, genome = options.get("fault_step"), options.get("genome_text")
        if type(seed) is not int or not -2**31 <= seed < 2**31:
            raise ValueError("Seed must be a 32-bit integer.")
        if agent not in ("rule", "anthropic") or fault not in FAULT_MODES or (step is not None and step not in OPERATIONS):
            raise ValueError("Unknown agent, fault or step.")
        if genome is not None and (not isinstance(genome, str) or not genome.strip()
                                   or len(genome.encode("utf-8")) > MAX_INPUT):
            raise ValueError("FASTA upload must be nonempty and at most 1 MB.")
        with self.lock:
            if self.busy:
                raise RuntimeError("A run is already active.")
            decision_agent = None
            if agent == "anthropic":
                if not self._api_key or not self._model:
                    raise ValueError("请先在面板的 Claude API 配置中填写 API Key 和模型 ID。")
                decision_agent = AnthropicAgent(self._api_key, self._model)
            self.busy, self.active_run, self.last_error = True, None, None
            self.thread = threading.Thread(target=self._run,
                args=(seed, agent, fault, step, genome, decision_agent), daemon=True)
            self.thread.start()

    def _event(self, event: dict) -> None:
        with self.lock:
            self.active_run = event["run_id"]

    def _run(self, seed, agent, fault, step, genome, decision_agent):
        try:
            self.output_root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".input-", dir=self.output_root) as temporary:
                path = ROOT / "examples" / "toy_genome.fasta"
                if genome is not None:
                    path = Path(temporary) / "input.fasta"
                    path.write_text(genome, encoding="utf-8")
                asyncio.run(run_demo(path, self.output_root, seed=seed, agent_mode=agent,
                                    fault=fault, fault_step=step, time_scale=self.time_scale,
                                    echo=False, on_event=self._event, agent=decision_agent))
        except Exception as exc:
            with self.lock:
                self.last_error = f"{type(exc).__name__}: {exc}"
        finally:
            with self.lock:
                self.busy = False


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, port: int, manager: RunManager):
        self.manager = manager
        super().__init__(("127.0.0.1", port), DashboardHandler)


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "PhageLab"

    def log_message(self, *args):
        pass

    def _trusted(self) -> bool:
        # Host checks also prevent hostile DNS names from rebinding to loopback.
        hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        if self.headers.get("Host") not in hosts:
            return False
        origin = self.headers.get("Origin")
        return origin is None or origin in {"http://" + host for host in hosts}

    def _send(self, code: int, body: bytes, mime="application/json; charset=utf-8", filename=None):
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, code, value):
        self._send(code, json.dumps(value, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        if not self._trusted():
            return self._json(403, {"error": "Local origin required."})
        manager, url = self.server.manager, urlsplit(self.path)
        try:
            assets = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
                      "/style.css": ("style.css", "text/css")}
            if url.path in assets:
                name, mime = assets[url.path]
                return self._send(200, (WEB / name).read_bytes(), mime + "; charset=utf-8")
            if url.path == "/api/status":
                return self._json(200, manager.status())
            if url.path == "/api/runs":
                return self._json(200, {"runs": manager.history()})
            match = re.fullmatch(r"/api/runs/([^/]+)(?:/download/(report\.json|report\.md|events\.jsonl))?", url.path)
            if not match:
                return self._json(404, {"error": "Not found."})
            run_id, filename = match.groups()
            if filename:
                return self._send(200, manager.read_file(run_id, filename), "application/octet-stream",
                                  f"{run_id}-{filename}")
            after = int(parse_qs(url.query).get("after", ["0"])[0])
            if after < 0:
                raise ValueError("Invalid event cursor.")
            return self._json(200, manager.snapshot(run_id, after))
        except FileNotFoundError:
            return self._json(404, {"error": "Run or report not available yet."})
        except (ValueError, UnicodeError):
            return self._json(400, {"error": "Invalid request or run data."})
        except OSError:
            return self._json(500, {"error": "Could not read local run files."})

    def do_POST(self):
        manager = self.server.manager
        token = self.headers.get("X-Lab-Token", "")
        if not self._trusted() or not token.isascii() or not secrets.compare_digest(token, manager.token):
            return self._json(403, {"error": "Reload the local dashboard to authorize this request."})
        if self.path not in {"/api/runs", "/api/config"}:
            return self._json(404, {"error": "Not found."})
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            return self._json(415, {"error": "JSON body required."})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= MAX_BODY:
                return self._json(413, {"error": "Request body must be at most 2 MB."})
            self.connection.settimeout(5)
            options = json.loads(self.rfile.read(size))
            if self.path == "/api/config":
                manager.configure_api(options)
                return self._json(200, manager.status())
            manager.start(options)
            return self._json(202, {"accepted": True})
        except (ValueError, UnicodeError) as exc:
            return self._json(400, {"error": str(exc)})
        except RuntimeError as exc:
            return self._json(409, {"error": str(exc)})
        except OSError:
            return self._json(400, {"error": "Could not read request body."})


def serve(output_root: Path, port=8765, time_scale=1.0, open_browser=True) -> None:
    manager = RunManager(output_root, time_scale)
    with DashboardServer(port, manager) as server:
        url = f"http://127.0.0.1:{server.server_port}"
        print(f"\nPhage Lab 本地面板：{url}\n保留此窗口运行；按 Ctrl+C 停止。\n", flush=True)
        if open_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\n面板已关闭。", flush=True)

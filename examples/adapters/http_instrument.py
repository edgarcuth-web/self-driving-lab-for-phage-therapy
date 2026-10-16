"""A worked example of a DeviceDriver for an instrument behind an HTTP API.

Copy this file, change the four `_request` calls to match your instrument, and
you have an adapter. Everything else here exists to satisfy the contract in
`phage_lab/devices.py`, and the comments say why each part matters rather than
what the code does.

The instrument this talks to is assumed to expose:

    POST /jobs            {"command_id", "operation", "payload"} -> {"job_id"}
    GET  /jobs/<job_id>                                          -> {"state", "result"}
    POST /jobs/<job_id>/cancel                                   -> {"cancelled": bool}
    POST /safe-state      {"reason"}                             -> {"entered", ...}
    GET  /status                                                 -> {"state", "busy"}

Almost no real instrument looks like this. A vendor SDK, a serial protocol or
OPC-UA will all differ in transport while needing the same five answers, so the
shape of the mapping is the reusable part:

  write()            your "start this" call, made idempotent per command_id
  read(job_id)       your "what is this job doing" call, asked of the device
  wait()             block until done, WITHOUT cancelling on timeout
  cancel()           your "stop" call, returning True only on acknowledgement
  enter_safe_state() your "make the apparatus safe" procedure

Run `python examples/adapters/http_instrument.py` to exercise it against a
local stand-in server, including the timeout, cancellation and safe-state
paths. That is a demonstration of the adapter, not of any real hardware.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
from urllib import error, request

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from phage_lab.devices import (  # noqa: E402
    Command,
    DeviceError,
    DeviceUnavailable,
    SafeStateError,
)

# How long to let a single HTTP call hang before treating the device as
# unreachable. This is transport-level only: it is NOT the controller's
# step deadline, and timing out here must never cancel a running job.
HTTP_TIMEOUT = 10.0
POLL_INTERVAL = 0.2


class HttpInstrument:
    """DeviceDriver over a simple job-oriented HTTP API.

    Parameters mirror what an operator actually needs to configure: where the
    instrument is, what it can do, and what its hardware does when a step is
    abandoned.
    """

    def __init__(self, device_id: str, operations: list[str], base_url: str, *,
                 safe_state_policy: str, safe_state_retains_hazard: bool,
                 safe_state_description: str):
        self.device_id = device_id
        self.operations = list(operations)
        self.base_url = base_url.rstrip("/")
        # These three are not defaults you can skip. The controller refuses a
        # real driver that will not say what its apparatus does when a step is
        # abandoned, because that answer decides whether it is safe for someone
        # to walk up to the bench.
        self.safe_state_policy = safe_state_policy
        self.safe_state_retains_hazard = safe_state_retains_hazard
        self.safe_state_description = safe_state_description
        self._quarantined = False
        # command_id -> job_id, so a resubmitted command never starts a second
        # physical action. Real adapters should persist this: an in-memory map
        # is lost on restart, and a restart is exactly when you most need it.
        self._submitted: dict[str, str] = {}

    # -- transport ------------------------------------------------------

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        payload = None if body is None else json.dumps(body).encode()
        req = request.Request(f"{self.base_url}{path}", data=payload, method=method,
                              headers={"Content-Type": "application/json"})
        try:
            with request.urlopen(req, timeout=HTTP_TIMEOUT) as response:
                raw = response.read(1_000_000)
        except error.HTTPError as exc:
            # A 4xx/5xx is an answer from the instrument: it is reachable and
            # refused. That is a DeviceError, not an unknown state.
            raise DeviceError(f"{self.device_id} returned HTTP {exc.code}.") from None
        except (error.URLError, TimeoutError, OSError) as exc:
            # No answer at all. The job may be running, finished, or never
            # started; the controller must not repeat physical work on this.
            raise DeviceUnavailable(
                f"{self.device_id} could not be reached ({exc}); job outcome unknown.") from None
        try:
            return json.loads(raw) if raw else {}
        except ValueError:
            raise DeviceError(f"{self.device_id} returned a non-JSON response.") from None

    async def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        # urllib blocks, so keep it off the event loop. A driver built on an
        # async client can call it directly.
        return await asyncio.to_thread(self._request, method, path, body)

    # -- contract -------------------------------------------------------

    def describe(self) -> dict:
        return {
            "device_id": self.device_id,
            "operations": list(self.operations),
            # False is the whole point of a real adapter, and the controller
            # checks it. Never report False from a driver that is faking.
            "simulated": False,
            "interface": "example-http-v1",
            "state": "quarantined" if self._quarantined else "available",
            "endpoint": self.base_url,
            "safe_state": {"policy": self.safe_state_policy,
                           "retains_hazard": self.safe_state_retains_hazard,
                           "description": self.safe_state_description},
        }

    async def write(self, command: Command) -> str:
        if self._quarantined:
            raise DeviceError(f"{self.device_id} is quarantined.")
        known = self._submitted.get(command.command_id)
        if known is not None:
            # Idempotency. The controller retries a command_id after a timeout;
            # starting a second aspirate here would be a second physical action.
            return known
        body = {"command_id": command.command_id, "operation": command.operation,
                "payload": command.payload, "attempt": command.attempt}
        response = await self._call("POST", "/jobs", body)
        job_id = response.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            raise DeviceError(f"{self.device_id} did not return a job id.")
        self._submitted[command.command_id] = job_id
        return job_id

    async def read(self, job_id: str | None = None) -> dict:
        """Ask the instrument. Never answer from a local cache.

        The controller calls this precisely when it has lost track of a job, so
        a cached answer is worse than no answer.
        """
        if job_id is None:
            status = await self._call("GET", "/status")
            return {**self.describe(), "busy": bool(status.get("busy")),
                    "state": status.get("state", "available")}
        response = await self._call("GET", f"/jobs/{job_id}")
        state = response.get("state")
        if state not in ("running", "succeeded", "failed", "cancelled"):
            raise DeviceError(f"{self.device_id} reported unknown job state {state!r}.")
        return {"device_id": self.device_id, "job_id": job_id, "state": state,
                "result": response.get("result")}

    async def wait(self, job_id: str) -> dict:
        """Poll until the job leaves `running`.

        No deadline here. The controller imposes its own and then reconciles;
        a driver that gives up and cancels turns "not known yet" into a real
        abort, which is a physical action nobody asked for.
        """
        while True:
            snapshot = await self.read(job_id)
            if snapshot["state"] == "succeeded":
                return snapshot["result"]
            if snapshot["state"] != "running":
                raise DeviceError(
                    f"{self.device_id} job {job_id} ended as {snapshot['state']}.")
            await asyncio.sleep(POLL_INTERVAL)

    async def cancel(self, job_id: str) -> bool:
        """Return True only if the instrument confirmed the job stopped.

        An optimistic True lets the controller start attempt two while the
        first one is still moving.
        """
        response = await self._call("POST", f"/jobs/{job_id}/cancel")
        return response.get("cancelled") is True

    async def enter_safe_state(self, reason: str) -> dict:
        """Run the instrument's make-safe procedure and report what happened.

        Returning `entered: False`, or raising, is a legitimate answer and a
        far better one than claiming success: the run report then tells the
        operator the physical state is unknown instead of implying the bench
        is clear.
        """
        try:
            response = await self._call("POST", "/safe-state", {"reason": reason})
        except DeviceUnavailable as exc:
            raise SafeStateError(
                f"{self.device_id} is unreachable; its physical state is unknown: {exc}"
            ) from None
        entered = response.get("entered")
        if not isinstance(entered, bool):
            raise SafeStateError(
                f"{self.device_id} did not confirm whether it reached a safe state.")
        return {"entered": entered, "policy": self.safe_state_policy,
                "retains_hazard": self.safe_state_retains_hazard,
                "detail": response.get("detail") or self.safe_state_description}

    def quarantine(self) -> None:
        self._quarantined = True

    async def close(self) -> None:
        """Release local resources only. This is not a safe-state request."""
        self._submitted.clear()


# ---------------------------------------------------------------------------
# A stand-in instrument, so the adapter above can be run and read end to end.
# It is a mock HTTP server. It moves nothing and proves nothing about hardware.
# ---------------------------------------------------------------------------

def _serve_stub(port: int = 0):
    """Start a stand-in instrument server; returns (server, thread, base_url)."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    jobs: dict[str, dict] = {}
    commands: dict[str, str] = {}
    state = {"safe": False, "hang_next": False}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, payload, code=200):
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self):
            length = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(length) or b"{}")

        def do_GET(self):
            if self.path == "/status":
                return self._send({"state": "available", "busy": any(
                    job["state"] == "running" for job in jobs.values())})
            if self.path.startswith("/jobs/"):
                job = jobs.get(self.path.split("/")[2])
                return self._send(job or {"state": "failed"}, 200 if job else 404)
            self._send({"error": "not found"}, 404)

        def do_POST(self):
            if self.path == "/jobs":
                body = self._body()
                existing = commands.get(body["command_id"])
                if existing:
                    return self._send({"job_id": existing})
                job_id = f"job-{len(jobs) + 1}"
                jobs[job_id] = {
                    "state": "running" if state["hang_next"] else "succeeded",
                    "result": {"operation": body["operation"],
                               "sample_id": body["payload"].get("sample_id"),
                               "physical_execution": True}}
                state["hang_next"] = False
                commands[body["command_id"]] = job_id
                return self._send({"job_id": job_id})
            if self.path.endswith("/cancel"):
                job = jobs.get(self.path.split("/")[2])
                if job and job["state"] == "running":
                    job["state"] = "cancelled"
                    return self._send({"cancelled": True})
                return self._send({"cancelled": False})
            if self.path == "/safe-state":
                state["safe"] = True
                return self._send({"entered": True,
                                   "detail": "Stand-in: axes parked, tip ejected to waste."})
            if self.path == "/hang-next":
                state["hang_next"] = True
                return self._send({"ok": True})
            self._send({"error": "not found"}, 404)

    server = HTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{server.server_port}"


async def _demo() -> None:
    server, _, base_url = _serve_stub()
    device = HttpInstrument(
        "liquid-handler-1", ["prepare"], base_url,
        safe_state_policy="park_and_release",
        safe_state_retains_hazard=False,
        safe_state_description="Parks axes clear of the deck and ejects the tip to waste.")
    try:
        print("manifest:", json.dumps(device.describe(), indent=2))

        payload = {"sample_id": "demo-001", "candidate_ids": ["NC_000866.4"]}
        job = await device.write(Command("demo:prepare", "prepare", payload))
        print("submitted:", job)
        print("resubmitting the same command_id returns the same job:",
              await device.write(Command("demo:prepare", "prepare", payload)) == job)
        print("result:", await device.wait(job))

        # Now the interesting path: a job that does not finish.
        request.urlopen(request.Request(f"{base_url}/hang-next", data=b"{}", method="POST")).read()
        stuck = await device.write(Command("demo:prepare-2", "prepare", payload))
        try:
            await asyncio.wait_for(device.wait(stuck), timeout=0.5)
        except TimeoutError:
            print("\ncontroller deadline hit; the job was NOT cancelled by wait()")
        print("authoritative state after timeout:", (await device.read(stuck))["state"])
        print("cancel acknowledged:", await device.cancel(stuck))
        print("safe state:", json.dumps(await device.enter_safe_state("demo stop"), indent=2))
    finally:
        await device.close()
        server.shutdown()


if __name__ == "__main__":
    asyncio.run(_demo())

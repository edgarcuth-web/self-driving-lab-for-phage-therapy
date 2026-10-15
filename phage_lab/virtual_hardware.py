"""Software device twins used when no physical instrument is connected.

A twin carries real candidate IDs through the orchestration stack so the
scheduler, reconciliation and reporting paths can be exercised before any
hardware exists. Everything it returns is labelled ``simulated`` and carries
``evidence: "none"``; it is never experimental evidence.

Fault behaviour is opt-in through the ``injector`` seam so that the recovery
invariants in :class:`phage_lab.workflow.Scheduler` stay testable. Production
callers leave it unset and get a no-fault twin.
"""

import asyncio
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
import random
from typing import Callable, Iterable, Protocol

from .devices import Command, DeviceError, DeviceUnavailable

VIRTUAL_INTERFACE = "phage-lab-virtual-twin-v1"


class FaultSource(Protocol):
    """Test seam: returns a fault name for an operation, or ``"none"``."""

    def take(self, operation: str) -> str: ...


@dataclass
class Job:
    job_id: str
    command: Command
    fingerprint: str
    fault: str
    state: str = "running"
    result: dict | None = None
    task: asyncio.Task | None = None


class VirtualDevice:
    """Software-only device twin. No physical action ever occurs."""

    def __init__(self, device_id: str, operation: str, emit: Callable[..., None],
                 *, injector: FaultSource | None = None, seed: int = 0,
                 time_scale: float = 1.0):
        self.device_id = device_id
        self.operation = operation
        self.emit = emit
        self.injector = injector
        self.seed = seed
        self.time_scale = time_scale
        self.jobs: dict[str, Job] = {}
        self._commands: dict[str, Job] = {}
        self.quarantined = False
        self.effect_count = 0

    def describe(self) -> dict:
        return {"device_id": self.device_id, "operations": [self.operation],
                "simulated": True, "interface": VIRTUAL_INTERFACE,
                "state": "quarantined" if self.quarantined else "available",
                "limits": {"concurrent_jobs": 1},
                "notes": "Software-only device twin. No physical action occurs."}

    def quarantine(self) -> None:
        self.quarantined = True

    def _reachable(self) -> None:
        if any(job.fault == "unreachable" for job in self.jobs.values()):
            raise DeviceUnavailable(f"Device {self.device_id} is unreachable; job outcome unknown.")

    async def read(self, job_id: str | None = None) -> dict:
        self._reachable()
        if job_id is None:
            return {**self.describe(), "busy": any(j.state == "running" for j in self.jobs.values())}
        job = self.jobs[job_id]
        return {"device_id": self.device_id, "job_id": job_id,
                "state": job.state, "result": deepcopy(job.result)}

    async def write(self, command: Command) -> str:
        self._reachable()
        if command.operation != self.operation:
            raise DeviceError("Device lacks the requested operation.")
        if (not command.command_id or type(command.attempt) is not int or command.attempt < 1
                or set(command.payload) != {"sample_id", "candidate_ids"}
                or not isinstance(command.payload["sample_id"], str)
                or not command.payload["sample_id"]
                or not isinstance(command.payload["candidate_ids"], list)
                or not command.payload["candidate_ids"]
                or any(not isinstance(item, str) or not item
                       for item in command.payload["candidate_ids"])):
            raise DeviceError("Command is outside the virtual device contract.")
        fingerprint = sha256(json.dumps(
            [command.operation, command.payload], sort_keys=True).encode()).hexdigest()
        previous = self._commands.get(command.command_id)
        if previous:
            if previous.fingerprint != fingerprint:
                raise DeviceError("Conflicting payload for an existing command ID.")
            if previous.state != "cancelled" or command.attempt <= previous.command.attempt:
                return previous.job_id
        if self.quarantined:
            raise DeviceError("Device is quarantined.")
        if any(job.state == "running" for job in self.jobs.values()):
            raise DeviceError("Device is busy.")
        fault = self.injector.take(command.operation) if self.injector else "none"
        job_id = f"{self.device_id}:{command.command_id}:{command.attempt}"
        job = Job(job_id, deepcopy(command), fingerprint, fault)
        self.jobs[job_id] = job
        self._commands[command.command_id] = job
        self.emit("job_submitted", device=self.device_id, step=command.operation,
                  job_id=job_id, command_id=command.command_id, attempt=command.attempt)
        if fault != "none":
            self.emit("fault_injected", device=self.device_id, step=command.operation, fault=fault)
        job.task = asyncio.create_task(self._execute(job))
        return job_id

    async def _execute(self, job: Job) -> None:
        delay = random.Random(
            f"delay:{self.seed}:{job.fingerprint}:{job.command.attempt}").uniform(0.2, 0.5)
        await asyncio.sleep(delay * self.time_scale)
        if job.fault in {"hang", "unreachable"}:
            await asyncio.Event().wait()
        result = {"simulated": True, "physical_execution": False, "evidence": "none",
                  "sample_id": job.command.payload["sample_id"],
                  "operation": self.operation}
        if self.operation == "synthesize":
            result["virtual_order_id"] = "VIRTUAL-ORDER-" + job.fingerprint[:10]
        if self.operation == "measure":
            key = json.dumps(sorted(job.command.payload["candidate_ids"]))
            rng = random.Random(f"virtual-readout:{self.seed}:{key}")
            result["readings"] = [round(rng.uniform(0.05, 0.95), 4) for _ in range(3)]
            result["unit"] = "arbitrary_virtual_units"
        self.effect_count += 1
        job.result = result
        job.state = "succeeded"
        self.emit("device_job_completed", device=self.device_id,
                  step=self.operation, job_id=job.job_id)

    async def wait(self, job_id: str) -> dict:
        job = self.jobs[job_id]
        await asyncio.shield(job.task)
        if job.fault == "response-lost":
            await asyncio.Event().wait()
        snapshot = await self.read(job_id)
        if snapshot["state"] != "succeeded":
            raise DeviceError("Job did not succeed.")
        return snapshot["result"]

    async def cancel(self, job_id: str) -> bool:
        self._reachable()
        job = self.jobs[job_id]
        if job.state == "succeeded":
            return False
        if job.state == "cancelled":
            return True
        job.task.cancel()
        try:
            await job.task
        except asyncio.CancelledError:
            pass
        job.state = "cancelled"
        self.emit("cancellation_acknowledged", device=self.device_id, job_id=job_id)
        return True

    async def close(self) -> None:
        pending = [job.task for job in self.jobs.values() if job.task and not job.task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


def make_virtual_devices(operations: Iterable[str], emit: Callable[..., None], *,
                         replicas: int = 1, seed: int = 0, time_scale: float = 0.05,
                         injector: FaultSource | None = None) -> dict[str, VirtualDevice]:
    """Create no-fault device twins for each requested operation.

    ``replicas`` above 1 produces ``-1``/``-2`` suffixed peers so failover has a
    compatible alternative to move to.
    """
    if replicas < 1:
        raise ValueError("replicas must be at least 1.")
    devices: dict[str, VirtualDevice] = {}
    for operation in operations:
        for index in range(1, replicas + 1):
            device_id = f"virtual-{operation}" if replicas == 1 else f"virtual-{operation}-{index}"
            devices[device_id] = VirtualDevice(device_id, operation, emit, injector=injector,
                                               seed=seed, time_scale=time_scale)
    return devices

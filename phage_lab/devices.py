"""A local MHS-inspired contract and asynchronous, entirely virtual devices."""

import asyncio
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
import random
from typing import Callable, Protocol

OPERATIONS = ("synthesize", "prepare", "transfer", "infect", "measure")
FAULT_MODES = ("none", "hang", "response-lost", "unreachable", "random")


class DeviceError(RuntimeError):
    pass


class DeviceUnavailable(DeviceError):
    pass


@dataclass(frozen=True)
class Command:
    command_id: str
    operation: str
    payload: dict
    attempt: int = 1


class DeviceDriver(Protocol):
    """Local contract; method names are not an official MHS wire protocol."""

    def describe(self) -> dict: ...
    async def read(self, job_id: str | None = None) -> dict: ...
    async def write(self, command: Command) -> str: ...
    async def wait(self, job_id: str) -> dict: ...
    async def cancel(self, job_id: str) -> bool: ...


class FaultInjector:
    """Inject at most one fault, on the first submission to a seeded task."""

    def __init__(self, seed: int, mode: str, step: str | None = None):
        if mode not in FAULT_MODES or (step is not None and step not in OPERATIONS):
            raise ValueError("Unknown fault mode or step.")
        rng = random.Random(f"fault:{seed}")
        self.step = step or rng.choice(OPERATIONS)
        self.mode = rng.choice(FAULT_MODES[1:4]) if mode == "random" else mode
        self.injected = False

    def take(self, operation: str) -> str:
        if operation == self.step and self.mode != "none" and not self.injected:
            self.injected = True
            return self.mode
        return "none"


@dataclass
class Job:
    job_id: str
    command: Command
    fingerprint: str
    fault: str
    state: str = "running"
    result: dict | None = None
    task: asyncio.Task | None = None


class SimulatedDevice:
    def __init__(self, device_id: str, operation: str, injector: FaultInjector,
                 emit: Callable[..., None], seed: int, time_scale: float = 1.0):
        self.device_id = device_id
        self.operation = operation
        self.injector = injector
        self.emit = emit
        self.seed = seed
        self.time_scale = time_scale
        self.jobs: dict[str, Job] = {}
        self._commands: dict[str, Job] = {}
        self.quarantined = False
        self.effect_count = 0

    def describe(self) -> dict:
        return {"device_id": self.device_id, "operations": [self.operation],
                "simulated": True, "interface": "mhs-inspired-local-v0",
                "state": "quarantined" if self.quarantined else "available",
                "limits": {"concurrent_jobs": 1},
                "notes": "Virtual jobs only. Cancellation is acknowledged before reuse."}

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
                or not 2 <= len(command.payload["candidate_ids"]) <= 3
                or any(not isinstance(item, str) or not item.startswith("SIM-PHAGE-")
                       for item in command.payload["candidate_ids"])):
            raise DeviceError("Command is outside the simulated device contract.")
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
        fault = self.injector.take(command.operation)
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
        delay = random.Random(f"delay:{self.seed}:{job.fingerprint}:{job.command.attempt}").uniform(0.2, 0.5)
        await asyncio.sleep(delay * self.time_scale)
        if job.fault in {"hang", "unreachable"}:
            await asyncio.Event().wait()
        result = {"simulated": True, "sample_id": job.command.payload["sample_id"],
                  "operation": self.operation}
        if self.operation == "synthesize":
            result["virtual_order_id"] = "SIM-ORDER-" + job.fingerprint[:10]
        if self.operation == "measure":
            # Independent from candidate ranking; no efficacy model or calibration.
            # Exclude run ID, device and retry count so failover doesn't change data.
            key = json.dumps(sorted(job.command.payload["candidate_ids"]))
            rng = random.Random(f"synthetic-readout:{self.seed}:{key}")
            result["readings"] = [round(rng.uniform(0.05, 0.95), 4) for _ in range(3)]
            result["unit"] = "arbitrary_simulation_units"
        self.effect_count += 1
        job.result = result
        job.state = "succeeded"
        self.emit("device_job_completed", device=self.device_id, step=self.operation, job_id=job.job_id)

    async def wait(self, job_id: str) -> dict:
        job = self.jobs[job_id]
        # Controller timeout must not cancel the simulated physical operation.
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
        """Local process cleanup only; not an acknowledgment from unreachable hardware."""
        pending = [job.task for job in self.jobs.values() if job.task and not job.task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


def make_devices(injector: FaultInjector, emit: Callable[..., None], seed: int,
                 time_scale: float = 1.0) -> dict[str, SimulatedDevice]:
    return {f"{operation}-{suffix}": SimulatedDevice(
        f"{operation}-{suffix}", operation, injector, emit, seed, time_scale)
        for operation in OPERATIONS for suffix in ("primary", "backup")}

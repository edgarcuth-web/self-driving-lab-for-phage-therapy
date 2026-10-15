"""Explicit simulation harness retained for tests and the legacy demo UI only."""

import asyncio
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
import random
from typing import Callable

from .agents import OpenRouterAgent, RuleAgent
from .biology import GenomeSummary, read_fasta
from .devices import Command, DeviceError, DeviceUnavailable
from .provenance import source_identity
from .records import RunRecords, evaluate, utc_now
from .workflow import Scheduler, validate_plan

OPERATIONS = ("synthesize", "prepare", "transfer", "infect", "measure")
FAULT_MODES = ("none", "hang", "response-lost", "unreachable", "random")
DEPENDENCIES = {
    "synthesize": (), "prepare": ("synthesize",), "transfer": ("prepare",),
    "infect": ("transfer",), "measure": ("infect",),
}
SIMULATION_INTERFACE = "mhs-inspired-local-v0"


def mock_candidates(genome: GenomeSummary) -> list[dict]:
    """Deterministic fixtures for controller tests; no biological meaning."""
    rng = random.Random("mock-candidates:" + genome.sha256)
    candidates = [
        {"id": f"SIM-PHAGE-{letter}", "simulation_score": round(rng.uniform(0.1, 0.9), 3),
         "source": "synthetic_fixture", "validated": False, "simulated": True}
        for letter in "ABCDEF"
    ]
    return sorted(candidates, key=lambda candidate: (-candidate["simulation_score"], candidate["id"]))


class FaultInjector:
    """Inject at most one synthetic fault into the explicit simulation backend."""

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
                "simulated": True, "interface": SIMULATION_INTERFACE,
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


def make_devices(injector: FaultInjector, emit: Callable[..., None], seed: int,
                 time_scale: float = 1.0) -> dict[str, SimulatedDevice]:
    return {f"{operation}-{suffix}": SimulatedDevice(
        f"{operation}-{suffix}", operation, injector, emit, seed, time_scale)
        for operation in OPERATIONS for suffix in ("primary", "backup")}


async def run_demo(genome_path: Path, output_root: Path, *, seed: int = 42,
                   fault: str = "hang", fault_step: str | None = None,
                   agent_mode: str = "rule", agent=None, time_scale: float = 1.0,
                   echo: bool = True, on_event=None) -> tuple[dict, Path]:
    """Legacy simulation harness. Never used by the real execution entry point."""
    if not math.isfinite(time_scale) or not 0.01 <= time_scale <= 10:
        raise ValueError("time_scale must be between 0.01 and 10.")
    injector = FaultInjector(seed, fault, fault_step)
    records = RunRecords(output_root, echo, on_event=on_event)
    report = {"schema_version": 1, "started_at": utc_now(), "status": "running",
              "simulated": True, "interface": SIMULATION_INTERFACE,
              "agent": agent.name if agent else agent_mode, "seed": seed,
              "fault": {"requested": fault, "selected": injector.mode, "step": injector.step,
                        "injected_count": 0},
              "results": {}, "recoveries": [], "error": None,
              "limitations": ["Synthetic candidates and readings; no biological efficacy assessed.",
                              "No physical instruments or real synthesis orders.",
                              "No restart/resume or multi-sample concurrency."]}
    devices = make_devices(injector, records.emit, seed, time_scale)
    try:
        records.emit("run_started", agent=report["agent"], seed=seed, simulated=True)
        report["source"] = source_identity()
        records.emit("source_identified", **report["source"])
        if agent is None:
            if agent_mode == "rule":
                agent = RuleAgent()
            elif agent_mode == "openrouter":
                agent = OpenRouterAgent.from_environment()
            else:
                raise ValueError("Unknown agent mode.")
        report["model"] = getattr(agent, "model", None)
        genome = read_fasta(genome_path)
        report["genome"] = genome.public_metadata()
        records.emit("input_validated", **report["genome"])
        report["candidates"] = mock_candidates(genome)
        manifests = [device.describe() for device in devices.values()]
        records.emit("devices_discovered", count=len(manifests))
        records.emit("planning_requested", agent=agent.name)
        plan = await agent.plan({"genome": genome.public_metadata(),
                                "candidates": report["candidates"], "devices": manifests,
                                "workflow": DEPENDENCIES, "simulated": True})
        validate_plan(plan, report["candidates"], devices, operations=OPERATIONS)
        report["plan"] = plan
        records.emit("plan_accepted", agent=agent.name, **plan)
        scheduler = Scheduler(devices, agent, records, report, time_scale)
        payload = {"sample_id": "SIM-SAMPLE-" + genome.sha256[:12],
                   "candidate_ids": sorted(plan["candidate_ids"])}
        for operation in OPERATIONS:
            result = await scheduler.execute(operation, plan["device_assignments"][operation], payload)
            report["results"][operation] = result
            records.emit("step_completed", step=operation, result=result)
        report["status"] = "succeeded"
    except asyncio.CancelledError:
        report["status"] = "cancelled"
        report["error"] = "Run cancelled by the operator; partial results retained."
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        for device in devices.values():
            await device.close()
        report["fault"]["injected_count"] = int(injector.injected)
        report["effects_by_device"] = {key: device.effect_count for key, device in devices.items()}
        report["evaluation"] = evaluate(report["results"])
        records.emit("run_finished", status=report["status"], error=report["error"])
        try:
            records.finish(report)
        finally:
            records.close()
    return report, records.directory

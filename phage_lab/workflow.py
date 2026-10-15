"""A dependency-aware, single-sample scheduler with bounded reconciliation."""

import asyncio
import math
from pathlib import Path

from .agents import AnthropicAgent, RuleAgent
from .biology import mock_candidates, read_fasta
from .devices import INTERFACE, Command, DeviceUnavailable, FaultInjector, OPERATIONS, make_devices
from .records import RunRecords, evaluate, utc_now
from .provenance import source_identity

DEPENDENCIES = {
    "synthesize": (), "prepare": ("synthesize",), "transfer": ("prepare",),
    "infect": ("transfer",), "measure": ("infect",)}


class WorkflowError(RuntimeError):
    pass


def _validate_reason(value: dict) -> None:
    if not isinstance(value.get("reason"), str) or not 1 <= len(value["reason"].strip()) <= 500:
        raise WorkflowError("Decision requires a short, nonempty reason.")


def validate_plan(plan: dict, candidates: list[dict], devices: dict) -> None:
    if not isinstance(plan, dict) or set(plan) != {"candidate_ids", "device_assignments", "reason"}:
        raise WorkflowError("Invalid plan fields.")
    _validate_reason(plan)
    ids = plan["candidate_ids"]
    allowed = {item["id"] for item in candidates}
    if (not isinstance(ids, list) or not 2 <= len(ids) <= 3
            or any(not isinstance(item, str) or item not in allowed for item in ids)
            or len(set(ids)) != len(ids)):
        raise WorkflowError("Plan must select two or three distinct offered candidate IDs.")
    assignments = plan["device_assignments"]
    if not isinstance(assignments, dict) or set(assignments) != set(OPERATIONS):
        raise WorkflowError("Plan must assign exactly all five workflow operations.")
    for operation, device_id in assignments.items():
        if (not isinstance(device_id, str) or device_id not in devices
                or operation not in devices[device_id].describe()["operations"]):
            raise WorkflowError("Plan assigned an unknown or incompatible device.")


def validate_recovery(decision: dict, alternatives: list[str]) -> None:
    if not isinstance(decision, dict) or set(decision) != {"action", "replacement_device_id", "reason"}:
        raise WorkflowError("Invalid recovery fields.")
    _validate_reason(decision)
    action, replacement = decision["action"], decision["replacement_device_id"]
    if action not in ("cancel_and_retry", "cancel_and_failover", "abort"):
        raise WorkflowError("Unknown recovery action.")
    if action == "cancel_and_failover":
        if not isinstance(replacement, str) or replacement not in alternatives:
            raise WorkflowError("Failover must target an available compatible device.")
    elif replacement is not None:
        raise WorkflowError("Only failover can specify a replacement device.")


class Scheduler:
    def __init__(self, devices: dict, agent, records: RunRecords, report: dict,
                 time_scale: float):
        self.devices = devices
        self.agent = agent
        self.records = records
        self.report = report
        self.timeout = max(0.05, 1.2 * time_scale)

    async def execute(self, operation: str, device_id: str, payload: dict) -> dict:
        command_id = f"{self.records.run_id}:{operation}"
        for attempt in (1, 2):
            device = self.devices[device_id]
            job_id = await device.write(Command(command_id, operation, payload, attempt))
            try:
                return await asyncio.wait_for(device.wait(job_id), self.timeout)
            except TimeoutError:
                self.records.emit("job_timeout", step=operation, device=device_id, job_id=job_id)
            try:
                observed = await device.read(job_id)
            except DeviceUnavailable:
                device.quarantined = True
                self.report["recoveries"].append({"step": operation, "outcome": "unknown_state_stop"})
                self.records.emit("reconciliation_failed", step=operation, device=device_id,
                                  reason="No authoritative job state; duplicate work refused.")
                raise WorkflowError("Unreachable device: cannot confirm completion or cancellation; stopped.") from None
            self.records.emit("job_reconciled", step=operation, device=device_id, state=observed["state"])
            if observed["state"] == "succeeded":
                self.report["recoveries"].append({"step": operation, "outcome": "completed_result_reused"})
                return observed["result"]
            if observed["state"] != "running" or attempt == 2:
                raise WorkflowError("Job could not complete within the two-attempt limit.")
            alternatives = []
            for other_id, other in self.devices.items():
                if other_id == device_id or operation not in other.describe()["operations"]:
                    continue
                try:
                    state = await other.read()
                except DeviceUnavailable:
                    continue
                if not state["busy"] and state["state"] == "available":
                    alternatives.append(other_id)
            context = {"step": operation, "current_device": device_id,
                       "observed_state": observed["state"], "alternatives": sorted(alternatives),
                       "attempts_remaining": 1, "cancellation_required": True}
            self.records.emit("recovery_requested", **context)
            decision = await self.agent.recover(context)
            validate_recovery(decision, alternatives)
            self.records.emit("recovery_decided", agent=self.agent.name, step=operation, **decision)
            if decision["action"] == "abort":
                raise WorkflowError("Agent chose to stop the run.")
            if not await device.cancel(job_id):
                # The job may have finished while the agent was deciding.
                observed = await device.read(job_id)
                if observed["state"] == "succeeded":
                    self.report["recoveries"].append({"step": operation, "outcome": "completed_during_recovery"})
                    return observed["result"]
                raise WorkflowError("Cancellation was not acknowledged; retry refused.")
            self.report["recoveries"].append({"step": operation, "outcome": decision["action"],
                                              "from_device": device_id, **decision})
            if decision["action"] == "cancel_and_failover":
                device.quarantined = True
                device_id = decision["replacement_device_id"]
            self.records.emit("recovery_executing", step=operation, device=device_id,
                              action=decision["action"], next_attempt=attempt + 1)
        raise WorkflowError("Attempt limit reached.")


async def run_demo(genome_path: Path, output_root: Path, *, seed: int = 42,
                   fault: str = "hang", fault_step: str | None = None,
                   agent_mode: str = "rule", agent=None, time_scale: float = 1.0,
                   echo: bool = True, on_event=None) -> tuple[dict, Path]:
    if not math.isfinite(time_scale) or not 0.01 <= time_scale <= 10:
        raise ValueError("time_scale must be between 0.01 and 10.")
    injector = FaultInjector(seed, fault, fault_step)
    records = RunRecords(output_root, echo, on_event=on_event)
    report = {"schema_version": 1, "started_at": utc_now(), "status": "running",
              "simulated": True, "interface": INTERFACE,
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
            elif agent_mode == "anthropic":
                agent = AnthropicAgent.from_environment()
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
        validate_plan(plan, report["candidates"], devices)
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
        # Only clean up local simulator tasks. Unknown physical state is not 'resolved'.
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

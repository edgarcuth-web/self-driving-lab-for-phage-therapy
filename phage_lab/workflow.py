"""Validated orchestration for real devices, plus bounded reconciliation logic."""

import asyncio
import math
from pathlib import Path

from .biology import read_fasta
from .devices import Command, DeviceUnavailable
from .records import RunRecords, evaluate, utc_now
from .provenance import source_identity


class WorkflowError(RuntimeError):
    pass


def _validate_reason(value: dict) -> None:
    if not isinstance(value.get("reason"), str) or not 1 <= len(value["reason"].strip()) <= 500:
        raise WorkflowError("Decision requires a short, nonempty reason.")


def _infer_operations(devices: dict) -> tuple[str, ...]:
    operations = []
    for device in devices.values():
        for operation in device.describe().get("operations", []):
            if operation not in operations:
                operations.append(operation)
    return tuple(operations)


def validate_plan(plan: dict, candidates: list[dict], devices: dict,
                  operations: tuple[str, ...] | list[str] | None = None) -> None:
    if not isinstance(plan, dict) or set(plan) != {"candidate_ids", "device_assignments", "reason"}:
        raise WorkflowError("Invalid plan fields.")
    _validate_reason(plan)
    ids = plan["candidate_ids"]
    allowed = {item["id"] for item in candidates if isinstance(item, dict) and isinstance(item.get("id"), str)}
    if (not isinstance(ids, list) or not 2 <= len(ids) <= 3
            or any(not isinstance(item, str) or item not in allowed for item in ids)
            or len(set(ids)) != len(ids)):
        raise WorkflowError("Plan must select two or three distinct offered candidate IDs.")
    operations = tuple(operations or _infer_operations(devices))
    assignments = plan["device_assignments"]
    if not isinstance(assignments, dict) or set(assignments) != set(operations):
        raise WorkflowError("Plan must assign exactly every workflow operation.")
    for operation, device_id in assignments.items():
        if (not isinstance(device_id, str) or device_id not in devices
                or operation not in devices[device_id].describe().get("operations", [])):
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


def validate_real_inputs(candidates: list[dict], devices: dict) -> None:
    """Refuse all known simulated fixtures on the production execution path."""
    if not candidates:
        raise WorkflowError("A real run requires externally supplied candidate records.")
    for candidate in candidates:
        if not isinstance(candidate, dict) or not isinstance(candidate.get("id"), str) or not candidate["id"].strip():
            raise WorkflowError("Each candidate requires a nonempty string ID.")
        if (candidate.get("simulated") is True
                or candidate.get("source") == "synthetic_fixture"
                or candidate["id"].startswith("SIM-")):
            raise WorkflowError("Real runs reject simulated candidate fixtures.")
    if not devices:
        raise WorkflowError("A real run requires configured device drivers.")
    for device_id, device in devices.items():
        manifest = device.describe()
        if manifest.get("simulated") is not False:
            raise WorkflowError(
                f"Real run refused device {device_id!r}: driver must explicitly declare simulated=False.")
        if not isinstance(manifest.get("device_id"), str) or manifest["device_id"] != device_id:
            raise WorkflowError("Real device manifest must match its configured device ID.")


def _validate_workflow(workflow: dict) -> tuple[str, ...]:
    if not isinstance(workflow, dict) or not workflow:
        raise WorkflowError("Workflow must contain at least one operation.")
    operations = tuple(workflow)
    for operation, dependencies in workflow.items():
        if not isinstance(operation, str) or not operation:
            raise WorkflowError("Workflow operation names must be nonempty strings.")
        if not isinstance(dependencies, (tuple, list)):
            raise WorkflowError("Workflow dependencies must be a list or tuple.")
        if any(dep not in workflow for dep in dependencies):
            raise WorkflowError("Workflow dependency references an unknown operation.")
        if any(operations.index(dep) >= operations.index(operation) for dep in dependencies):
            raise WorkflowError("Workflow dependencies must appear before dependent operations.")
    return operations


class Scheduler:
    def __init__(self, devices: dict, agent, records: RunRecords, report: dict,
                 time_scale: float | None = None, *, timeout_seconds: float | None = None):
        self.devices = devices
        self.agent = agent
        self.records = records
        self.report = report
        if timeout_seconds is None:
            if time_scale is None or not math.isfinite(time_scale) or time_scale <= 0:
                raise ValueError("A positive time scale or timeout must be provided.")
            timeout_seconds = max(0.05, 1.2 * time_scale)
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive and finite.")
        self.timeout = timeout_seconds

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
                if hasattr(device, "quarantined"):
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
                if other_id == device_id or operation not in other.describe().get("operations", []):
                    continue
                try:
                    state = await other.read()
                except DeviceUnavailable:
                    continue
                if not state.get("busy") and state.get("state") == "available":
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
                observed = await device.read(job_id)
                if observed["state"] == "succeeded":
                    self.report["recoveries"].append({"step": operation, "outcome": "completed_during_recovery"})
                    return observed["result"]
                raise WorkflowError("Cancellation was not acknowledged; retry refused.")
            self.report["recoveries"].append({"step": operation, "outcome": decision["action"],
                                              "from_device": device_id, **decision})
            if decision["action"] == "cancel_and_failover":
                if hasattr(device, "quarantined"):
                    device.quarantined = True
                device_id = decision["replacement_device_id"]
            self.records.emit("recovery_executing", step=operation, device=device_id,
                              action=decision["action"], next_attempt=attempt + 1)
        raise WorkflowError("Attempt limit reached.")


async def run_experiment(genome_path: Path, output_root: Path, *, sample_id: str,
                         candidates: list[dict], devices: dict, workflow: dict, agent,
                         timeout_seconds: float = 60.0, echo: bool = True,
                         on_event=None) -> tuple[dict, Path]:
    """Run an explicitly configured real experiment.

    Nothing is synthesized by this function: candidate records and device drivers
    must be supplied by the caller. Any simulated candidate or device is rejected.
    """
    if not isinstance(sample_id, str) or not sample_id.strip():
        raise ValueError("sample_id must be a nonempty string.")
    operations = _validate_workflow(workflow)
    validate_real_inputs(candidates, devices)
    records = RunRecords(output_root, echo, on_event=on_event)
    report = {"schema_version": 2, "started_at": utc_now(), "status": "running",
              "simulated": False, "agent": getattr(agent, "name", type(agent).__name__),
              "sample_id": sample_id, "results": {}, "recoveries": [], "error": None,
              "limitations": ["Biological efficacy is not inferred by the orchestration layer."]}
    try:
        records.emit("run_started", agent=report["agent"], simulated=False, sample_id=sample_id)
        report["source"] = source_identity()
        records.emit("source_identified", **report["source"])
        genome = read_fasta(genome_path)
        report["genome"] = genome.public_metadata()
        records.emit("input_validated", **report["genome"])
        report["candidates"] = candidates
        manifests = [device.describe() for device in devices.values()]
        records.emit("devices_discovered", count=len(manifests), simulated=False)
        records.emit("planning_requested", agent=report["agent"])
        plan = await agent.plan({"genome": genome.public_metadata(), "candidates": candidates,
                                "devices": manifests, "workflow": workflow, "simulated": False})
        validate_plan(plan, candidates, devices, operations=operations)
        report["plan"] = plan
        records.emit("plan_accepted", agent=report["agent"], **plan)
        scheduler = Scheduler(devices, agent, records, report, timeout_seconds=timeout_seconds)
        payload = {"sample_id": sample_id, "candidate_ids": list(plan["candidate_ids"])}
        for operation in operations:
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
            close = getattr(device, "close", None)
            if close is not None:
                await close()
        report["evaluation"] = evaluate(report["results"])
        records.emit("run_finished", status=report["status"], error=report["error"])
        try:
            records.finish(report)
        finally:
            records.close()
    return report, records.directory


async def run_demo(*args, **kwargs):
    """Compatibility wrapper for the legacy explicit simulation harness."""
    from .simulation import run_demo as _run_demo
    return await _run_demo(*args, **kwargs)

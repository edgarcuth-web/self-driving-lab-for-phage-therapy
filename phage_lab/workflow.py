"""Validated experiment orchestration with explicit hardware execution modes."""

import asyncio
from datetime import datetime
import math
from pathlib import Path
import re

from .biology import read_fasta
from .devices import Command, DeviceUnavailable
from .records import RunRecords, evaluate, utc_now
from .provenance import source_identity

EXECUTION_MODES = ("real_hardware", "virtual_hardware")

# Every experiment-path candidate must carry all of these, as nonempty strings.
CANDIDATE_PROVENANCE_FIELDS = ("source_db", "accession", "retrieved_at", "source_uri")

# Records produced from a pinned snapshot additionally name the snapshot. They
# are not required of every candidate — an isolate from a lab's own collection
# has a legitimate source and no snapshot — but a record carrying one of them
# must carry both, and `require_snapshot` makes them mandatory for a run.
SNAPSHOT_PROVENANCE_FIELDS = ("snapshot_version", "snapshot_sha256")
SHA256_PATTERN = re.compile(r"\A[0-9a-f]{64}\Z")

# Inclusive (minimum, maximum) candidates a plan may select when the caller
# does not state its own bound.
DEFAULT_SELECTION_SIZE = (1, 3)

# The default operation graph for a run that is not synthesizing anything new:
# prepare the host and the candidate phages, infect, then read out. Callers pass
# their own workflow when their protocol differs.
STANDARD_WORKFLOW = {"prepare": (), "infect": ("prepare",), "measure": ("infect",)}


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
                  operations: tuple[str, ...] | list[str] | None = None, *,
                  selection_size: tuple[int, int] = DEFAULT_SELECTION_SIZE) -> None:
    """Validate an agent plan against the offered candidates and devices.

    ``selection_size`` is the inclusive ``(minimum, maximum)`` number of
    candidates a plan may select. A single phage and a six-member cocktail are
    both legitimate experiments, so the bound belongs to the experiment spec
    rather than to this function.
    """
    low, high = selection_size
    if not 1 <= low <= high:
        raise WorkflowError("selection_size must be an inclusive range of at least one candidate.")
    if not isinstance(plan, dict) or set(plan) != {"candidate_ids", "device_assignments", "reason"}:
        raise WorkflowError("Invalid plan fields.")
    _validate_reason(plan)
    ids = plan["candidate_ids"]
    allowed = {item["id"] for item in candidates if isinstance(item, dict) and isinstance(item.get("id"), str)}
    if (not isinstance(ids, list) or not low <= len(ids) <= high
            or any(not isinstance(item, str) or item not in allowed for item in ids)
            or len(set(ids)) != len(ids)):
        raise WorkflowError(
            f"Plan must select between {low} and {high} distinct offered candidate IDs.")
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


def _validate_snapshot_provenance(candidate: dict, identifier: str, *,
                                  require_snapshot: bool) -> None:
    present = [field for field in SNAPSHOT_PROVENANCE_FIELDS
               if candidate.get(field) not in (None, "")]
    if require_snapshot and len(present) != len(SNAPSHOT_PROVENANCE_FIELDS):
        raise WorkflowError(
            f"Candidate {identifier!r} did not come from a pinned snapshot: "
            f"{', '.join(SNAPSHOT_PROVENANCE_FIELDS)} are required for this run.")
    if not present:
        return
    missing = [field for field in SNAPSHOT_PROVENANCE_FIELDS if field not in present]
    if missing:
        raise WorkflowError(
            f"Candidate {identifier!r} names a snapshot but omits {', '.join(missing)}; "
            "a snapshot reference is only traceable with both fields.")
    for field in SNAPSHOT_PROVENANCE_FIELDS:
        if not isinstance(candidate[field], str) or not candidate[field].strip():
            raise WorkflowError(f"Candidate {identifier!r} has a non-string {field}.")
    if not SHA256_PATTERN.match(candidate["snapshot_sha256"]):
        raise WorkflowError(
            f"Candidate {identifier!r} has a snapshot_sha256 that is not a SHA-256 digest.")


def _validate_candidates(candidates: list[dict], *,
                         min_candidates: int = 1, max_candidates: int | None = None,
                         require_snapshot: bool = False) -> None:
    """Require positive, traceable provenance on every experiment-path candidate.

    This is an allowlist, not a denylist. A candidate record is accepted only
    when it names where it came from and when it was retrieved, so that a plan
    can be traced back to an external source. Rejecting by naming convention
    (``SIM-*`` prefixes and the like) only catches fixtures that happen to be
    labelled honestly, so it is not used here.
    """
    if not candidates:
        raise WorkflowError("An experiment run requires externally supplied candidate records.")
    if len(candidates) < min_candidates:
        raise WorkflowError(f"An experiment run requires at least {min_candidates} candidate records.")
    if max_candidates is not None and len(candidates) > max_candidates:
        raise WorkflowError(f"An experiment run accepts at most {max_candidates} candidate records.")
    seen: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise WorkflowError("Each candidate must be a record object.")
        identifier = candidate.get("id")
        if not isinstance(identifier, str) or not identifier.strip():
            raise WorkflowError("Each candidate requires a nonempty string ID.")
        if identifier in seen:
            raise WorkflowError(f"Duplicate candidate ID {identifier!r}.")
        seen.add(identifier)
        missing = [field for field in CANDIDATE_PROVENANCE_FIELDS
                   if not isinstance(candidate.get(field), str) or not candidate[field].strip()]
        if missing:
            raise WorkflowError(
                f"Candidate {identifier!r} is missing traceable provenance: {', '.join(missing)}. "
                "Experiment-path candidates must record the external source they came from.")
        if candidate.get("simulated") is True:
            raise WorkflowError(f"Candidate {identifier!r} is explicitly marked simulated.")
        try:
            datetime.fromisoformat(candidate["retrieved_at"])
        except ValueError:
            raise WorkflowError(
                f"Candidate {identifier!r} has a non-ISO-8601 retrieved_at timestamp.") from None
        _validate_snapshot_provenance(candidate, identifier, require_snapshot=require_snapshot)


def validate_experiment_inputs(candidates: list[dict], devices: dict, execution_mode: str, *,
                               require_snapshot: bool = False) -> None:
    if execution_mode not in EXECUTION_MODES:
        raise WorkflowError("Unknown execution mode.")
    _validate_candidates(candidates, require_snapshot=require_snapshot)
    if not devices:
        raise WorkflowError("An experiment run requires configured device drivers.")
    expected_simulated = execution_mode == "virtual_hardware"
    for device_id, device in devices.items():
        manifest = device.describe()
        if manifest.get("simulated") is not expected_simulated:
            expected = "simulated=True" if expected_simulated else "simulated=False"
            raise WorkflowError(
                f"{execution_mode} refused device {device_id!r}: driver must explicitly declare {expected}.")
        if not isinstance(manifest.get("device_id"), str) or manifest["device_id"] != device_id:
            raise WorkflowError("Device manifest must match its configured device ID.")


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


def _quarantine(device) -> None:
    """Advisory: take a driver out of service when it supports being stopped."""
    hook = getattr(device, "quarantine", None)
    if callable(hook):
        hook()


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
                _quarantine(device)
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
                _quarantine(device)
                device_id = decision["replacement_device_id"]
            self.records.emit("recovery_executing", step=operation, device=device_id,
                              action=decision["action"], next_attempt=attempt + 1)
        raise WorkflowError("Attempt limit reached.")


async def run_experiment(genome_path: Path, output_root: Path, *, sample_id: str,
                         candidates: list[dict], devices: dict | None, workflow: dict, agent,
                         execution_mode: str, selection_size: tuple[int, int] = DEFAULT_SELECTION_SIZE,
                         require_snapshot: bool = False, timeout_seconds: float = 60.0,
                         echo: bool = True, on_event=None) -> tuple[dict, Path]:
    """Run an experiment plan against physical or explicitly virtual hardware.

    ``execution_mode`` is required: there is no default, because a caller that
    did not state which kind of hardware it expects should not be given either.

    Candidate records must always be externally supplied and carry traceable
    provenance. ``virtual_hardware`` may emulate instruments, but its outputs
    are not physical measurements and must never be represented as evidence.
    """
    if not isinstance(sample_id, str) or not sample_id.strip():
        raise ValueError("sample_id must be a nonempty string.")
    if execution_mode not in EXECUTION_MODES:
        raise ValueError(f"execution_mode must be one of {EXECUTION_MODES}.")
    operations = _validate_workflow(workflow)
    _validate_candidates(candidates, min_candidates=selection_size[0],
                         require_snapshot=require_snapshot)
    if execution_mode == "real_hardware" and not devices:
        raise WorkflowError("real_hardware requires configured physical device drivers.")
    if devices:
        validate_experiment_inputs(candidates, devices, execution_mode,
                                   require_snapshot=require_snapshot)

    records = RunRecords(output_root, echo, on_event=on_event)
    if execution_mode == "virtual_hardware" and not devices:
        from .virtual_hardware import make_virtual_devices
        devices = make_virtual_devices(operations, records.emit)
        validate_experiment_inputs(candidates, devices, execution_mode,
                                   require_snapshot=require_snapshot)

    physical_execution = execution_mode == "real_hardware"
    report = {"schema_version": 2, "started_at": utc_now(), "status": "running",
              "simulated": not physical_execution, "execution_mode": execution_mode,
              "physical_execution": physical_execution,
              "agent": getattr(agent, "name", type(agent).__name__),
              "sample_id": sample_id, "results": {}, "recoveries": [], "error": None,
              "limitations": ["Biological efficacy is not inferred by the orchestration layer."]}
    if not physical_execution:
        report["limitations"].append(
            "Instrument actions and resulting device outputs are virtual; no wet-lab experiment occurred.")
    try:
        records.emit("run_started", agent=report["agent"], execution_mode=execution_mode,
                     physical_execution=physical_execution, sample_id=sample_id)
        report["source"] = source_identity()
        records.emit("source_identified", **report["source"])
        genome = read_fasta(genome_path)
        report["genome"] = genome.public_metadata()
        records.emit("input_validated", **report["genome"])
        report["candidates"] = candidates
        report["candidate_sources"] = sorted({candidate["source_db"] for candidate in candidates})
        report["candidate_snapshots"] = sorted(
            {f"{candidate['source_db']} {candidate['snapshot_version']} "
             f"({candidate['snapshot_sha256'][:12]})"
             for candidate in candidates if candidate.get("snapshot_version")})
        manifests = [device.describe() for device in devices.values()]
        records.emit("devices_discovered", count=len(manifests), execution_mode=execution_mode)
        records.emit("planning_requested", agent=report["agent"])
        plan = await agent.plan({"genome": genome.public_metadata(), "candidates": candidates,
                                "devices": manifests, "workflow": workflow,
                                "execution_mode": execution_mode,
                                "physical_execution": physical_execution,
                                "selection_size": list(selection_size)})
        validate_plan(plan, candidates, devices, operations=operations,
                      selection_size=selection_size)
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


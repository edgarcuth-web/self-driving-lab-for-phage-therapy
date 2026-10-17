"""Validated experiment orchestration with explicit hardware execution modes."""

import asyncio
from datetime import datetime
import math
from pathlib import Path
import re

from .biology import read_fasta
from .devices import (
    Command,
    DeviceError,
    DeviceUnavailable,
    SafeStateError,
    validate_execution_payload,
    validate_safe_state,
)
from .experiment_spec import (
    ExperimentSpec,
    bind_candidates_to_spec,
)
from .interaction_evidence import interaction_evidence_from_dict
from .material_batch import (
    ExperimentMaterials,
    MaterialBatch,
    bind_material_batches_to_spec,
)
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

# A candidate ordered by an external host-range tool carries a `ranking` block.
# It records which tool produced the order and against which host genome, so a
# plan's ordering can be reproduced or disputed. An ordering with no tool behind
# it is not a ranking, so these fields are all required once the block exists.
RANKING_REQUIRED_FIELDS = ("tool", "tool_version", "ranked_at", "host_genome_sha256",
                           "statistic", "interpretation", "reported")
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


def validate_device_assignment(
    decision: dict,
    devices: dict,
    operations: tuple[str, ...] | list[str],
) -> None:
    """Validate orchestration-only assignment for a locked ExperimentSpec."""

    if not isinstance(decision, dict) or set(decision) != {
        "device_assignments",
        "reason",
    }:
        raise WorkflowError(
            "Device assignment must contain exactly device_assignments and reason."
        )
    _validate_reason(decision)
    assignments = decision["device_assignments"]
    operations = tuple(operations)
    if not isinstance(assignments, dict) or set(assignments) != set(operations):
        raise WorkflowError(
            "Device assignment must assign exactly every workflow operation."
        )
    for operation, device_id in assignments.items():
        if (
            not isinstance(device_id, str)
            or device_id not in devices
            or operation not in devices[device_id].describe().get("operations", [])
        ):
            raise WorkflowError(
                "Device assignment selected an unknown or incompatible device."
            )


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


def _validate_ranking(candidate: dict, identifier: str) -> tuple[str, str] | None:
    """Check a ranking block, and report the (tool, host genome) it came from."""
    block = candidate.get("ranking")
    if block is None:
        return None
    if not isinstance(block, dict):
        raise WorkflowError(f"Candidate {identifier!r} has a non-object ranking block.")
    missing = [field for field in RANKING_REQUIRED_FIELDS if field not in block]
    if missing:
        raise WorkflowError(
            f"Candidate {identifier!r} has a ranking block missing {', '.join(missing)}. "
            "An ordering without a named tool behind it is not a ranking.")
    for field in ("tool", "tool_version", "ranked_at", "host_genome_sha256",
                  "statistic", "interpretation"):
        if not isinstance(block[field], str) or not block[field].strip():
            raise WorkflowError(f"Candidate {identifier!r} has an empty ranking {field}.")
    if not isinstance(block["reported"], bool):
        raise WorkflowError(f"Candidate {identifier!r} has a non-boolean ranking.reported.")
    if not SHA256_PATTERN.match(block["host_genome_sha256"]):
        raise WorkflowError(
            f"Candidate {identifier!r} ranking names a host genome digest that is not SHA-256.")
    rank = block.get("rank")
    if block["reported"]:
        if not isinstance(rank, int) or isinstance(rank, bool) or rank < 1:
            raise WorkflowError(
                f"Candidate {identifier!r} is marked reported but has no positive rank.")
    elif rank is not None:
        raise WorkflowError(
            f"Candidate {identifier!r} was not reported by the tool but carries a rank.")
    offenders = [key for key in block
                 if re.search(r"(probab|likelihood|success|efficacy|infectivity)", key, re.I)]
    if offenders:
        raise WorkflowError(
            f"Candidate {identifier!r} ranking contains {', '.join(offenders)}; a tool "
            "statistic must not be presented as a probability of infection.")
    return block["tool"], block["host_genome_sha256"]


def _validate_interaction_evidence(candidate: dict, identifier: str) -> None:
    records = candidate.get("interaction_evidence")
    if records is None:
        return
    if not isinstance(records, list) or not records:
        raise WorkflowError(
            f"Candidate {identifier!r} interaction_evidence must be a nonempty array."
        )
    expected_profile_id = candidate.get("phage_profile_id") or f"{identifier}:v1"
    seen: set[str] = set()
    for raw in records:
        try:
            evidence = interaction_evidence_from_dict(raw)
        except ValueError as exc:
            raise WorkflowError(
                f"Candidate {identifier!r} carries invalid InteractionEvidence: {exc}"
            ) from None
        if evidence.evidence_id in seen:
            raise WorkflowError(
                f"Candidate {identifier!r} repeats InteractionEvidence {evidence.evidence_id}."
            )
        seen.add(evidence.evidence_id)
        if evidence.phage_profile_id != expected_profile_id:
            raise WorkflowError(
                f"Candidate {identifier!r} evidence targets {evidence.phage_profile_id!r}, "
                f"not {expected_profile_id!r}."
            )
        ranking = candidate.get("ranking")
        if (
            isinstance(ranking, dict)
            and evidence.producer.name == "phist"
            and evidence.host.genome_sha256 != ranking.get("host_genome_sha256")
        ):
            raise WorkflowError(
                f"Candidate {identifier!r} PHIST evidence and ranking name different host genomes."
            )


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
    rankings: set[tuple[str, str]] = set()
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
        origin = _validate_ranking(candidate, identifier)
        _validate_interaction_evidence(candidate, identifier)
        if origin is not None:
            rankings.add(origin)
    if len(rankings) > 1:
        raise WorkflowError(
            "Candidates carry rankings from different tools or host genomes; "
            "ranks from separate comparisons cannot be ordered against each other.")
    if rankings and len(rankings) == 1 and any("ranking" not in candidate for candidate in candidates):
        raise WorkflowError(
            "Some candidates are ranked and some are not; a partial ordering would make "
            "the unranked ones look worse than the tool actually said.")


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
        # A driver that moves real liquid must say what its apparatus does when a
        # step is abandoned. Nobody can infer that on the driver's behalf.
        try:
            validate_safe_state(manifest, device_id)
        except DeviceError as exc:
            raise WorkflowError(str(exc)) from None


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


def _ranking_summary(candidates: list[dict]) -> dict | None:
    """Describe where a plan's candidate ordering came from, or say there is none."""
    blocks = [candidate["ranking"] for candidate in candidates if candidate.get("ranking")]
    if not blocks:
        return {"ordered_by": "source_order",
                "note": ("Candidates are in the order the source database returned them. "
                         "No host-range tool was run; the order carries no biological meaning.")}
    first = blocks[0]
    return {"ordered_by": first["tool"], "tool_version": first["tool_version"],
            "statistic": first["statistic"], "ranked_at": first["ranked_at"],
            "host_genome_sha256": first["host_genome_sha256"],
            "parameters": first.get("parameters"),
            "reported_count": sum(1 for block in blocks if block["reported"]),
            "unreported_count": sum(1 for block in blocks if not block["reported"]),
            "interpretation": first["interpretation"]}


def _plan_ranking(selected: list[str], candidates: list[dict]) -> dict:
    """Say, per selected candidate, whether a tool actually reported it.

    Without this a reader cannot tell a top-ranked pick from one that merely sat
    near the top of an unordered list.
    """
    by_id = {candidate["id"]: candidate for candidate in candidates}
    ranks, unsupported = {}, []
    for identifier in selected:
        block = by_id.get(identifier, {}).get("ranking")
        if not block:
            return {"ordered_by": "source_order",
                    "note": "No host-range tool was run; selection order carries no biological meaning."}
        if block["reported"]:
            ranks[identifier] = block["rank"]
        else:
            unsupported.append(identifier)
    summary = {"ordered_by": by_id[selected[0]]["ranking"]["tool"], "ranks": ranks}
    if unsupported:
        summary["selected_without_tool_support"] = unsupported
        summary["note"] = ("These candidates were selected although the tool reported no "
                           "match. That is an absence of signal, not evidence against them.")
    return summary


class PhysicalStateLedger:
    """Tracks what the apparatus is believed to be holding when a run stops.

    The orchestrator halting is not the same as the bench being safe. This
    records, per device, whether it confirmed its declared safe state, so a
    report tells an operator whether they are walking up to a parked machine, a
    contained hazard, or a device whose state nobody knows.
    """

    def __init__(self, emit):
        self.emit = emit
        self.devices: dict[str, dict] = {}
        self.touched: dict[str, object] = {}

    def touched_device(self, device_id: str, device) -> None:
        """Note that this device was given physical work in this run."""
        self.touched.setdefault(device_id, device)

    def record_unknown(self, device_id: str, reason: str) -> None:
        """The device could not be asked, so its physical state is unknown."""
        self.devices[device_id] = {"entered": False, "policy": None,
                                   "retains_hazard": None, "status": "unknown",
                                   "detail": reason}
        self.emit("physical_state_unknown", device=device_id, reason=reason)

    async def request(self, device_id: str, device, reason: str) -> None:
        hook = getattr(device, "enter_safe_state", None)
        if not callable(hook):
            self.devices[device_id] = {
                "entered": False, "policy": None, "retains_hazard": None,
                "status": "unknown",
                "detail": ("Driver implements no enter_safe_state; the controller could not "
                           "ask it to make itself safe.")}
            self.emit("safe_state_unsupported", device=device_id, reason=reason)
            return
        try:
            outcome = await hook(reason)
        except (SafeStateError, DeviceUnavailable) as exc:
            self.record_unknown(device_id,
                                f"Device did not confirm its safe state: {exc}")
            return
        except Exception as exc:  # a driver bug must not hide the hazard
            self.record_unknown(device_id,
                                f"Safe-state request raised {type(exc).__name__}: {exc}")
            return
        if not isinstance(outcome, dict) or not isinstance(outcome.get("entered"), bool):
            self.record_unknown(device_id,
                                "Driver returned no usable safe-state confirmation.")
            return
        entered = outcome["entered"]
        retains = outcome.get("retains_hazard")
        status = ("safe" if entered and retains is False
                  else "hazard_retained" if entered else "unknown")
        self.devices[device_id] = {"entered": entered, "policy": outcome.get("policy"),
                                   "retains_hazard": retains, "status": status,
                                   "detail": outcome.get("detail", "")}
        self.emit("safe_state_requested", device=device_id, reason=reason,
                  entered=entered, status=status, policy=outcome.get("policy"))

    async def settle(self, reason: str) -> None:
        """Ask every device that did physical work, unless already recorded."""
        for device_id, device in self.touched.items():
            if device_id not in self.devices:
                await self.request(device_id, device, reason)

    def summary(self, *, physical_execution: bool) -> dict:
        """The block a report carries so an operator knows what to approach.

        The worst device decides the overall status: one unconfirmed device
        makes the whole apparatus unknown, because a person walking up to the
        bench meets all of it, not the average of it.
        """
        if not self.devices:
            summary = {"status": "not_requested", "operator_action_required": False,
                       "devices": {},
                       "note": ("No step was abandoned on a device, so no safe-state request "
                                "was made.")}
        else:
            statuses = {entry["status"] for entry in self.devices.values()}
            status = ("unknown" if "unknown" in statuses
                      else "hazard_retained" if "hazard_retained" in statuses else "safe")
            notes = {
                "unknown": ("At least one device did not confirm its safe state. Treat the "
                            "apparatus as potentially holding hazardous material and follow "
                            "the reagent's handling procedure before approaching it."),
                "hazard_retained": ("Devices reached their declared safe state, but that state "
                                    "still holds hazardous material. Approach only per the "
                                    "reagent's handling procedure."),
                "safe": "Every device confirmed a safe state that retains no hazard."}
            summary = {"status": status, "operator_action_required": status != "safe",
                       "devices": dict(self.devices), "note": notes[status]}
        if not physical_execution:
            summary["note"] = ("Virtual hardware: no physical apparatus was involved. "
                               + summary["note"])
        return summary


def _quarantine(device) -> None:
    """Advisory: take a driver out of service when it supports being stopped."""
    hook = getattr(device, "quarantine", None)
    if callable(hook):
        hook()


class Scheduler:
    def __init__(self, devices: dict, agent, records: RunRecords, report: dict,
                 time_scale: float | None = None, *, timeout_seconds: float | None = None,
                 ledger: PhysicalStateLedger | None = None):
        self.devices = devices
        self.agent = agent
        self.records = records
        self.report = report
        self.ledger = ledger if ledger is not None else PhysicalStateLedger(records.emit)
        if timeout_seconds is None:
            if time_scale is None or not math.isfinite(time_scale) or time_scale <= 0:
                raise ValueError("A positive time scale or timeout must be provided.")
            timeout_seconds = max(0.05, 1.2 * time_scale)
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive and finite.")
        self.timeout = timeout_seconds

    async def execute(self, operation: str, device_id: str, payload: dict) -> dict:
        validate_execution_payload(payload)
        command_id = f"{self.records.run_id}:{operation}"
        for attempt in (1, 2):
            device = self.devices[device_id]
            self.ledger.touched_device(device_id, device)
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
                # The device is unreachable, so it cannot be asked to make itself
                # safe either. Say so rather than leaving the report silent.
                self.ledger.record_unknown(
                    device_id,
                    f"Device became unreachable during {operation!r}; neither the job outcome "
                    "nor the physical state could be confirmed.")
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
                self.ledger.record_unknown(
                    device_id,
                    f"Cancellation of {operation!r} was not acknowledged; the device may still "
                    "be executing the original job.")
                raise WorkflowError("Cancellation was not acknowledged; retry refused.")
            self.report["recoveries"].append({"step": operation, "outcome": decision["action"],
                                              "from_device": device_id, **decision})
            if decision["action"] == "cancel_and_failover":
                _quarantine(device)
                device_id = decision["replacement_device_id"]
            self.records.emit("recovery_executing", step=operation, device=device_id,
                              action=decision["action"], next_attempt=attempt + 1)
        raise WorkflowError("Attempt limit reached.")


async def _plan_for_run(agent, *, spec, genome, candidates, devices, workflow,
                        execution_mode, selection_size, records):
    """Resolve a plan once; the scheduler executes the same shape for both entries."""
    if spec is None:
        from .legacy import request_candidate_plan
        return await request_candidate_plan(
            agent, genome=genome, candidates=candidates, devices=devices,
            workflow=workflow, execution_mode=execution_mode,
            selection_size=selection_size, records=records,
        )
    experiment_spec = spec
    manifests = [device.describe() for device in devices.values()]
    operations = tuple(workflow)
    physical_execution = execution_mode == "real_hardware"
    assign = getattr(agent, "assign_devices", None)
    if not callable(assign):
        raise WorkflowError(
            "Spec-bound execution requires an agent with assign_devices()."
        )
    records.emit(
        "device_assignment_requested",
        agent=getattr(agent, "name", type(agent).__name__),
        spec_id=experiment_spec.spec_id,
    )
    decision = await assign({
        "experiment_spec": experiment_spec.to_dict(),
        "devices": manifests,
        "workflow": experiment_spec.workflow_dict(),
        "execution_mode": execution_mode,
        "physical_execution": physical_execution,
    })
    validate_device_assignment(decision, devices, operations)
    locked_ids = [candidate["id"] for candidate in candidates]
    plan = {
        "candidate_ids": locked_ids,
        "device_assignments": decision["device_assignments"],
        "reason": decision["reason"],
    }
    records.emit(
        "device_assignment_accepted",
        agent=getattr(agent, "name", type(agent).__name__),
        spec_id=experiment_spec.spec_id,
        **decision,
    )
    return plan


async def run_experiment(genome_path: Path, output_root: Path, *, sample_id: str,
                         candidates: list[dict], devices: dict | None, workflow: dict, agent,
                         execution_mode: str, selection_size: tuple[int, int] = DEFAULT_SELECTION_SIZE,
                         require_snapshot: bool = False, timeout_seconds: float = 60.0,
                         echo: bool = True, on_event=None,
                         experiment_spec: ExperimentSpec | None = None,
                         material_batches: list[MaterialBatch] | None = None) -> tuple[dict, Path]:
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
    if experiment_spec is not None and not isinstance(experiment_spec, ExperimentSpec):
        raise ValueError("experiment_spec must be an ExperimentSpec or None.")
    if material_batches is not None:
        if experiment_spec is None:
            raise WorkflowError(
                "MaterialBatch binding requires an ExperimentSpec-bound run."
            )
        if (
            not isinstance(material_batches, list)
            or any(not isinstance(batch, MaterialBatch) for batch in material_batches)
        ):
            raise ValueError(
                "material_batches must be a list of MaterialBatch objects."
            )
    bound_materials: ExperimentMaterials | None = None
    if experiment_spec is not None:
        spec_workflow = experiment_spec.workflow_dict()
        normalized_workflow = {
            operation: tuple(dependencies)
            for operation, dependencies in workflow.items()
        }
        if normalized_workflow != spec_workflow:
            raise WorkflowError(
                "Runtime workflow does not match the locked ExperimentSpec."
            )
        try:
            candidates = bind_candidates_to_spec(experiment_spec, candidates)
        except ValueError as exc:
            raise WorkflowError(str(exc)) from None
        operations = _validate_workflow(spec_workflow)
        locked_member_count = len(experiment_spec.member_phage_profile_ids)
        if locked_member_count < 1:
            raise WorkflowError(
                "The current run executor requires at least one phage across ExperimentSpec arms."
            )
        _validate_candidates(
            candidates,
            min_candidates=locked_member_count,
            max_candidates=locked_member_count,
            require_snapshot=require_snapshot,
        )
        if material_batches is not None:
            try:
                bound_materials = bind_material_batches_to_spec(
                    experiment_spec,
                    material_batches,
                )
            except ValueError as exc:
                raise WorkflowError(str(exc)) from None
        if execution_mode == "real_hardware" and bound_materials is None:
            raise WorkflowError(
                "ExperimentSpec-bound real_hardware requires test-ready MaterialBatch records "
                "for the host and every phage member."
            )
    else:
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
    report = {"schema_version": 4, "started_at": utc_now(), "status": "running",
              "simulated": not physical_execution, "execution_mode": execution_mode,
              "physical_execution": physical_execution,
              "agent": getattr(agent, "name", type(agent).__name__),
              "sample_id": sample_id,
              "scientific_membership_locked": experiment_spec is not None,
              "results": {}, "recoveries": [], "error": None,
              "limitations": ["Biological efficacy is not inferred by the orchestration layer."]}
    if not physical_execution:
        report["limitations"].append(
            "Instrument actions and resulting device outputs are virtual; no wet-lab experiment occurred.")
        if bound_materials is not None:
            report["limitations"].append(
                "MaterialBatch metadata was bound for lineage only; virtual execution did not consume physical material."
            )
    ledger = PhysicalStateLedger(records.emit)
    try:
        records.emit("run_started", agent=report["agent"], execution_mode=execution_mode,
                     physical_execution=physical_execution, sample_id=sample_id)
        report["source"] = source_identity()
        records.emit("source_identified", **report["source"])
        genome = read_fasta(genome_path)
        report["genome"] = genome.public_metadata()
        if (
            experiment_spec is not None
            and genome.sha256 != experiment_spec.target_host.genome_sha256
        ):
            raise WorkflowError(
                "Runtime host genome does not match the locked ExperimentSpec."
            )
        records.emit("input_validated", **report["genome"])
        if experiment_spec is not None:
            report["experiment_spec"] = experiment_spec.to_dict()
            source_design = experiment_spec.source_design
            records.emit(
                "experiment_spec_bound",
                spec_id=experiment_spec.spec_id,
                source_design_id=(
                    source_design.design_id if source_design is not None else None
                ),
                arm_ids=[arm.arm_id for arm in experiment_spec.arms],
                members=list(experiment_spec.member_phage_profile_ids),
            )
        report["material_batch_ids"] = (
            list(bound_materials.batch_ids) if bound_materials is not None else []
        )
        if bound_materials is not None:
            report["material_batches"] = bound_materials.to_dict()
            records.emit(
                "material_batches_bound",
                spec_id=experiment_spec.spec_id,
                batch_ids=list(bound_materials.batch_ids),
                physical_execution=physical_execution,
            )
        report["candidates"] = candidates
        report["candidate_sources"] = sorted({candidate["source_db"] for candidate in candidates})
        report["candidate_ranking"] = _ranking_summary(candidates)
        report["candidate_snapshots"] = sorted(
            {f"{candidate['source_db']} {candidate['snapshot_version']} "
             f"({candidate['snapshot_sha256'][:12]})"
             for candidate in candidates if candidate.get("snapshot_version")})
        manifests = [device.describe() for device in devices.values()]
        records.emit("devices_discovered", count=len(manifests), execution_mode=execution_mode)
        plan = await _plan_for_run(
            agent, spec=experiment_spec, genome=genome, candidates=candidates,
            devices=devices, workflow=workflow, execution_mode=execution_mode,
            selection_size=selection_size, records=records,
        )
        report["plan"] = plan
        report["plan_ranking"] = _plan_ranking(plan["candidate_ids"], candidates)
        if report["plan_ranking"].get("selected_without_tool_support"):
            records.emit("plan_includes_unreported_candidates",
                         candidates=report["plan_ranking"]["selected_without_tool_support"],
                         note=("Selected candidates the host-range tool did not report. "
                               "Absence of the tool's signal is not evidence against them, "
                               "but nothing supports them either."))
        scheduler = Scheduler(devices, agent, records, report,
                              timeout_seconds=timeout_seconds, ledger=ledger)
        payload = {"sample_id": sample_id, "candidate_ids": list(plan["candidate_ids"])}
        if experiment_spec is not None:
            payload.update({
                "experiment_spec_id": experiment_spec.spec_id,
                "experiment_spec_sha256": experiment_spec.content_sha256,
                "phage_profile_ids": list(experiment_spec.member_phage_profile_ids),
                "experiment_arms": [arm.to_dict() for arm in experiment_spec.arms],
            })
            source_design = experiment_spec.source_design
            if source_design is not None:
                payload["cocktail_design_id"] = source_design.design_id
            if bound_materials is not None:
                payload["material_batch_ids"] = list(bound_materials.batch_ids)
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
        # A run that did not finish may have left an instrument mid-step. Ask
        # every device that did physical work to reach its declared safe state,
        # before releasing the drivers, and record what each one confirmed.
        if report["status"] != "succeeded":
            try:
                await ledger.settle(f"run {report['status']}: {report['error'] or 'stopped'}")
            except Exception as exc:  # never let this mask the original failure
                records.emit("safe_state_settle_failed", error=f"{type(exc).__name__}: {exc}")
        report["physical_state"] = ledger.summary(physical_execution=physical_execution)
        if report["physical_state"]["operator_action_required"]:
            report["limitations"].append(
                "A device did not confirm a hazard-free safe state; see physical_state "
                "before approaching the apparatus.")
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


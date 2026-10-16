"""Arm-scoped measurement ingestion from completed run reports.

Measurement v2 preserves device/run/spec lineage and binds each spec-backed
measurement to exactly one ExperimentArm. A spec-bound device result must expose
an arms mapping so ingestion never invents arm membership after execution.
Virtual outputs remain non-evidence.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path

from .experiment_spec import ExperimentArm, experiment_spec_from_dict

SCHEMA_VERSION = 2
ORIGINS = ("physical_run", "virtual_run")
QC_STATUSES = ("pending", "valid", "invalid")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a nonempty string.")
    return value.strip()


def _validate_timestamp(value: str, field_name: str) -> None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp.") from None
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone.")


def _validate_digest(value: str, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ValueError(f"{field_name} must be a SHA-256 digest.")


def _validate_text_tuple(values: tuple[str, ...], field_name: str) -> None:
    if not isinstance(values, tuple):
        raise ValueError(f"{field_name} must be a tuple.")
    for value in values:
        _require_text(value, field_name)
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} values must be unique.")


def _validate_json(value, field_name: str = "data") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{field_name} contains a non-finite number.")
        return
    if isinstance(value, list):
        for item in value:
            _validate_json(item, field_name)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _require_text(key, f"{field_name} key")
            _validate_json(item, field_name)
        return
    raise ValueError(f"{field_name} must contain JSON-compatible values.")


@dataclass(frozen=True)
class Measurement:
    measurement_id: str
    revision: int
    run_id: str
    experiment_spec_id: str | None
    experiment_spec_sha256: str | None
    experiment_arm_id: str | None
    target_host_profile_id: str | None
    phage_profile_ids: tuple[str, ...]
    source_step: str
    device_id: str
    material_batch_ids: tuple[str, ...]
    origin: str
    physical_execution: bool
    qc_status: str
    qc_evidence: tuple[str, ...]
    measurement_type: str
    data: dict
    recorded_at: str
    created_at: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_text(self.measurement_id, "measurement_id")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("revision must be a positive integer.")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"Measurement schema_version must be {SCHEMA_VERSION}."
            )
        _require_text(self.run_id, "run_id")
        if (self.experiment_spec_id is None) != (
            self.experiment_spec_sha256 is None
        ):
            raise ValueError(
                "experiment_spec_id and experiment_spec_sha256 must both be set or both be null."
            )
        spec_bound = self.experiment_spec_id is not None
        if spec_bound:
            _require_text(self.experiment_spec_id, "experiment_spec_id")
            _validate_digest(
                self.experiment_spec_sha256,
                "experiment_spec_sha256",
            )
            _require_text(self.experiment_arm_id, "experiment_arm_id")
            _require_text(
                self.target_host_profile_id,
                "target_host_profile_id",
            )
        elif (
            self.experiment_arm_id is not None
            or self.target_host_profile_id is not None
            or self.phage_profile_ids
        ):
            raise ValueError(
                "arm/host/phage lineage requires ExperimentSpec lineage."
            )
        _validate_text_tuple(self.phage_profile_ids, "phage_profile_id")
        _require_text(self.source_step, "source_step")
        _require_text(self.device_id, "device_id")
        _validate_text_tuple(self.material_batch_ids, "material_batch_id")
        if self.origin not in ORIGINS:
            raise ValueError(f"origin must be one of {ORIGINS}.")
        if not isinstance(self.physical_execution, bool):
            raise ValueError("physical_execution must be a boolean.")
        if self.origin == "physical_run" and not self.physical_execution:
            raise ValueError(
                "physical_run Measurement requires physical_execution=True."
            )
        if self.origin == "virtual_run" and self.physical_execution:
            raise ValueError(
                "virtual_run Measurement requires physical_execution=False."
            )
        if self.qc_status not in QC_STATUSES:
            raise ValueError(f"qc_status must be one of {QC_STATUSES}.")
        _validate_text_tuple(self.qc_evidence, "qc_evidence")
        if self.qc_status in {"valid", "invalid"} and not self.qc_evidence:
            raise ValueError(
                f"qc_status={self.qc_status!r} requires qc_evidence."
            )
        _require_text(self.measurement_type, "measurement_type")
        if not isinstance(self.data, dict):
            raise ValueError("data must be an object.")
        _validate_json(self.data)
        _validate_timestamp(self.recorded_at, "recorded_at")
        _validate_timestamp(self.created_at, "created_at")

    @property
    def record_id(self) -> str:
        return f"{self.measurement_id}:v{self.revision}"

    @property
    def evidence_class(self) -> str:
        return "physical_measurement" if self.physical_execution else "none"

    def _content_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "record_id": self.record_id,
            "measurement_id": self.measurement_id,
            "revision": self.revision,
            "run_id": self.run_id,
            "experiment_spec_id": self.experiment_spec_id,
            "experiment_spec_sha256": self.experiment_spec_sha256,
            "experiment_arm_id": self.experiment_arm_id,
            "target_host_profile_id": self.target_host_profile_id,
            "phage_profile_ids": list(self.phage_profile_ids),
            "source_step": self.source_step,
            "device_id": self.device_id,
            "material_batch_ids": list(self.material_batch_ids),
            "origin": self.origin,
            "physical_execution": self.physical_execution,
            "evidence_class": self.evidence_class,
            "qc_status": self.qc_status,
            "qc_evidence": list(self.qc_evidence),
            "measurement_type": self.measurement_type,
            "data": self.data,
            "recorded_at": self.recorded_at,
            "created_at": self.created_at,
        }

    @property
    def content_sha256(self) -> str:
        canonical = json.dumps(
            self._content_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return sha256(canonical).hexdigest()

    def to_dict(self) -> dict:
        return {"content_sha256": self.content_sha256, **self._content_dict()}


def _arm_by_id(spec, arm_id: str) -> ExperimentArm:
    arm_id = _require_text(arm_id, "arm_id")
    matches = [arm for arm in spec.arms if arm.arm_id == arm_id]
    if not matches:
        raise ValueError(f"ExperimentSpec has no arm {arm_id!r}.")
    return matches[0]


def _arm_material_batch_ids(report: dict, arm: ExperimentArm) -> tuple[str, ...]:
    material = report.get("material_batches")
    if material is None:
        return ()
    if not isinstance(material, dict):
        raise ValueError("run report material_batches must be an object.")

    host = material.get("host_batch")
    phages = material.get("phage_batches")
    if not isinstance(host, dict) or not isinstance(phages, list):
        raise ValueError(
            "run report material_batches lacks host/phage batch detail."
        )
    if host.get("profile_id") != arm.target_host.profile_id:
        raise ValueError(
            "run report host MaterialBatch does not match the ExperimentArm host."
        )
    host_record_id = _require_text(host.get("record_id"), "host batch record_id")

    by_profile: dict[str, list[dict]] = {}
    for batch in phages:
        if not isinstance(batch, dict):
            raise ValueError("run report phage batch entry must be an object.")
        profile_id = _require_text(batch.get("profile_id"), "phage batch profile_id")
        by_profile.setdefault(profile_id, []).append(batch)

    selected = [host_record_id]
    for profile_id in arm.phage_profile_ids:
        matches = by_profile.get(profile_id, [])
        if len(matches) != 1:
            raise ValueError(
                f"ExperimentArm phage {profile_id!r} does not map to exactly one "
                "run-report MaterialBatch."
            )
        selected.append(
            _require_text(matches[0].get("record_id"), "phage batch record_id")
        )
    return tuple(selected)


def measurement_from_run_report(
    report: dict,
    *,
    measurement_id: str,
    arm_id: str | None = None,
    source_step: str = "measure",
    measurement_type: str = "device_result",
    qc_status: str = "pending",
    qc_evidence: tuple[str, ...] = (),
    revision: int = 1,
    created_at: str | None = None,
) -> Measurement:
    """Ingest one arm-scoped completed device result without inferring phenotype."""

    if not isinstance(report, dict):
        raise ValueError("run report must be an object.")
    run_id = _require_text(report.get("run_id"), "run report run_id")
    results = report.get("results")
    if not isinstance(results, dict) or source_step not in results:
        raise ValueError(
            f"run report has no completed result for step {source_step!r}."
        )
    result = results[source_step]
    if not isinstance(result, dict):
        raise ValueError("run result must be an object.")

    plan = report.get("plan")
    if not isinstance(plan, dict):
        raise ValueError("run report has no plan.")
    assignments = plan.get("device_assignments")
    if not isinstance(assignments, dict):
        raise ValueError("run report has no device assignments.")
    device_id = _require_text(
        assignments.get(source_step),
        f"device assignment for {source_step}",
    )

    physical_flag = report.get("physical_execution")
    if not isinstance(physical_flag, bool):
        raise ValueError("run report physical_execution must be a boolean.")
    physical = physical_flag
    mode = report.get("execution_mode")
    simulated = report.get("simulated")
    if physical:
        if mode != "real_hardware" or simulated is not False:
            raise ValueError(
                "run report execution_mode/simulated contradicts physical_execution=True."
            )
    else:
        if mode != "virtual_hardware" or simulated is not True:
            raise ValueError(
                "run report execution_mode/simulated contradicts physical_execution=False."
            )
    origin = "physical_run" if physical else "virtual_run"

    raw_spec = report.get("experiment_spec")
    spec_id = None
    spec_sha = None
    experiment_arm_id = None
    host_profile_id = None
    phage_profile_ids: tuple[str, ...] = ()
    batch_ids: tuple[str, ...]
    data: dict

    if raw_spec is not None:
        if not isinstance(raw_spec, dict):
            raise ValueError("run report experiment_spec must be an object.")
        spec = experiment_spec_from_dict(raw_spec)
        if arm_id is None:
            raise ValueError(
                "spec-bound Measurement ingestion requires arm_id."
            )
        arm = _arm_by_id(spec, arm_id)
        arm_results = result.get("arms")
        if not isinstance(arm_results, dict):
            raise ValueError(
                "spec-bound run result must contain an arm-scoped 'arms' mapping."
            )
        arm_result = arm_results.get(arm.arm_id)
        if not isinstance(arm_result, dict):
            raise ValueError(
                f"run result has no completed arm result for {arm.arm_id!r}."
            )
        spec_id = spec.spec_id
        spec_sha = spec.content_sha256
        experiment_arm_id = arm.arm_id
        host_profile_id = arm.target_host.profile_id
        phage_profile_ids = arm.phage_profile_ids
        batch_ids = _arm_material_batch_ids(report, arm)
        data = dict(arm_result)
    else:
        if arm_id is not None:
            raise ValueError("arm_id is allowed only for ExperimentSpec-bound runs.")
        raw_batch_ids = report.get("material_batch_ids", [])
        if not isinstance(raw_batch_ids, list):
            raise ValueError("run report material_batch_ids must be an array.")
        batch_ids = tuple(raw_batch_ids)
        data = dict(result)

    if physical:
        if (
            data.get("simulated") is True
            or data.get("physical_execution") is False
        ):
            raise ValueError(
                "physical run result contradicts its physical_execution provenance."
            )
    else:
        if (
            data.get("simulated") is False
            or data.get("physical_execution") is True
        ):
            raise ValueError(
                "virtual run result contradicts its non-physical provenance."
            )

    recorded_at = report.get("finished_at") or report.get("started_at")
    _validate_timestamp(recorded_at, "run report timestamp")

    return Measurement(
        measurement_id=measurement_id,
        revision=revision,
        run_id=run_id,
        experiment_spec_id=spec_id,
        experiment_spec_sha256=spec_sha,
        experiment_arm_id=experiment_arm_id,
        target_host_profile_id=host_profile_id,
        phage_profile_ids=phage_profile_ids,
        source_step=source_step,
        device_id=device_id,
        material_batch_ids=batch_ids,
        origin=origin,
        physical_execution=physical,
        qc_status=qc_status,
        qc_evidence=qc_evidence,
        measurement_type=measurement_type,
        data=data,
        recorded_at=recorded_at,
        created_at=created_at or utc_now(),
    )


def measurement_from_dict(data: dict) -> Measurement:
    if not isinstance(data, dict):
        raise ValueError("Measurement must be an object.")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            "Measurement schema_version is not supported; re-ingest v1 records as v2."
        )
    required = {
        "content_sha256",
        "schema_version",
        "record_id",
        "measurement_id",
        "revision",
        "run_id",
        "experiment_spec_id",
        "experiment_spec_sha256",
        "experiment_arm_id",
        "target_host_profile_id",
        "phage_profile_ids",
        "source_step",
        "device_id",
        "material_batch_ids",
        "origin",
        "physical_execution",
        "evidence_class",
        "qc_status",
        "qc_evidence",
        "measurement_type",
        "data",
        "recorded_at",
        "created_at",
    }
    if set(data) != required:
        raise ValueError("Measurement has missing or unknown fields.")
    for field in ("phage_profile_ids", "material_batch_ids", "qc_evidence"):
        if not isinstance(data[field], list):
            raise ValueError(f"{field} must be an array.")

    measurement = Measurement(
        schema_version=data["schema_version"],
        measurement_id=data["measurement_id"],
        revision=data["revision"],
        run_id=data["run_id"],
        experiment_spec_id=data["experiment_spec_id"],
        experiment_spec_sha256=data["experiment_spec_sha256"],
        experiment_arm_id=data["experiment_arm_id"],
        target_host_profile_id=data["target_host_profile_id"],
        phage_profile_ids=tuple(data["phage_profile_ids"]),
        source_step=data["source_step"],
        device_id=data["device_id"],
        material_batch_ids=tuple(data["material_batch_ids"]),
        origin=data["origin"],
        physical_execution=data["physical_execution"],
        qc_status=data["qc_status"],
        qc_evidence=tuple(data["qc_evidence"]),
        measurement_type=data["measurement_type"],
        data=data["data"],
        recorded_at=data["recorded_at"],
        created_at=data["created_at"],
    )
    if data["record_id"] != measurement.record_id:
        raise ValueError(
            "record_id does not match measurement_id and revision."
        )
    if data["evidence_class"] != measurement.evidence_class:
        raise ValueError("evidence_class does not match execution provenance.")
    if data["content_sha256"] != measurement.content_sha256:
        raise ValueError(
            "content_sha256 does not match the Measurement content."
        )
    return measurement


def write_measurement(measurement: Measurement, path: Path) -> None:
    if not isinstance(measurement, Measurement):
        raise ValueError("measurement must be a Measurement.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(measurement.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def load_measurement(path: Path) -> Measurement:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"Measurement could not be loaded: {exc}") from None
    return measurement_from_dict(data)

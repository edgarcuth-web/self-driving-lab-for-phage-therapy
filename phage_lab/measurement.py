"""First-class measurement ingestion from completed run reports.

A Measurement preserves device output and run lineage without turning workflow
success into a biological conclusion. Virtual outputs may be stored for control
path testing, but they carry evidence_class='none' and cannot support Phenotype.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path

SCHEMA_VERSION = 1
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
        if self.experiment_spec_id is not None:
            _require_text(self.experiment_spec_id, "experiment_spec_id")
            _validate_digest(
                self.experiment_spec_sha256,
                "experiment_spec_sha256",
            )
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


def measurement_from_run_report(
    report: dict,
    *,
    measurement_id: str,
    source_step: str = "measure",
    measurement_type: str = "device_result",
    qc_status: str = "pending",
    qc_evidence: tuple[str, ...] = (),
    revision: int = 1,
    created_at: str | None = None,
) -> Measurement:
    """Ingest one completed device result without inferring phenotype."""

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
        if (
            result.get("simulated") is True
            or result.get("physical_execution") is False
        ):
            raise ValueError(
                "physical run result contradicts its physical_execution provenance."
            )
    else:
        if mode != "virtual_hardware" or simulated is not True:
            raise ValueError(
                "run report execution_mode/simulated contradicts physical_execution=False."
            )
        if (
            result.get("simulated") is False
            or result.get("physical_execution") is True
        ):
            raise ValueError(
                "virtual run result contradicts its non-physical provenance."
            )
    origin = "physical_run" if physical else "virtual_run"

    spec = report.get("experiment_spec")
    spec_id = None
    spec_sha = None
    if spec is not None:
        if not isinstance(spec, dict):
            raise ValueError("run report experiment_spec must be an object.")
        spec_id = _require_text(spec.get("spec_id"), "experiment_spec spec_id")
        spec_sha = spec.get("content_sha256")
        _validate_digest(spec_sha, "experiment_spec content_sha256")

    batch_ids = report.get("material_batch_ids", [])
    if not isinstance(batch_ids, list):
        raise ValueError("run report material_batch_ids must be an array.")
    recorded_at = report.get("finished_at") or report.get("started_at")
    _validate_timestamp(recorded_at, "run report timestamp")

    return Measurement(
        measurement_id=measurement_id,
        revision=revision,
        run_id=run_id,
        experiment_spec_id=spec_id,
        experiment_spec_sha256=spec_sha,
        source_step=source_step,
        device_id=device_id,
        material_batch_ids=tuple(batch_ids),
        origin=origin,
        physical_execution=physical,
        qc_status=qc_status,
        qc_evidence=qc_evidence,
        measurement_type=measurement_type,
        data=dict(result),
        recorded_at=recorded_at,
        created_at=created_at or utc_now(),
    )


def measurement_from_dict(data: dict) -> Measurement:
    if not isinstance(data, dict):
        raise ValueError("Measurement must be an object.")
    required = {
        "content_sha256",
        "schema_version",
        "record_id",
        "measurement_id",
        "revision",
        "run_id",
        "experiment_spec_id",
        "experiment_spec_sha256",
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
    if not isinstance(data["material_batch_ids"], list):
        raise ValueError("material_batch_ids must be an array.")
    if not isinstance(data["qc_evidence"], list):
        raise ValueError("qc_evidence must be an array.")

    measurement = Measurement(
        schema_version=data["schema_version"],
        measurement_id=data["measurement_id"],
        revision=data["revision"],
        run_id=data["run_id"],
        experiment_spec_id=data["experiment_spec_id"],
        experiment_spec_sha256=data["experiment_spec_sha256"],
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

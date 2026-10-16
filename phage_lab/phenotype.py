"""Arm-aware phenotype interpretation and explicit phenotype comparison.

Phenotype v2 is scoped to one ExperimentArm and can represent both host-only
controls and phage-containing treatment arms. PhenotypeComparison links two
already-admitted arm phenotypes and records an assessor-stated comparison. No
threshold or biological conclusion is inferred automatically.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path

from .experiment_spec import ExperimentSpec
from .measurement import Measurement

SCHEMA_VERSION = 2
COMPARISON_SCHEMA_VERSION = 1
OUTCOMES = ("positive", "negative", "graded")


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


def _validate_scalar(value, field_name: str) -> None:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must not be a boolean.")
    if value is None or isinstance(value, (str, int)):
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    raise ValueError(f"{field_name} must be a finite scalar value or null.")


def _validate_scalar_mapping(value: dict, field_name: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object.")
    for key, item in value.items():
        _require_text(key, f"{field_name} key")
        _validate_scalar(item, field_name)


@dataclass(frozen=True)
class PhenotypeAssessor:
    name: str
    version: str
    parameters: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.name, "assessor name")
        _require_text(self.version, "assessor version")
        _validate_scalar_mapping(self.parameters, "assessor parameters")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "parameters": dict(self.parameters),
        }


@dataclass(frozen=True)
class Phenotype:
    phenotype_id: str
    revision: int
    experiment_spec_id: str
    experiment_spec_sha256: str
    experiment_arm_id: str
    target_host_profile_id: str
    phage_profile_ids: tuple[str, ...]
    material_batch_ids: tuple[str, ...]
    measurement_ids: tuple[str, ...]
    phenotype_type: str
    outcome: str
    value: str | int | float | None
    unit: str | None
    interpretation: str
    assessor: PhenotypeAssessor
    assessed_at: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_text(self.phenotype_id, "phenotype_id")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("revision must be a positive integer.")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"Phenotype schema_version must be {SCHEMA_VERSION}."
            )
        _require_text(self.experiment_spec_id, "experiment_spec_id")
        _validate_digest(
            self.experiment_spec_sha256,
            "experiment_spec_sha256",
        )
        _require_text(self.experiment_arm_id, "experiment_arm_id")
        _require_text(self.target_host_profile_id, "target_host_profile_id")
        _validate_text_tuple(self.phage_profile_ids, "phage_profile_id")
        _validate_text_tuple(self.material_batch_ids, "material_batch_id")
        if not self.material_batch_ids:
            raise ValueError(
                "Phenotype requires material_batch_ids from physical execution."
            )
        _validate_text_tuple(self.measurement_ids, "measurement_id")
        if not self.measurement_ids:
            raise ValueError("Phenotype requires at least one Measurement.")
        _require_text(self.phenotype_type, "phenotype_type")
        if self.outcome not in OUTCOMES:
            raise ValueError(f"outcome must be one of {OUTCOMES}.")
        _validate_scalar(self.value, "value")
        if self.outcome == "graded" and self.value is None:
            raise ValueError("graded phenotype requires a value.")
        if self.unit is not None:
            _require_text(self.unit, "unit")
        _require_text(self.interpretation, "interpretation")
        if not isinstance(self.assessor, PhenotypeAssessor):
            raise ValueError("assessor must be a PhenotypeAssessor.")
        _validate_timestamp(self.assessed_at, "assessed_at")

    @property
    def record_id(self) -> str:
        return f"{self.phenotype_id}:v{self.revision}"

    def _content_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "record_id": self.record_id,
            "phenotype_id": self.phenotype_id,
            "revision": self.revision,
            "experiment_spec_id": self.experiment_spec_id,
            "experiment_spec_sha256": self.experiment_spec_sha256,
            "experiment_arm_id": self.experiment_arm_id,
            "target_host_profile_id": self.target_host_profile_id,
            "phage_profile_ids": list(self.phage_profile_ids),
            "material_batch_ids": list(self.material_batch_ids),
            "measurement_ids": list(self.measurement_ids),
            "phenotype_type": self.phenotype_type,
            "outcome": self.outcome,
            "value": self.value,
            "unit": self.unit,
            "interpretation": self.interpretation,
            "assessor": self.assessor.to_dict(),
            "assessed_at": self.assessed_at,
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


@dataclass(frozen=True)
class PhenotypeComparison:
    comparison_id: str
    revision: int
    experiment_spec_id: str
    experiment_spec_sha256: str
    baseline_arm_id: str
    comparator_arm_id: str
    baseline_phenotype_id: str
    baseline_phenotype_sha256: str
    comparator_phenotype_id: str
    comparator_phenotype_sha256: str
    comparison_type: str
    outcome: str
    value: str | int | float | None
    unit: str | None
    interpretation: str
    assessor: PhenotypeAssessor
    assessed_at: str
    schema_version: int = COMPARISON_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_text(self.comparison_id, "comparison_id")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("revision must be a positive integer.")
        if self.schema_version != COMPARISON_SCHEMA_VERSION:
            raise ValueError(
                "PhenotypeComparison schema_version must be "
                f"{COMPARISON_SCHEMA_VERSION}."
            )
        _require_text(self.experiment_spec_id, "experiment_spec_id")
        _validate_digest(self.experiment_spec_sha256, "experiment_spec_sha256")
        _require_text(self.baseline_arm_id, "baseline_arm_id")
        _require_text(self.comparator_arm_id, "comparator_arm_id")
        if self.baseline_arm_id == self.comparator_arm_id:
            raise ValueError("PhenotypeComparison requires two distinct arms.")
        _require_text(self.baseline_phenotype_id, "baseline_phenotype_id")
        _validate_digest(
            self.baseline_phenotype_sha256,
            "baseline_phenotype_sha256",
        )
        _require_text(self.comparator_phenotype_id, "comparator_phenotype_id")
        _validate_digest(
            self.comparator_phenotype_sha256,
            "comparator_phenotype_sha256",
        )
        _require_text(self.comparison_type, "comparison_type")
        _require_text(self.outcome, "comparison outcome")
        _validate_scalar(self.value, "value")
        if self.unit is not None:
            _require_text(self.unit, "unit")
        _require_text(self.interpretation, "interpretation")
        if not isinstance(self.assessor, PhenotypeAssessor):
            raise ValueError("assessor must be a PhenotypeAssessor.")
        _validate_timestamp(self.assessed_at, "assessed_at")

    @property
    def record_id(self) -> str:
        return f"{self.comparison_id}:v{self.revision}"

    def _content_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "record_id": self.record_id,
            "comparison_id": self.comparison_id,
            "revision": self.revision,
            "experiment_spec_id": self.experiment_spec_id,
            "experiment_spec_sha256": self.experiment_spec_sha256,
            "baseline_arm_id": self.baseline_arm_id,
            "comparator_arm_id": self.comparator_arm_id,
            "baseline_phenotype_id": self.baseline_phenotype_id,
            "baseline_phenotype_sha256": self.baseline_phenotype_sha256,
            "comparator_phenotype_id": self.comparator_phenotype_id,
            "comparator_phenotype_sha256": self.comparator_phenotype_sha256,
            "comparison_type": self.comparison_type,
            "outcome": self.outcome,
            "value": self.value,
            "unit": self.unit,
            "interpretation": self.interpretation,
            "assessor": self.assessor.to_dict(),
            "assessed_at": self.assessed_at,
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


def _arm_by_id(spec: ExperimentSpec, arm_id: str):
    arm_id = _require_text(arm_id, "arm_id")
    matches = [arm for arm in spec.arms if arm.arm_id == arm_id]
    if not matches:
        raise ValueError(f"ExperimentSpec has no arm {arm_id!r}.")
    return matches[0]


def phenotype_from_measurements(
    spec: ExperimentSpec,
    measurements: list[Measurement],
    *,
    arm_id: str,
    phenotype_id: str,
    phenotype_type: str,
    outcome: str,
    interpretation: str,
    assessor_name: str,
    assessor_version: str,
    assessor_parameters: dict | None = None,
    value: str | int | float | None = None,
    unit: str | None = None,
    revision: int = 1,
    assessed_at: str | None = None,
) -> Phenotype:
    """Create one arm-scoped phenotype from admitted physical evidence."""

    if not isinstance(spec, ExperimentSpec):
        raise ValueError("spec must be an ExperimentSpec.")
    if not isinstance(measurements, list) or not measurements:
        raise ValueError("measurements must be a nonempty list.")
    if any(not isinstance(item, Measurement) for item in measurements):
        raise ValueError("measurements must contain Measurement objects.")

    arm = _arm_by_id(spec, arm_id)
    expected_spec_id = spec.spec_id
    expected_spec_sha = spec.content_sha256
    material_sets = set()
    measurement_ids = []
    for measurement in measurements:
        if (
            not measurement.physical_execution
            or measurement.evidence_class != "physical_measurement"
        ):
            raise ValueError(
                "Phenotype cannot be derived from non-physical Measurement."
            )
        if measurement.qc_status != "valid":
            raise ValueError(
                "Phenotype requires every source Measurement to have qc_status='valid'."
            )
        if (
            measurement.experiment_spec_id != expected_spec_id
            or measurement.experiment_spec_sha256 != expected_spec_sha
        ):
            raise ValueError(
                "Measurement does not match the target ExperimentSpec."
            )
        if measurement.experiment_arm_id != arm.arm_id:
            raise ValueError(
                "Phenotype source Measurement does not match the target ExperimentArm."
            )
        if measurement.target_host_profile_id != arm.target_host.profile_id:
            raise ValueError(
                "Measurement host lineage does not match the target ExperimentArm."
            )
        if measurement.phage_profile_ids != arm.phage_profile_ids:
            raise ValueError(
                "Measurement phage lineage does not match the target ExperimentArm."
            )
        if not measurement.material_batch_ids:
            raise ValueError(
                "Phenotype requires physical Measurement with MaterialBatch lineage."
            )
        material_sets.add(measurement.material_batch_ids)
        measurement_ids.append(measurement.record_id)
    if len(material_sets) != 1:
        raise ValueError(
            "Phenotype source Measurements must name the same arm-specific material batch set."
        )

    host_profile_id = arm.target_host.profile_id
    if host_profile_id is None:
        raise ValueError("ExperimentArm target has no HostProfile ID.")

    return Phenotype(
        phenotype_id=phenotype_id,
        revision=revision,
        experiment_spec_id=spec.spec_id,
        experiment_spec_sha256=spec.content_sha256,
        experiment_arm_id=arm.arm_id,
        target_host_profile_id=host_profile_id,
        phage_profile_ids=arm.phage_profile_ids,
        material_batch_ids=next(iter(material_sets)),
        measurement_ids=tuple(measurement_ids),
        phenotype_type=phenotype_type,
        outcome=outcome,
        value=value,
        unit=unit,
        interpretation=interpretation,
        assessor=PhenotypeAssessor(
            name=assessor_name,
            version=assessor_version,
            parameters=assessor_parameters or {},
        ),
        assessed_at=assessed_at or utc_now(),
    )


def phenotype_comparison_from_phenotypes(
    spec: ExperimentSpec,
    baseline: Phenotype,
    comparator: Phenotype,
    *,
    comparison_id: str,
    comparison_type: str,
    outcome: str,
    interpretation: str,
    assessor_name: str,
    assessor_version: str,
    assessor_parameters: dict | None = None,
    value: str | int | float | None = None,
    unit: str | None = None,
    revision: int = 1,
    assessed_at: str | None = None,
) -> PhenotypeComparison:
    """Record an explicit comparison between two admitted arm phenotypes."""

    if not isinstance(spec, ExperimentSpec):
        raise ValueError("spec must be an ExperimentSpec.")
    if not isinstance(baseline, Phenotype) or not isinstance(comparator, Phenotype):
        raise ValueError("baseline and comparator must be Phenotype objects.")
    for phenotype in (baseline, comparator):
        if (
            phenotype.experiment_spec_id != spec.spec_id
            or phenotype.experiment_spec_sha256 != spec.content_sha256
        ):
            raise ValueError(
                "PhenotypeComparison source phenotype does not match ExperimentSpec."
            )
        _arm_by_id(spec, phenotype.experiment_arm_id)
    if baseline.experiment_arm_id == comparator.experiment_arm_id:
        raise ValueError("PhenotypeComparison requires phenotypes from distinct arms.")
    if baseline.phenotype_type != comparator.phenotype_type:
        raise ValueError(
            "PhenotypeComparison requires matching phenotype_type values."
        )

    return PhenotypeComparison(
        comparison_id=comparison_id,
        revision=revision,
        experiment_spec_id=spec.spec_id,
        experiment_spec_sha256=spec.content_sha256,
        baseline_arm_id=baseline.experiment_arm_id,
        comparator_arm_id=comparator.experiment_arm_id,
        baseline_phenotype_id=baseline.record_id,
        baseline_phenotype_sha256=baseline.content_sha256,
        comparator_phenotype_id=comparator.record_id,
        comparator_phenotype_sha256=comparator.content_sha256,
        comparison_type=comparison_type,
        outcome=outcome,
        value=value,
        unit=unit,
        interpretation=interpretation,
        assessor=PhenotypeAssessor(
            name=assessor_name,
            version=assessor_version,
            parameters=assessor_parameters or {},
        ),
        assessed_at=assessed_at or utc_now(),
    )


def _assessor_from_dict(data: dict) -> PhenotypeAssessor:
    if not isinstance(data, dict) or set(data) != {
        "name",
        "version",
        "parameters",
    }:
        raise ValueError("assessor has missing or unknown fields.")
    return PhenotypeAssessor(
        name=data["name"],
        version=data["version"],
        parameters=data["parameters"],
    )


def phenotype_from_dict(data: dict) -> Phenotype:
    if not isinstance(data, dict):
        raise ValueError("Phenotype must be an object.")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            "Phenotype schema_version is not supported; rebuild v1 records as arm-scoped v2."
        )
    required = {
        "content_sha256",
        "schema_version",
        "record_id",
        "phenotype_id",
        "revision",
        "experiment_spec_id",
        "experiment_spec_sha256",
        "experiment_arm_id",
        "target_host_profile_id",
        "phage_profile_ids",
        "material_batch_ids",
        "measurement_ids",
        "phenotype_type",
        "outcome",
        "value",
        "unit",
        "interpretation",
        "assessor",
        "assessed_at",
    }
    if set(data) != required:
        raise ValueError("Phenotype has missing or unknown fields.")
    for field in (
        "phage_profile_ids",
        "material_batch_ids",
        "measurement_ids",
    ):
        if not isinstance(data[field], list):
            raise ValueError(f"{field} must be an array.")

    phenotype = Phenotype(
        schema_version=data["schema_version"],
        phenotype_id=data["phenotype_id"],
        revision=data["revision"],
        experiment_spec_id=data["experiment_spec_id"],
        experiment_spec_sha256=data["experiment_spec_sha256"],
        experiment_arm_id=data["experiment_arm_id"],
        target_host_profile_id=data["target_host_profile_id"],
        phage_profile_ids=tuple(data["phage_profile_ids"]),
        material_batch_ids=tuple(data["material_batch_ids"]),
        measurement_ids=tuple(data["measurement_ids"]),
        phenotype_type=data["phenotype_type"],
        outcome=data["outcome"],
        value=data["value"],
        unit=data["unit"],
        interpretation=data["interpretation"],
        assessor=_assessor_from_dict(data["assessor"]),
        assessed_at=data["assessed_at"],
    )
    if data["record_id"] != phenotype.record_id:
        raise ValueError(
            "record_id does not match phenotype_id and revision."
        )
    if data["content_sha256"] != phenotype.content_sha256:
        raise ValueError(
            "content_sha256 does not match the Phenotype content."
        )
    return phenotype


def phenotype_comparison_from_dict(data: dict) -> PhenotypeComparison:
    if not isinstance(data, dict):
        raise ValueError("PhenotypeComparison must be an object.")
    required = {
        "content_sha256",
        "schema_version",
        "record_id",
        "comparison_id",
        "revision",
        "experiment_spec_id",
        "experiment_spec_sha256",
        "baseline_arm_id",
        "comparator_arm_id",
        "baseline_phenotype_id",
        "baseline_phenotype_sha256",
        "comparator_phenotype_id",
        "comparator_phenotype_sha256",
        "comparison_type",
        "outcome",
        "value",
        "unit",
        "interpretation",
        "assessor",
        "assessed_at",
    }
    if set(data) != required:
        raise ValueError("PhenotypeComparison has missing or unknown fields.")
    comparison = PhenotypeComparison(
        schema_version=data["schema_version"],
        comparison_id=data["comparison_id"],
        revision=data["revision"],
        experiment_spec_id=data["experiment_spec_id"],
        experiment_spec_sha256=data["experiment_spec_sha256"],
        baseline_arm_id=data["baseline_arm_id"],
        comparator_arm_id=data["comparator_arm_id"],
        baseline_phenotype_id=data["baseline_phenotype_id"],
        baseline_phenotype_sha256=data["baseline_phenotype_sha256"],
        comparator_phenotype_id=data["comparator_phenotype_id"],
        comparator_phenotype_sha256=data["comparator_phenotype_sha256"],
        comparison_type=data["comparison_type"],
        outcome=data["outcome"],
        value=data["value"],
        unit=data["unit"],
        interpretation=data["interpretation"],
        assessor=_assessor_from_dict(data["assessor"]),
        assessed_at=data["assessed_at"],
    )
    if data["record_id"] != comparison.record_id:
        raise ValueError("record_id does not match comparison_id and revision.")
    if data["content_sha256"] != comparison.content_sha256:
        raise ValueError(
            "content_sha256 does not match the PhenotypeComparison content."
        )
    return comparison


def write_phenotype(phenotype: Phenotype, path: Path) -> None:
    if not isinstance(phenotype, Phenotype):
        raise ValueError("phenotype must be a Phenotype.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(phenotype.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def load_phenotype(path: Path) -> Phenotype:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"Phenotype could not be loaded: {exc}") from None
    return phenotype_from_dict(data)


def write_phenotype_comparison(
    comparison: PhenotypeComparison,
    path: Path,
) -> None:
    if not isinstance(comparison, PhenotypeComparison):
        raise ValueError("comparison must be a PhenotypeComparison.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(comparison.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def load_phenotype_comparison(path: Path) -> PhenotypeComparison:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError(
            f"PhenotypeComparison could not be loaded: {exc}"
        ) from None
    return phenotype_comparison_from_dict(data)

"""Arm-aware phenotype interpretation and explicit phenotype comparison.

Phenotype v2 is scoped to one ExperimentArm and can represent both host-only
controls and phage-containing treatment arms. PhenotypeComparison links two
already-admitted arm phenotypes and records an assessor-stated comparison. No
threshold or biological conclusion is inferred automatically.
"""

from dataclasses import dataclass, field
from pathlib import Path

from .artifacts import (
    ContentAddressed,
    atomic_write_json,
    parse_timestamp as _validate_timestamp,
    read_json,
    require_text as _require_text,
    require_text_tuple,
    utc_now,
    validate_digest as _validate_digest,
    validate_scalar,
    validate_scalar_mapping,
)

from .experiment_spec import ExperimentSpec, arm_by_id
from .measurement import Measurement

SCHEMA_VERSION = 2
COMPARISON_SCHEMA_VERSION = 1
OUTCOMES = ("positive", "negative", "graded")


@dataclass(frozen=True)
class PhenotypeAssessor:
    name: str
    version: str
    parameters: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.name, "assessor name")
        _require_text(self.version, "assessor version")
        validate_scalar_mapping(self.parameters, "assessor parameters", allow_bool=False)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "parameters": dict(self.parameters),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PhenotypeAssessor":
        if not isinstance(data, dict) or set(data) != {"name", "version", "parameters"}:
            raise ValueError("assessor has missing or unknown fields.")
        return cls(name=data["name"], version=data["version"], parameters=data["parameters"])


@dataclass(frozen=True)
class Phenotype(ContentAddressed):
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
        require_text_tuple(self.phage_profile_ids, "phage_profile_id")
        require_text_tuple(self.material_batch_ids, "material_batch_id")
        if not self.material_batch_ids:
            raise ValueError(
                "Phenotype requires material_batch_ids from physical execution."
            )
        require_text_tuple(self.measurement_ids, "measurement_id")
        if not self.measurement_ids:
            raise ValueError("Phenotype requires at least one Measurement.")
        _require_text(self.phenotype_type, "phenotype_type")
        if self.outcome not in OUTCOMES:
            raise ValueError(f"outcome must be one of {OUTCOMES}.")
        validate_scalar(self.value, "value", allow_bool=False)
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


@dataclass(frozen=True)
class PhenotypeComparison(ContentAddressed):
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
        validate_scalar(self.value, "value", allow_bool=False)
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

    arm = arm_by_id(spec, arm_id)
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
        arm_by_id(spec, phenotype.experiment_arm_id)
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
        assessor=PhenotypeAssessor.from_dict(data["assessor"]),
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
        assessor=PhenotypeAssessor.from_dict(data["assessor"]),
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
    atomic_write_json(phenotype.to_dict(), path)


def load_phenotype(path: Path) -> Phenotype:
    data = read_json(path, 'Phenotype')
    return phenotype_from_dict(data)


def write_phenotype_comparison(
    comparison: PhenotypeComparison,
    path: Path,
) -> None:
    if not isinstance(comparison, PhenotypeComparison):
        raise ValueError("comparison must be a PhenotypeComparison.")
    atomic_write_json(comparison.to_dict(), path)


def load_phenotype_comparison(path: Path) -> PhenotypeComparison:
    data = read_json(path, 'PhenotypeComparison')
    return phenotype_comparison_from_dict(data)

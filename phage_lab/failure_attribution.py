"""Explicit result review, with unconfirmed mechanism hypotheses.

This artifact records an assessor's judgment against a declared criterion. It
does not infer failure from a negative phenotype, identify a causal mechanism,
assign a cocktail result to its individual members, or update a model/HostState.
Source snapshots are re-admitted on construction and load, including physical
measurement QC and exact arm/comparison lineage.
"""

from dataclasses import dataclass, fields
from datetime import datetime, timezone
from pathlib import Path

from .artifacts import (
    ContentAddressed,
    atomic_write_json,
    parse_timestamp as _time,
    read_json,
    require_text as _text,
    require_text_tuple,
)

from .experiment_spec import ExperimentSpec, experiment_spec_from_dict
from .measurement import Measurement, measurement_from_dict
from .phenotype import (
    Phenotype, PhenotypeAssessor, PhenotypeComparison,
    phenotype_from_dict, phenotype_comparison_from_dict,
    phenotype_from_measurements, phenotype_comparison_from_phenotypes,
)

SCHEMA_VERSION = 1
FAILURE_OUTCOMES = ("failure_observed", "failure_not_observed", "inconclusive")
MECHANISM_CATEGORIES = ("adsorption", "intracellular", "kinetics", "other")


def _index(items, kind, name, *, nonempty=False):
    if not isinstance(items, tuple) or (nonempty and not items):
        raise ValueError(f"{name} must be a {'nonempty ' if nonempty else ''}tuple.")
    if any(not isinstance(item, kind) for item in items):
        raise ValueError(f"{name} contains an invalid object.")
    indexed = {item.record_id: item for item in items}
    if len(indexed) != len(items):
        raise ValueError(f"{name} record IDs must be unique.")
    return indexed


@dataclass(frozen=True)
class MechanismHypothesis:
    """Assessor-declared possibility; never a confirmed causal attribution."""

    category: str
    rationale: str
    supporting_phenotype_ids: tuple[str, ...] = ()
    supporting_comparison_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self):
        if self.category not in MECHANISM_CATEGORIES:
            raise ValueError(f"category must be one of {MECHANISM_CATEGORIES}.")
        _text(self.rationale, "hypothesis rationale")
        require_text_tuple(self.supporting_phenotype_ids, "supporting_phenotype_ids")
        require_text_tuple(self.supporting_comparison_ids, "supporting_comparison_ids")
        if not (self.supporting_phenotype_ids or self.supporting_comparison_ids):
            raise ValueError("A hypothesis must reference a reviewed result.")
        require_text_tuple(self.limitations, "hypothesis limitations", nonempty=True)

    def to_dict(self):
        return {
            "category": self.category,
            "rationale": self.rationale,
            "supporting_phenotype_ids": list(self.supporting_phenotype_ids),
            "supporting_comparison_ids": list(self.supporting_comparison_ids),
            "limitations": list(self.limitations),
        }


def mechanism_hypothesis_from_dict(data):
    if not isinstance(data, dict) or set(data) != {
        field.name for field in fields(MechanismHypothesis)
    }:
        raise ValueError("MechanismHypothesis has missing or unknown fields.")
    values = dict(data)
    for name in ("supporting_phenotype_ids", "supporting_comparison_ids", "limitations"):
        if not isinstance(values[name], list):
            raise ValueError(f"{name} must be an array.")
        values[name] = tuple(values[name])
    return MechanismHypothesis(**values)


@dataclass(frozen=True)
class FailureAttribution(ContentAddressed):
    attribution_id: str
    revision: int
    experiment_spec: ExperimentSpec
    target_arm_id: str
    measurements: tuple[Measurement, ...]
    phenotypes: tuple[Phenotype, ...]
    comparisons: tuple[PhenotypeComparison, ...]
    outcome: str
    criterion: str
    interpretation: str
    hypotheses: tuple[MechanismHypothesis, ...]
    assessor: PhenotypeAssessor
    limitations: tuple[str, ...]
    assessed_at: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self):
        _text(self.attribution_id, "attribution_id")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("revision must be a positive integer.")
        if type(self.schema_version) is not int or self.schema_version != SCHEMA_VERSION:
            raise ValueError("Unsupported FailureAttribution schema_version.")
        if not isinstance(self.experiment_spec, ExperimentSpec):
            raise ValueError("experiment_spec must be an ExperimentSpec.")
        _text(self.target_arm_id, "target_arm_id")
        arms = {arm.arm_id: arm for arm in self.experiment_spec.arms}
        target = arms.get(self.target_arm_id)
        if target is None or target.role != "treatment" or not target.phage_profile_ids:
            raise ValueError("target_arm_id must name a phage-containing treatment arm.")
        if self.outcome not in FAILURE_OUTCOMES:
            raise ValueError(f"outcome must be one of {FAILURE_OUTCOMES}.")
        _text(self.criterion, "criterion")
        _text(self.interpretation, "interpretation")
        require_text_tuple(self.limitations, "limitations", nonempty=True)
        if not isinstance(self.assessor, PhenotypeAssessor):
            raise ValueError("assessor must be a PhenotypeAssessor.")
        assessed = _time(self.assessed_at)
        measurements = _index(self.measurements, Measurement, "measurements", nonempty=True)
        phenotypes = _index(self.phenotypes, Phenotype, "phenotypes", nonempty=True)
        comparisons = _index(self.comparisons, PhenotypeComparison, "comparisons")
        used_measurements = set()
        for phenotype in self.phenotypes:
            try:
                sources = [measurements[key] for key in phenotype.measurement_ids]
            except KeyError:
                raise ValueError("Every phenotype source Measurement must be supplied.") from None
            # Re-admit evidence rather than trusting the shape or outcome of a Phenotype.
            rebuilt = phenotype_from_measurements(
                self.experiment_spec, sources, arm_id=phenotype.experiment_arm_id,
                phenotype_id=phenotype.phenotype_id, revision=phenotype.revision,
                phenotype_type=phenotype.phenotype_type, outcome=phenotype.outcome,
                value=phenotype.value, unit=phenotype.unit,
                interpretation=phenotype.interpretation,
                assessor_name=phenotype.assessor.name,
                assessor_version=phenotype.assessor.version,
                assessor_parameters=phenotype.assessor.parameters,
                assessed_at=phenotype.assessed_at,
            )
            if rebuilt.content_sha256 != phenotype.content_sha256:
                raise ValueError("Phenotype lineage does not match its supplied Measurements/spec.")
            phenotype_time = _time(phenotype.assessed_at)
            if not _time(self.experiment_spec.created_at) <= phenotype_time <= assessed:
                raise ValueError("Phenotype assessment must fall between spec creation and attribution.")
            for source in sources:
                if max(_time(source.recorded_at), _time(source.created_at)) > phenotype_time:
                    raise ValueError("Measurement cannot postdate its Phenotype assessment.")
            used_measurements.update(phenotype.measurement_ids)
        if used_measurements != set(measurements):
            raise ValueError("Unreferenced Measurements must not be included.")
        if not any(p.experiment_arm_id == self.target_arm_id for p in self.phenotypes):
            raise ValueError("At least one Phenotype must belong to the target arm.")
        compared_phenotypes = set()
        for comparison in self.comparisons:
            try:
                baseline = phenotypes[comparison.baseline_phenotype_id]
                comparator = phenotypes[comparison.comparator_phenotype_id]
            except KeyError:
                raise ValueError("Comparison source Phenotypes must be supplied.") from None
            if self.target_arm_id not in (baseline.experiment_arm_id, comparator.experiment_arm_id):
                raise ValueError("Every comparison must involve the target arm.")
            rebuilt = phenotype_comparison_from_phenotypes(
                self.experiment_spec, baseline, comparator,
                comparison_id=comparison.comparison_id, revision=comparison.revision,
                comparison_type=comparison.comparison_type, outcome=comparison.outcome,
                value=comparison.value, unit=comparison.unit,
                interpretation=comparison.interpretation,
                assessor_name=comparison.assessor.name,
                assessor_version=comparison.assessor.version,
                assessor_parameters=comparison.assessor.parameters,
                assessed_at=comparison.assessed_at,
            )
            if rebuilt.content_sha256 != comparison.content_sha256:
                raise ValueError("Comparison does not match exact source Phenotypes/spec.")
            source_time = max(_time(baseline.assessed_at), _time(comparator.assessed_at))
            if not source_time <= _time(comparison.assessed_at) <= assessed:
                raise ValueError("Comparison assessment violates result/attribution time order.")
            compared_phenotypes.update((baseline.record_id, comparator.record_id))
        if any(p.experiment_arm_id != self.target_arm_id and p.record_id not in compared_phenotypes
               for p in self.phenotypes):
            raise ValueError("Other-arm Phenotypes require a comparison with the target arm.")
        if not isinstance(self.hypotheses, tuple) or any(
            not isinstance(item, MechanismHypothesis) for item in self.hypotheses
        ):
            raise ValueError("hypotheses must be a tuple of MechanismHypothesis objects.")
        if self.hypotheses and self.outcome != "failure_observed":
            raise ValueError("Failure mechanism hypotheses require failure_observed.")
        if len({h.category for h in self.hypotheses}) != len(self.hypotheses):
            raise ValueError("Hypothesis categories must be unique; combine their rationale.")
        for hypothesis in self.hypotheses:
            if (not set(hypothesis.supporting_phenotype_ids) <= set(phenotypes)
                    or not set(hypothesis.supporting_comparison_ids) <= set(comparisons)):
                raise ValueError("Hypothesis references an unavailable reviewed result.")
            target_support = any(
                phenotypes[key].experiment_arm_id == self.target_arm_id
                for key in hypothesis.supporting_phenotype_ids
            )
            if not target_support and not hypothesis.supporting_comparison_ids:
                raise ValueError("Hypothesis must reference target-arm evidence or a target comparison.")

    @property
    def record_id(self):
        return f"{self.attribution_id}:v{self.revision}"

    @property
    def mechanism_status(self):
        return "hypothesized" if self.hypotheses else "unknown"

    def _content_dict(self):
        return {
            "schema_version": self.schema_version,
            "record_id": self.record_id,
            "attribution_id": self.attribution_id,
            "revision": self.revision,
            "experiment_spec": self.experiment_spec.to_dict(),
            "target_arm_id": self.target_arm_id,
            "measurements": [m.to_dict() for m in self.measurements],
            "phenotypes": [p.to_dict() for p in self.phenotypes],
            "comparisons": [c.to_dict() for c in self.comparisons],
            "outcome": self.outcome,
            "criterion": self.criterion,
            "interpretation": self.interpretation,
            "mechanism_status": self.mechanism_status,
            "hypotheses": [h.to_dict() for h in self.hypotheses],
            "assessor": self.assessor.to_dict(),
            "limitations": list(self.limitations),
            "assessed_at": self.assessed_at,
        }


def failure_attribution_from_results(
    spec, measurements, phenotypes, *, attribution_id, target_arm_id, outcome,
    criterion, interpretation, assessor_name, assessor_version,
    limitations, comparisons=(), hypotheses=(), assessor_parameters=None,
    revision=1, assessed_at=None,
):
    """Record explicit review; no automatic thresholds or mechanism inference."""
    if not isinstance(limitations, (list, tuple)):
        raise ValueError("limitations must be an array or tuple.")
    return FailureAttribution(
        attribution_id=attribution_id, revision=revision,
        experiment_spec=spec, target_arm_id=target_arm_id,
        measurements=tuple(measurements), phenotypes=tuple(phenotypes),
        comparisons=tuple(comparisons), outcome=outcome, criterion=criterion,
        interpretation=interpretation, hypotheses=tuple(hypotheses),
        assessor=PhenotypeAssessor(
            assessor_name, assessor_version,
            assessor_parameters if assessor_parameters is not None else {},
        ),
        limitations=tuple(limitations),
        assessed_at=assessed_at if assessed_at is not None else datetime.now(timezone.utc).isoformat(),
    )


def failure_attribution_from_dict(data):
    required = {field.name for field in fields(FailureAttribution)} | {
        "record_id", "content_sha256", "mechanism_status",
    }
    if not isinstance(data, dict) or set(data) != required:
        raise ValueError("FailureAttribution has missing or unknown fields.")
    values = {field.name: data[field.name] for field in fields(FailureAttribution)}
    values["experiment_spec"] = experiment_spec_from_dict(data["experiment_spec"])
    for name, reader in (
        ("measurements", measurement_from_dict), ("phenotypes", phenotype_from_dict),
        ("comparisons", phenotype_comparison_from_dict),
        ("hypotheses", mechanism_hypothesis_from_dict),
    ):
        if not isinstance(data[name], list):
            raise ValueError(f"{name} must be an array.")
        values[name] = tuple(reader(item) for item in data[name])
    if not isinstance(data["limitations"], list):
        raise ValueError("limitations must be an array.")
    values["limitations"] = tuple(data["limitations"])
    assessor = data["assessor"]
    if not isinstance(assessor, dict) or set(assessor) != {"name", "version", "parameters"}:
        raise ValueError("assessor has missing or unknown fields.")
    values["assessor"] = PhenotypeAssessor(**assessor)
    attribution = FailureAttribution(**values)
    if (data["record_id"] != attribution.record_id
            or data["content_sha256"] != attribution.content_sha256
            or data["mechanism_status"] != attribution.mechanism_status):
        raise ValueError("FailureAttribution identity/hash/mechanism_status mismatch.")
    return attribution


def write_failure_attribution(attribution, path: Path):
    if not isinstance(attribution, FailureAttribution):
        raise ValueError("attribution must be a FailureAttribution.")
    # Also check nested snapshots again in case a caller mutated a nested dict.
    data = attribution.to_dict()
    failure_attribution_from_dict(data)
    atomic_write_json(data, path)


def load_failure_attribution(path: Path):
    data = read_json(path, 'FailureAttribution')
    return failure_attribution_from_dict(data)

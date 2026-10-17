"""Machine-readable experimental intent between science and orchestration.

ExperimentSpec v2 is arm-centric. A spec can be created directly from scientific
intent or derived from an upstream artifact such as CocktailDesign. CocktailDesign
is therefore one possible source, not the ExperimentSpec domain model itself.

The spec freezes arm identity, host, phage membership, conditions, expected
readouts and abstract workflow before device assignment. It deliberately contains
no instrument-specific commands or wet-lab procedure parameters.
"""

from dataclasses import dataclass
import math
from pathlib import Path

from .artifacts import (
    atomic_write_json,
    content_hash,
    parse_timestamp as _validate_timestamp,
    read_json,
    require_text as _require_text,
    utc_now,
    validate_digest as _validate_digest,
    with_content_hash,
)

from .cocktail_design import CocktailDesign
from .interaction_evidence import HostReference

SCHEMA_VERSION = 2
ARM_ROLES = ("control", "treatment")

DEFAULT_EXECUTION_CONSTRAINTS = (
    "Arm identities, phage membership, conditions and expected readouts are locked by ExperimentSpec.",
    "Device assignment may change during recovery, but scientific arm definitions may not.",
    "Workflow completion is not evidence of biological efficacy.",
)


def _validate_text_tuple(
    values: tuple[str, ...],
    field_name: str,
    *,
    nonempty: bool = False,
) -> None:
    if not isinstance(values, tuple):
        raise ValueError(f"{field_name} must be a tuple.")
    if nonempty and not values:
        raise ValueError(f"{field_name} must not be empty.")
    for value in values:
        _require_text(value, field_name)
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} values must be unique.")


def _validate_scalar(value, field_name: str) -> None:
    if value is None or isinstance(value, (str, int, bool)):
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    raise ValueError(f"{field_name} must be a finite scalar value or null.")


def _validate_conditions(value: dict) -> None:
    if not isinstance(value, dict):
        raise ValueError("arm conditions must be an object.")
    for key, item in value.items():
        _require_text(key, "condition key")
        _validate_scalar(item, f"condition {key!r}")


@dataclass(frozen=True)
class DesignReference:
    """Compatibility view of a CocktailDesign source reference."""

    design_id: str
    content_sha256: str

    def __post_init__(self) -> None:
        _require_text(self.design_id, "design_id")
        _validate_digest(self.content_sha256, "content_sha256")

    def to_dict(self) -> dict:
        return {
            "design_id": self.design_id,
            "content_sha256": self.content_sha256,
        }


@dataclass(frozen=True)
class SourceReference:
    """Immutable pointer to any upstream scientific artifact."""

    artifact_type: str
    artifact_id: str
    content_sha256: str

    def __post_init__(self) -> None:
        _require_text(self.artifact_type, "artifact_type")
        _require_text(self.artifact_id, "artifact_id")
        _validate_digest(self.content_sha256, "content_sha256")

    def to_dict(self) -> dict:
        return {
            "artifact_type": self.artifact_type,
            "artifact_id": self.artifact_id,
            "content_sha256": self.content_sha256,
        }


@dataclass(frozen=True)
class ExperimentArm:
    """One scientifically distinct comparison arm.

    Control arms may contain zero phages (for example a host-only control) or
    named comparator phages. Treatment arms require at least one phage.
    """

    arm_id: str
    role: str
    target_host: HostReference
    phage_profile_ids: tuple[str, ...]
    conditions: dict
    expected_readouts: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_text(self.arm_id, "arm_id")
        if self.role not in ARM_ROLES:
            raise ValueError(
                "arm role must be one of " + ", ".join(ARM_ROLES) + "."
            )
        if not isinstance(self.target_host, HostReference):
            raise ValueError("arm target_host must be a HostReference.")
        if self.target_host.profile_id is None:
            raise ValueError("ExperimentArm requires a target HostProfile ID.")
        _validate_text_tuple(self.phage_profile_ids, "arm phage_profile_id")
        if self.role == "treatment" and not self.phage_profile_ids:
            raise ValueError("treatment arm requires at least one phage_profile_id.")
        _validate_conditions(self.conditions)
        _validate_text_tuple(
            self.expected_readouts,
            "expected readout",
            nonempty=True,
        )

    def to_dict(self) -> dict:
        return {
            "arm_id": self.arm_id,
            "role": self.role,
            "target_host": self.target_host.to_dict(),
            "phage_profile_ids": list(self.phage_profile_ids),
            "conditions": dict(self.conditions),
            "expected_readouts": list(self.expected_readouts),
        }


@dataclass(frozen=True)
class ExperimentStep:
    """One abstract orchestration step with no device assignment."""

    name: str
    depends_on: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.name, "step name")
        _validate_text_tuple(self.depends_on, "step dependency")
        if self.name in self.depends_on:
            raise ValueError("a workflow step cannot depend on itself.")

    def to_dict(self) -> dict:
        return {"name": self.name, "depends_on": list(self.depends_on)}


def _validate_steps(steps: tuple[ExperimentStep, ...]) -> None:
    if not isinstance(steps, tuple) or not steps:
        raise ValueError("workflow must contain at least one ExperimentStep.")
    if any(not isinstance(step, ExperimentStep) for step in steps):
        raise ValueError("workflow must contain ExperimentStep objects.")
    names = [step.name for step in steps]
    if len(set(names)) != len(names):
        raise ValueError("workflow step names must be unique.")
    seen = set()
    for step in steps:
        unknown = [dependency for dependency in step.depends_on if dependency not in seen]
        if unknown:
            raise ValueError(
                f"workflow step {step.name!r} depends on a missing or later step: "
                + ", ".join(unknown)
            )
        seen.add(step.name)


def _steps_from_workflow(workflow: dict) -> tuple[ExperimentStep, ...]:
    if not isinstance(workflow, dict) or not workflow:
        raise ValueError("workflow must be a nonempty operation/dependency mapping.")
    steps = []
    for name, dependencies in workflow.items():
        if not isinstance(dependencies, (list, tuple)):
            raise ValueError("workflow dependencies must be lists or tuples.")
        steps.append(ExperimentStep(name=name, depends_on=tuple(dependencies)))
    return tuple(steps)


@dataclass(frozen=True)
class ExperimentSpec:
    """Versioned, arm-aware experimental intent."""

    experiment_id: str
    revision: int
    arms: tuple[ExperimentArm, ...]
    workflow: tuple[ExperimentStep, ...]
    objective: str
    scientific_questions: tuple[str, ...]
    execution_constraints: tuple[str, ...]
    source_references: tuple[SourceReference, ...]
    created_at: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_text(self.experiment_id, "experiment_id")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("revision must be a positive integer.")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"ExperimentSpec schema_version must be {SCHEMA_VERSION}."
            )
        if not isinstance(self.arms, tuple) or not self.arms:
            raise ValueError("ExperimentSpec requires at least one ExperimentArm.")
        if any(not isinstance(arm, ExperimentArm) for arm in self.arms):
            raise ValueError("arms must contain ExperimentArm objects.")
        arm_ids = [arm.arm_id for arm in self.arms]
        if len(set(arm_ids)) != len(arm_ids):
            raise ValueError("ExperimentSpec arm IDs must be unique.")

        host_keys = {
            (arm.target_host.genome_sha256, arm.target_host.profile_id)
            for arm in self.arms
        }
        if len(host_keys) != 1:
            raise ValueError(
                "ExperimentSpec v2 requires all arms to share one target host; "
                "split multi-host experiments into separate specs."
            )

        _validate_steps(self.workflow)
        _require_text(self.objective, "objective")
        _validate_text_tuple(
            self.scientific_questions,
            "scientific question",
            nonempty=True,
        )
        _validate_text_tuple(
            self.execution_constraints,
            "execution constraint",
            nonempty=True,
        )
        if not isinstance(self.source_references, tuple):
            raise ValueError("source_references must be a tuple.")
        if any(
            not isinstance(reference, SourceReference)
            for reference in self.source_references
        ):
            raise ValueError("source_references must contain SourceReference objects.")
        source_keys = [
            (reference.artifact_type, reference.artifact_id)
            for reference in self.source_references
        ]
        if len(set(source_keys)) != len(source_keys):
            raise ValueError("source_references must be unique by type and ID.")
        _validate_timestamp(self.created_at, "created_at")

    @property
    def spec_id(self) -> str:
        return f"{self.experiment_id}:v{self.revision}"

    @property
    def target_host(self) -> HostReference:
        """Compatibility view for the common v2 host."""
        return self.arms[0].target_host

    @property
    def member_phage_profile_ids(self) -> tuple[str, ...]:
        """Compatibility view: unique phages across all arms in arm order."""
        seen = set()
        ordered = []
        for arm in self.arms:
            for profile_id in arm.phage_profile_ids:
                if profile_id not in seen:
                    seen.add(profile_id)
                    ordered.append(profile_id)
        return tuple(ordered)

    @property
    def source_design(self) -> DesignReference | None:
        """Compatibility view for specs derived from exactly one CocktailDesign."""
        matches = [
            reference
            for reference in self.source_references
            if reference.artifact_type == "CocktailDesign"
        ]
        if len(matches) != 1:
            return None
        reference = matches[0]
        return DesignReference(
            design_id=reference.artifact_id,
            content_sha256=reference.content_sha256,
        )

    @property
    def purpose(self) -> str:
        """Compatibility alias for ExperimentSpec v1 callers."""
        return self.objective

    def workflow_dict(self) -> dict:
        return {step.name: step.depends_on for step in self.workflow}

    def _content_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "spec_id": self.spec_id,
            "experiment_id": self.experiment_id,
            "revision": self.revision,
            "source_references": [
                reference.to_dict() for reference in self.source_references
            ],
            "arms": [arm.to_dict() for arm in self.arms],
            "workflow": [step.to_dict() for step in self.workflow],
            "objective": self.objective,
            "scientific_questions": list(self.scientific_questions),
            "execution_constraints": list(self.execution_constraints),
            "created_at": self.created_at,
        }

    @property
    def content_sha256(self) -> str:
        return content_hash(self._content_dict())

    def to_dict(self) -> dict:
        return with_content_hash(self._content_dict())


def _host_reference_from_dict(data: dict) -> HostReference:
    if not isinstance(data, dict):
        raise ValueError("target_host must be an object.")
    allowed = {"genome_sha256", "profile_id"}
    if set(data) - allowed:
        raise ValueError("target_host contains unknown fields.")
    return HostReference(
        genome_sha256=data.get("genome_sha256"),
        profile_id=data.get("profile_id"),
    )


def source_reference_from_dict(data: dict) -> SourceReference:
    if not isinstance(data, dict) or set(data) != {
        "artifact_type",
        "artifact_id",
        "content_sha256",
    }:
        raise ValueError("source reference has missing or unknown fields.")
    return SourceReference(
        artifact_type=data["artifact_type"],
        artifact_id=data["artifact_id"],
        content_sha256=data["content_sha256"],
    )


def experiment_arm_from_dict(data: dict) -> ExperimentArm:
    if not isinstance(data, dict):
        raise ValueError("ExperimentArm must be an object.")
    required = {
        "arm_id",
        "role",
        "target_host",
        "phage_profile_ids",
        "conditions",
        "expected_readouts",
    }
    if set(data) != required:
        raise ValueError("ExperimentArm has missing or unknown fields.")
    for field in ("phage_profile_ids", "expected_readouts"):
        if not isinstance(data[field], list):
            raise ValueError(f"ExperimentArm {field} must be an array.")
    return ExperimentArm(
        arm_id=data["arm_id"],
        role=data["role"],
        target_host=_host_reference_from_dict(data["target_host"]),
        phage_profile_ids=tuple(data["phage_profile_ids"]),
        conditions=data["conditions"],
        expected_readouts=tuple(data["expected_readouts"]),
    )


def _step_from_dict(data: dict) -> ExperimentStep:
    if not isinstance(data, dict) or set(data) != {"name", "depends_on"}:
        raise ValueError("workflow step has missing or unknown fields.")
    dependencies = data["depends_on"]
    if not isinstance(dependencies, list):
        raise ValueError("workflow step depends_on must be an array.")
    return ExperimentStep(name=data["name"], depends_on=tuple(dependencies))


def experiment_spec_from_dict(data: dict) -> ExperimentSpec:
    """Validate and reconstruct a serialized ExperimentSpec v2."""

    if not isinstance(data, dict):
        raise ValueError("ExperimentSpec must be an object.")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            "ExperimentSpec schema_version is not supported; regenerate v1 specs as v2."
        )
    required = {
        "content_sha256",
        "schema_version",
        "spec_id",
        "experiment_id",
        "revision",
        "source_references",
        "arms",
        "workflow",
        "objective",
        "scientific_questions",
        "execution_constraints",
        "created_at",
    }
    if set(data) != required:
        raise ValueError("ExperimentSpec has missing or unknown fields.")
    for field in (
        "source_references",
        "arms",
        "workflow",
        "scientific_questions",
        "execution_constraints",
    ):
        if not isinstance(data[field], list):
            raise ValueError(f"{field} must be an array.")

    spec = ExperimentSpec(
        schema_version=data["schema_version"],
        experiment_id=data["experiment_id"],
        revision=data["revision"],
        source_references=tuple(
            source_reference_from_dict(item)
            for item in data["source_references"]
        ),
        arms=tuple(experiment_arm_from_dict(item) for item in data["arms"]),
        workflow=tuple(_step_from_dict(item) for item in data["workflow"]),
        objective=data["objective"],
        scientific_questions=tuple(data["scientific_questions"]),
        execution_constraints=tuple(data["execution_constraints"]),
        created_at=data["created_at"],
    )
    if data["spec_id"] != spec.spec_id:
        raise ValueError("spec_id does not match experiment_id and revision.")
    if data["content_sha256"] != spec.content_sha256:
        raise ValueError("content_sha256 does not match the ExperimentSpec content.")
    return spec


def experiment_spec_from_arms(
    arms: tuple[ExperimentArm, ...] | list[ExperimentArm],
    *,
    experiment_id: str,
    workflow: dict,
    objective: str,
    scientific_questions: tuple[str, ...] | None = None,
    execution_constraints: tuple[str, ...] | None = None,
    source_references: tuple[SourceReference, ...] = (),
    revision: int = 1,
    created_at: str | None = None,
) -> ExperimentSpec:
    """Create a generic ExperimentSpec without requiring CocktailDesign."""

    if not isinstance(arms, (list, tuple)):
        raise ValueError("arms must be a list or tuple of ExperimentArm objects.")
    frozen_arms = tuple(arms)
    return ExperimentSpec(
        experiment_id=experiment_id,
        revision=revision,
        arms=frozen_arms,
        workflow=_steps_from_workflow(workflow),
        objective=objective,
        scientific_questions=(
            scientific_questions
            if scientific_questions is not None
            else (_require_text(objective, "objective"),)
        ),
        execution_constraints=(
            execution_constraints
            if execution_constraints is not None
            else DEFAULT_EXECUTION_CONSTRAINTS
        ),
        source_references=tuple(source_references),
        created_at=created_at or utc_now(),
    )


def experiment_spec_from_cocktail(
    design: CocktailDesign,
    *,
    experiment_id: str,
    workflow: dict,
    purpose: str | None = None,
    expected_readouts: tuple[str, ...] = ("biological_phenotype",),
    include_host_control: bool = True,
    revision: int = 1,
    created_at: str | None = None,
) -> ExperimentSpec:
    """Create an arm-aware ExperimentSpec from one CocktailDesign.

    CocktailDesign is captured as provenance. The resulting ExperimentSpec is
    otherwise a generic arm-based artifact and can coexist with specs created
    directly from single-phage or other scientific intents.
    """

    if not isinstance(design, CocktailDesign):
        raise ValueError("design must be a CocktailDesign.")
    _validate_text_tuple(
        expected_readouts,
        "expected readout",
        nonempty=True,
    )

    members = tuple(member.phage_profile_id for member in design.members)
    arms = []
    if include_host_control:
        arms.append(
            ExperimentArm(
                arm_id="host-control",
                role="control",
                target_host=design.target_host,
                phage_profile_ids=(),
                conditions={},
                expected_readouts=expected_readouts,
            )
        )
    arms.append(
        ExperimentArm(
            arm_id="cocktail-treatment",
            role="treatment",
            target_host=design.target_host,
            phage_profile_ids=members,
            conditions={},
            expected_readouts=expected_readouts,
        )
    )

    objective_names = ", ".join(objective.name for objective in design.objectives)
    return experiment_spec_from_arms(
        tuple(arms),
        experiment_id=experiment_id,
        workflow=workflow,
        objective=purpose
        or (
            "Evaluate the locked CocktailDesign in explicit experimental arm(s) "
            "without changing its member set."
        ),
        scientific_questions=(
            f"Generate interpretable experimental outputs for design objective(s): {objective_names}.",
        ),
        execution_constraints=(
            "Cocktail membership in the treatment arm is locked by the source CocktailDesign.",
            "Arm identities, conditions and expected readouts may not be changed by orchestration.",
            "Device assignment may change during recovery, but scientific arm definitions may not.",
            "Workflow completion is not evidence of biological efficacy.",
        ),
        source_references=(
            SourceReference(
                artifact_type="CocktailDesign",
                artifact_id=design.design_id,
                content_sha256=design.content_sha256,
            ),
        ),
        revision=revision,
        created_at=created_at,
    )


def candidate_profile_id(candidate: dict) -> str:
    if not isinstance(candidate, dict):
        raise ValueError("candidate must be an object.")
    explicit = candidate.get("phage_profile_id")
    if explicit is not None:
        return _require_text(explicit, "candidate phage_profile_id")
    identifier = _require_text(candidate.get("id"), "candidate id")
    return f"{identifier}:v1"


def bind_candidates_to_spec(
    spec: ExperimentSpec,
    candidates: list[dict],
) -> list[dict]:
    """Resolve exact candidate records for the unique phages named by all arms."""

    if not isinstance(spec, ExperimentSpec):
        raise ValueError("spec must be an ExperimentSpec.")
    if not isinstance(candidates, list):
        raise ValueError("candidates must be an array.")

    by_profile: dict[str, list[dict]] = {}
    for candidate in candidates:
        profile_id = candidate_profile_id(candidate)
        by_profile.setdefault(profile_id, []).append(candidate)

    bound = []
    for profile_id in spec.member_phage_profile_ids:
        matches = by_profile.get(profile_id, [])
        if not matches:
            raise ValueError(
                f"ExperimentSpec member {profile_id!r} has no candidate record."
            )
        if len(matches) > 1:
            raise ValueError(
                f"ExperimentSpec member {profile_id!r} maps to multiple candidate records."
            )
        bound.append(matches[0])
    return bound


def write_experiment_spec(spec: ExperimentSpec, path: Path) -> None:
    """Atomically write one ExperimentSpec JSON document."""

    if not isinstance(spec, ExperimentSpec):
        raise ValueError("spec must be an ExperimentSpec.")
    atomic_write_json(spec.to_dict(), path)


def load_experiment_spec(path: Path) -> ExperimentSpec:
    """Load and validate one ExperimentSpec JSON document."""

    data = read_json(path, 'ExperimentSpec')
    return experiment_spec_from_dict(data)

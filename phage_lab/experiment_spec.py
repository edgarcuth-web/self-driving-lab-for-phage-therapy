"""Machine-readable experimental intent bound to a scientific design.

ExperimentSpec is the boundary between scientific choice and orchestration.
It freezes the target host, CocktailDesign identity, member PhageProfiles and
high-level workflow before any device is assigned. It deliberately contains no
instrument-specific commands or wet-lab procedure parameters.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from .cocktail_design import CocktailDesign
from .interaction_evidence import HostReference

SCHEMA_VERSION = 1


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


def _validate_text_tuple(values: tuple[str, ...], field_name: str, *, nonempty=False) -> None:
    if not isinstance(values, tuple):
        raise ValueError(f"{field_name} must be a tuple.")
    if nonempty and not values:
        raise ValueError(f"{field_name} must not be empty.")
    for value in values:
        _require_text(value, field_name)
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} values must be unique.")


@dataclass(frozen=True)
class DesignReference:
    """Immutable pointer to the exact CocktailDesign used to create a spec."""

    design_id: str
    content_sha256: str

    def __post_init__(self) -> None:
        _require_text(self.design_id, "design_id")
        if (
            not isinstance(self.content_sha256, str)
            or len(self.content_sha256) != 64
            or any(char not in "0123456789abcdef" for char in self.content_sha256)
        ):
            raise ValueError("content_sha256 must be a SHA-256 digest.")

    def to_dict(self) -> dict:
        return {
            "design_id": self.design_id,
            "content_sha256": self.content_sha256,
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


@dataclass(frozen=True)
class ExperimentSpec:
    """Versioned experimental intent derived from one CocktailDesign."""

    experiment_id: str
    revision: int
    source_design: DesignReference
    target_host: HostReference
    member_phage_profile_ids: tuple[str, ...]
    workflow: tuple[ExperimentStep, ...]
    purpose: str
    scientific_questions: tuple[str, ...]
    execution_constraints: tuple[str, ...]
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
        if not isinstance(self.source_design, DesignReference):
            raise ValueError("source_design must be a DesignReference.")
        if not isinstance(self.target_host, HostReference):
            raise ValueError("target_host must be a HostReference.")
        if self.target_host.profile_id is None:
            raise ValueError("ExperimentSpec requires a target HostProfile ID.")
        _validate_text_tuple(
            self.member_phage_profile_ids,
            "member_phage_profile_id",
            nonempty=True,
        )
        if len(self.member_phage_profile_ids) < 2:
            raise ValueError("ExperimentSpec requires at least two cocktail members.")
        _validate_steps(self.workflow)
        _require_text(self.purpose, "purpose")
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
        _validate_timestamp(self.created_at, "created_at")

    @property
    def spec_id(self) -> str:
        return f"{self.experiment_id}:v{self.revision}"

    def workflow_dict(self) -> dict:
        return {step.name: step.depends_on for step in self.workflow}

    def _content_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "spec_id": self.spec_id,
            "experiment_id": self.experiment_id,
            "revision": self.revision,
            "source_design": self.source_design.to_dict(),
            "target_host": self.target_host.to_dict(),
            "member_phage_profile_ids": list(self.member_phage_profile_ids),
            "workflow": [step.to_dict() for step in self.workflow],
            "purpose": self.purpose,
            "scientific_questions": list(self.scientific_questions),
            "execution_constraints": list(self.execution_constraints),
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


def _design_reference_from_dict(data: dict) -> DesignReference:
    if not isinstance(data, dict) or set(data) != {"design_id", "content_sha256"}:
        raise ValueError("source_design has missing or unknown fields.")
    return DesignReference(
        design_id=data["design_id"],
        content_sha256=data["content_sha256"],
    )


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


def _step_from_dict(data: dict) -> ExperimentStep:
    if not isinstance(data, dict) or set(data) != {"name", "depends_on"}:
        raise ValueError("workflow step has missing or unknown fields.")
    dependencies = data["depends_on"]
    if not isinstance(dependencies, list):
        raise ValueError("workflow step depends_on must be an array.")
    return ExperimentStep(name=data["name"], depends_on=tuple(dependencies))


def experiment_spec_from_dict(data: dict) -> ExperimentSpec:
    """Validate and reconstruct a serialized ExperimentSpec."""

    if not isinstance(data, dict):
        raise ValueError("ExperimentSpec must be an object.")
    required = {
        "content_sha256",
        "schema_version",
        "spec_id",
        "experiment_id",
        "revision",
        "source_design",
        "target_host",
        "member_phage_profile_ids",
        "workflow",
        "purpose",
        "scientific_questions",
        "execution_constraints",
        "created_at",
    }
    if set(data) != required:
        raise ValueError("ExperimentSpec has missing or unknown fields.")
    for field in (
        "member_phage_profile_ids",
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
        source_design=_design_reference_from_dict(data["source_design"]),
        target_host=_host_reference_from_dict(data["target_host"]),
        member_phage_profile_ids=tuple(data["member_phage_profile_ids"]),
        workflow=tuple(_step_from_dict(item) for item in data["workflow"]),
        purpose=data["purpose"],
        scientific_questions=tuple(data["scientific_questions"]),
        execution_constraints=tuple(data["execution_constraints"]),
        created_at=data["created_at"],
    )
    if data["spec_id"] != spec.spec_id:
        raise ValueError("spec_id does not match experiment_id and revision.")
    if data["content_sha256"] != spec.content_sha256:
        raise ValueError("content_sha256 does not match the ExperimentSpec content.")
    return spec


def experiment_spec_from_cocktail(
    design: CocktailDesign,
    *,
    experiment_id: str,
    workflow: dict,
    purpose: str | None = None,
    revision: int = 1,
    created_at: str | None = None,
) -> ExperimentSpec:
    """Freeze a CocktailDesign into an orchestration-neutral ExperimentSpec."""

    if not isinstance(design, CocktailDesign):
        raise ValueError("design must be a CocktailDesign.")
    if not isinstance(workflow, dict) or not workflow:
        raise ValueError("workflow must be a nonempty operation/dependency mapping.")

    steps = []
    for name, dependencies in workflow.items():
        if not isinstance(dependencies, (list, tuple)):
            raise ValueError("workflow dependencies must be lists or tuples.")
        steps.append(ExperimentStep(name=name, depends_on=tuple(dependencies)))

    objective_names = ", ".join(objective.name for objective in design.objectives)
    return ExperimentSpec(
        experiment_id=experiment_id,
        revision=revision,
        source_design=DesignReference(
            design_id=design.design_id,
            content_sha256=design.content_sha256,
        ),
        target_host=design.target_host,
        member_phage_profile_ids=tuple(
            member.phage_profile_id for member in design.members
        ),
        workflow=tuple(steps),
        purpose=purpose
        or (
            "Execute the locked CocktailDesign for experimental evaluation "
            "without changing its member set."
        ),
        scientific_questions=(
            f"Generate interpretable experimental outputs for design objective(s): {objective_names}.",
        ),
        execution_constraints=(
            "Cocktail membership is locked by the source CocktailDesign and may not be changed by orchestration.",
            "Device assignment may change during recovery, but scientific membership may not.",
            "Workflow completion is not evidence of biological efficacy.",
        ),
        created_at=created_at or utc_now(),
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
    """Resolve the exact candidate records named by an ExperimentSpec.

    Extra discovery candidates are ignored. Missing or duplicate records for a
    locked member are rejected. Returned records follow the spec member order.
    """

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
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(spec.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def load_experiment_spec(path: Path) -> ExperimentSpec:
    """Load and validate one ExperimentSpec JSON document."""

    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"ExperimentSpec could not be loaded: {exc}") from None
    return experiment_spec_from_dict(data)

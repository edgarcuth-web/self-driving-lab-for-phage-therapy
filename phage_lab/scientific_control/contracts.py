"""Immutable scientific-control artifacts for planning and review.

These contracts sit above scientific domain modules and below any future
language-model interface. They do not describe device execution.
"""

from dataclasses import dataclass

from ..artifacts import (
    content_hash,
    parse_timestamp,
    require_text,
    validate_digest,
    with_content_hash,
)
from ..host_state import HostStateReference


SCHEMA_VERSION = 1
OBJECTIVE_KINDS = ("prioritize_natural_phages",)
EVIDENCE_STATES = ("predicted", "mixed", "exploration_only", "empty")
REVIEW_DECISIONS = ("approved", "revision_required", "abstained")
FINDING_SEVERITIES = ("info", "warning", "error")


def _text_tuple(values: tuple[str, ...], field_name: str, *, nonempty: bool = False) -> None:
    if not isinstance(values, tuple):
        raise ValueError(f"{field_name} must be a tuple.")
    if nonempty and not values:
        raise ValueError(f"{field_name} must not be empty.")
    for value in values:
        require_text(value, field_name)
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} values must be unique.")


@dataclass(frozen=True)
class ArtifactReference:
    """Exact immutable reference to one upstream scientific artifact."""

    artifact_type: str
    artifact_id: str
    content_sha256: str

    def __post_init__(self) -> None:
        require_text(self.artifact_type, "artifact_type")
        require_text(self.artifact_id, "artifact_id")
        validate_digest(self.content_sha256, "content_sha256")

    def to_dict(self) -> dict:
        return {
            "artifact_type": self.artifact_type,
            "artifact_id": self.artifact_id,
            "content_sha256": self.content_sha256,
        }


@dataclass(frozen=True)
class ScientificObjective:
    """One bounded scientific intent, before any experiment execution."""

    objective_id: str
    revision: int
    kind: str
    statement: str
    host_state: HostStateReference
    created_at: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_text(self.objective_id, "objective_id")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("revision must be a positive integer.")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("Unsupported ScientificObjective schema_version.")
        if self.kind not in OBJECTIVE_KINDS:
            raise ValueError("Unsupported scientific objective kind.")
        require_text(self.statement, "statement")
        if not isinstance(self.host_state, HostStateReference):
            raise ValueError("host_state must be a HostStateReference.")
        parse_timestamp(self.created_at, "created_at")

    @property
    def record_id(self) -> str:
        return f"{self.objective_id}:v{self.revision}"

    def _content_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "record_id": self.record_id,
            "objective_id": self.objective_id,
            "revision": self.revision,
            "kind": self.kind,
            "statement": self.statement,
            "host_state": self.host_state.to_dict(),
            "created_at": self.created_at,
        }

    @property
    def content_sha256(self) -> str:
        return content_hash(self._content_dict())

    def to_dict(self) -> dict:
        return with_content_hash(self._content_dict())


@dataclass(frozen=True)
class ScientificClaim:
    """Typed claim proposed by scientific control.

    The reviewer, not this data class, decides whether a claim type is supported
    by the cited evidence. Keeping the type explicit prevents prose from silently
    upgrading screening evidence into efficacy.
    """

    kind: str
    statement: str

    def __post_init__(self) -> None:
        require_text(self.kind, "claim kind")
        require_text(self.statement, "claim statement")

    def to_dict(self) -> dict:
        return {"kind": self.kind, "statement": self.statement}


@dataclass(frozen=True)
class ModuleInvocation:
    """Trace of one explicitly trusted scientific-module call."""

    module_id: str
    module_version: str
    inputs: tuple[ArtifactReference, ...]
    output: ArtifactReference

    def __post_init__(self) -> None:
        require_text(self.module_id, "module_id")
        require_text(self.module_version, "module_version")
        if (
            not isinstance(self.inputs, tuple)
            or any(not isinstance(item, ArtifactReference) for item in self.inputs)
        ):
            raise ValueError("inputs must contain ArtifactReference objects.")
        if not isinstance(self.output, ArtifactReference):
            raise ValueError("output must be an ArtifactReference.")
        keys = [
            (item.artifact_type, item.artifact_id, item.content_sha256)
            for item in self.inputs
        ]
        if len(set(keys)) != len(keys):
            raise ValueError("module input references must be unique.")

    def to_dict(self) -> dict:
        return {
            "module_id": self.module_id,
            "module_version": self.module_version,
            "inputs": [item.to_dict() for item in self.inputs],
            "output": self.output.to_dict(),
        }


@dataclass(frozen=True)
class ScientificProposal:
    """Content-addressed proposal produced from trusted scientific outputs."""

    proposal_id: str
    revision: int
    objective: ArtifactReference
    invocation: ModuleInvocation
    candidate_set: ArtifactReference
    selected_phage_profile_ids: tuple[str, ...]
    evidence_state: str
    claim: ScientificClaim
    limitations: tuple[str, ...]
    created_at: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_text(self.proposal_id, "proposal_id")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("revision must be a positive integer.")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("Unsupported ScientificProposal schema_version.")
        if not isinstance(self.objective, ArtifactReference):
            raise ValueError("objective must be an ArtifactReference.")
        if self.objective.artifact_type != "ScientificObjective":
            raise ValueError("objective must reference ScientificObjective.")
        if not isinstance(self.invocation, ModuleInvocation):
            raise ValueError("invocation must be a ModuleInvocation.")
        if not isinstance(self.candidate_set, ArtifactReference):
            raise ValueError("candidate_set must be an ArtifactReference.")
        if self.candidate_set.artifact_type != "CandidateSet":
            raise ValueError("candidate_set must reference CandidateSet.")
        if self.invocation.output != self.candidate_set:
            raise ValueError("module output must be the proposal CandidateSet.")
        _text_tuple(self.selected_phage_profile_ids, "selected phage_profile_id")
        if self.evidence_state not in EVIDENCE_STATES:
            raise ValueError("Unsupported evidence_state.")
        if not isinstance(self.claim, ScientificClaim):
            raise ValueError("claim must be a ScientificClaim.")
        _text_tuple(self.limitations, "limitation", nonempty=True)
        parse_timestamp(self.created_at, "created_at")

    @property
    def record_id(self) -> str:
        return f"{self.proposal_id}:v{self.revision}"

    def _content_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "record_id": self.record_id,
            "proposal_id": self.proposal_id,
            "revision": self.revision,
            "objective": self.objective.to_dict(),
            "invocation": self.invocation.to_dict(),
            "candidate_set": self.candidate_set.to_dict(),
            "selected_phage_profile_ids": list(self.selected_phage_profile_ids),
            "evidence_state": self.evidence_state,
            "claim": self.claim.to_dict(),
            "limitations": list(self.limitations),
            "created_at": self.created_at,
        }

    @property
    def content_sha256(self) -> str:
        return content_hash(self._content_dict())

    def to_dict(self) -> dict:
        return with_content_hash(self._content_dict())


@dataclass(frozen=True)
class ReviewFinding:
    code: str
    severity: str
    message: str

    def __post_init__(self) -> None:
        require_text(self.code, "finding code")
        if self.severity not in FINDING_SEVERITIES:
            raise ValueError("Unsupported review finding severity.")
        require_text(self.message, "finding message")

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
        }


@dataclass(frozen=True)
class ScientificReview:
    """Immutable reviewer decision about a specific proposal revision."""

    review_id: str
    revision: int
    proposal: ArtifactReference
    decision: str
    findings: tuple[ReviewFinding, ...]
    reviewed_at: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_text(self.review_id, "review_id")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("revision must be a positive integer.")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("Unsupported ScientificReview schema_version.")
        if not isinstance(self.proposal, ArtifactReference):
            raise ValueError("proposal must be an ArtifactReference.")
        if self.proposal.artifact_type != "ScientificProposal":
            raise ValueError("proposal must reference ScientificProposal.")
        if self.decision not in REVIEW_DECISIONS:
            raise ValueError("Unsupported scientific review decision.")
        if (
            not isinstance(self.findings, tuple)
            or any(not isinstance(item, ReviewFinding) for item in self.findings)
        ):
            raise ValueError("findings must contain ReviewFinding objects.")
        parse_timestamp(self.reviewed_at, "reviewed_at")

    @property
    def record_id(self) -> str:
        return f"{self.review_id}:v{self.revision}"

    def _content_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "record_id": self.record_id,
            "review_id": self.review_id,
            "revision": self.revision,
            "proposal": self.proposal.to_dict(),
            "decision": self.decision,
            "findings": [item.to_dict() for item in self.findings],
            "reviewed_at": self.reviewed_at,
        }

    @property
    def content_sha256(self) -> str:
        return content_hash(self._content_dict())

    def to_dict(self) -> dict:
        return with_content_hash(self._content_dict())

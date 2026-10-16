"""Immutable time-indexed host-state snapshots.

HostProfile anchors stable host identity and characterization. HostState H(t)
captures only explicitly admitted, time-dependent state at a particular as_of
time. Missing components mean unknown, not negative. A later snapshot references
an earlier snapshot but never inherits or overwrites its components implicitly.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path

from .host_profile import HostProfile

SCHEMA_VERSION = 1
STATE_DOMAINS = (
    "receptor_state",
    "surface_state",
    "defense_state",
    "physiology",
    "antimicrobial_state",
    "phage_exposure",
    "phenotype_history",
    "environment",
)
COMPONENT_BASES = ("observed", "derived", "declared")
EVIDENCE_KINDS = (
    "analysis",
    "measurement",
    "phenotype",
    "phenotype_comparison",
    "host_profile",
    "external_observation",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a nonempty string.")
    return value.strip()


def _parse_timestamp(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp.") from None
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone.")
    return parsed


def _validate_digest(value: str, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ValueError(f"{field_name} must be a SHA-256 digest.")


def _validate_scalar(value, field_name: str) -> None:
    if isinstance(value, (str, int, bool)):
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    raise ValueError(
        f"{field_name} must be a finite JSON scalar; use omission for unknown state."
    )


def _validate_scalar_mapping(value: dict, field_name: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object.")
    for key, item in value.items():
        _require_text(key, f"{field_name} key")
        if item is not None:
            _validate_scalar(item, field_name)


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


@dataclass(frozen=True)
class HostStateEvidence:
    """One provenance pointer admitted into a HostState snapshot."""

    evidence_id: str
    host_profile_id: str
    kind: str
    reference_id: str
    observed_at: str
    relation: str
    reference_sha256: str | None = None
    details: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.evidence_id, "evidence_id")
        _require_text(self.host_profile_id, "host_profile_id")
        if self.kind not in EVIDENCE_KINDS:
            raise ValueError(
                "evidence kind must be one of " + ", ".join(EVIDENCE_KINDS) + "."
            )
        _require_text(self.reference_id, "reference_id")
        _parse_timestamp(self.observed_at, "observed_at")
        _require_text(self.relation, "relation")
        if self.reference_sha256 is not None:
            _validate_digest(self.reference_sha256, "reference_sha256")
        _validate_scalar_mapping(self.details, "evidence details")

    def to_dict(self) -> dict:
        return {
            "evidence_id": self.evidence_id,
            "host_profile_id": self.host_profile_id,
            "kind": self.kind,
            "reference_id": self.reference_id,
            "reference_sha256": self.reference_sha256,
            "observed_at": self.observed_at,
            "relation": self.relation,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class HostStateComponent:
    """One explicit H(t) variable backed by admitted evidence."""

    domain: str
    name: str
    value: str | int | float | bool
    basis: str
    evidence_ids: tuple[str, ...]
    unit: str | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        if self.domain not in STATE_DOMAINS:
            raise ValueError(
                "state domain must be one of " + ", ".join(STATE_DOMAINS) + "."
            )
        _require_text(self.name, "component name")
        _validate_scalar(self.value, "component value")
        if self.basis not in COMPONENT_BASES:
            raise ValueError(
                "component basis must be one of "
                + ", ".join(COMPONENT_BASES)
                + "."
            )
        _validate_text_tuple(
            self.evidence_ids,
            "component evidence_id",
            nonempty=True,
        )
        if self.unit is not None:
            _require_text(self.unit, "component unit")
        if self.note is not None:
            _require_text(self.note, "component note")

    @property
    def key(self) -> tuple[str, str]:
        return self.domain, self.name

    def to_dict(self) -> dict:
        return {
            "domain": self.domain,
            "name": self.name,
            "value": self.value,
            "basis": self.basis,
            "evidence_ids": list(self.evidence_ids),
            "unit": self.unit,
            "note": self.note,
        }


@dataclass(frozen=True)
class HostStateReference:
    """Immutable pointer to an earlier H(t) snapshot."""

    record_id: str
    content_sha256: str
    host_profile_id: str
    host_genome_sha256: str
    as_of: str

    def __post_init__(self) -> None:
        _require_text(self.record_id, "previous state record_id")
        _validate_digest(self.content_sha256, "previous state content_sha256")
        _require_text(self.host_profile_id, "previous state host_profile_id")
        _validate_digest(
            self.host_genome_sha256,
            "previous state host_genome_sha256",
        )
        _parse_timestamp(self.as_of, "previous state as_of")

    def to_dict(self) -> dict:
        return {
            "record_id": self.record_id,
            "content_sha256": self.content_sha256,
            "host_profile_id": self.host_profile_id,
            "host_genome_sha256": self.host_genome_sha256,
            "as_of": self.as_of,
        }


@dataclass(frozen=True)
class HostState:
    """Content-addressed, time-indexed dynamic state for one HostProfile."""

    host_state_id: str
    revision: int
    host_profile_id: str
    host_genome_sha256: str
    as_of: str
    components: tuple[HostStateComponent, ...]
    evidence: tuple[HostStateEvidence, ...]
    limitations: tuple[str, ...]
    previous_state: HostStateReference | None
    created_at: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_text(self.host_state_id, "host_state_id")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("revision must be a positive integer.")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"HostState schema_version must be {SCHEMA_VERSION}."
            )
        _require_text(self.host_profile_id, "host_profile_id")
        _validate_digest(self.host_genome_sha256, "host_genome_sha256")
        as_of = _parse_timestamp(self.as_of, "as_of")
        created_at = _parse_timestamp(self.created_at, "created_at")

        if not isinstance(self.components, tuple) or any(
            not isinstance(item, HostStateComponent) for item in self.components
        ):
            raise ValueError("components must contain HostStateComponent objects.")
        if not isinstance(self.evidence, tuple) or any(
            not isinstance(item, HostStateEvidence) for item in self.evidence
        ):
            raise ValueError("evidence must contain HostStateEvidence objects.")
        _validate_text_tuple(self.limitations, "limitation")

        component_keys = [item.key for item in self.components]
        if len(set(component_keys)) != len(component_keys):
            raise ValueError("HostState component domain/name pairs must be unique.")

        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("HostState evidence IDs must be unique.")
        available = set(evidence_ids)
        for item in self.evidence:
            if item.host_profile_id != self.host_profile_id:
                raise ValueError(
                    "HostState evidence host_profile_id must match the snapshot host."
                )
            if _parse_timestamp(item.observed_at, "evidence observed_at") > as_of:
                raise ValueError(
                    "HostState cannot cite evidence observed after its as_of time."
                )
        for component in self.components:
            missing = set(component.evidence_ids) - available
            if missing:
                raise ValueError(
                    "HostState component references missing evidence: "
                    + ", ".join(sorted(missing))
                    + "."
                )

        if self.previous_state is not None:
            if not isinstance(self.previous_state, HostStateReference):
                raise ValueError("previous_state must be a HostStateReference.")
            if self.previous_state.host_profile_id != self.host_profile_id:
                raise ValueError(
                    "previous_state host_profile_id must match the current HostState."
                )
            if self.previous_state.host_genome_sha256 != self.host_genome_sha256:
                raise ValueError(
                    "previous_state genome must match the current HostState."
                )
            if _parse_timestamp(self.previous_state.as_of, "previous state as_of") > as_of:
                raise ValueError(
                    "previous_state cannot be later than the current HostState."
                )
            if self.previous_state.record_id == self.record_id:
                raise ValueError("HostState cannot reference itself as previous_state.")

        if created_at < as_of:
            raise ValueError("created_at must not be earlier than as_of.")

    @property
    def record_id(self) -> str:
        return f"{self.host_state_id}:v{self.revision}"

    def _content_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "record_id": self.record_id,
            "host_state_id": self.host_state_id,
            "revision": self.revision,
            "host_profile_id": self.host_profile_id,
            "host_genome_sha256": self.host_genome_sha256,
            "as_of": self.as_of,
            "components": [item.to_dict() for item in self.components],
            "evidence": [item.to_dict() for item in self.evidence],
            "limitations": list(self.limitations),
            "previous_state": (
                None if self.previous_state is None
                else self.previous_state.to_dict()
            ),
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

    def component(self, domain: str, name: str) -> HostStateComponent | None:
        for item in self.components:
            if item.domain == domain and item.name == name:
                return item
        return None


def host_state_reference(state: HostState) -> HostStateReference:
    if not isinstance(state, HostState):
        raise ValueError("state must be a HostState.")
    return HostStateReference(
        record_id=state.record_id,
        content_sha256=state.content_sha256,
        host_profile_id=state.host_profile_id,
        host_genome_sha256=state.host_genome_sha256,
        as_of=state.as_of,
    )


def new_host_state(
    profile: HostProfile,
    *,
    host_state_id: str,
    as_of: str,
    components: tuple[HostStateComponent, ...] = (),
    evidence: tuple[HostStateEvidence, ...] = (),
    limitations: tuple[str, ...] = (),
    previous_state: HostState | HostStateReference | None = None,
    revision: int = 1,
    created_at: str | None = None,
) -> HostState:
    """Create H(t) without copying stable HostProfile features into it.

    Components are a complete explicit snapshot of the admitted dynamic state at
    the as_of time. Previous components are not inherited automatically.
    """

    if not isinstance(profile, HostProfile):
        raise ValueError("profile must be a HostProfile.")
    if isinstance(previous_state, HostState):
        previous = host_state_reference(previous_state)
    elif previous_state is None or isinstance(previous_state, HostStateReference):
        previous = previous_state
    else:
        raise ValueError("previous_state must be HostState, HostStateReference or null.")

    return HostState(
        host_state_id=host_state_id,
        revision=revision,
        host_profile_id=profile.profile_id,
        host_genome_sha256=profile.genome.sha256,
        as_of=as_of,
        components=tuple(components),
        evidence=tuple(evidence),
        limitations=tuple(limitations),
        previous_state=previous,
        created_at=created_at or utc_now(),
    )



def host_state_evidence_from_measurement(
    measurement,
    *,
    evidence_id: str,
    relation: str,
    details: dict | None = None,
) -> HostStateEvidence:
    """Create a provenance reference from one arm-scoped Measurement.

    This copies lineage only. It does not promote raw measurement data into a
    biological state interpretation.
    """

    from .measurement import Measurement

    if not isinstance(measurement, Measurement):
        raise ValueError("measurement must be a Measurement.")
    if measurement.target_host_profile_id is None:
        raise ValueError(
            "Measurement must carry target_host_profile_id for HostState evidence."
        )
    return HostStateEvidence(
        evidence_id=evidence_id,
        host_profile_id=measurement.target_host_profile_id,
        kind="measurement",
        reference_id=measurement.record_id,
        reference_sha256=measurement.content_sha256,
        observed_at=measurement.recorded_at,
        relation=relation,
        details=dict(details or {}),
    )


def host_state_evidence_from_phenotype(
    phenotype,
    *,
    evidence_id: str,
    relation: str,
    details: dict | None = None,
) -> HostStateEvidence:
    """Create a provenance reference from one admitted arm-scoped Phenotype.

    The Phenotype interpretation remains the source of the biological claim;
    HostState merely points to it.
    """

    from .phenotype import Phenotype

    if not isinstance(phenotype, Phenotype):
        raise ValueError("phenotype must be a Phenotype.")
    return HostStateEvidence(
        evidence_id=evidence_id,
        host_profile_id=phenotype.target_host_profile_id,
        kind="phenotype",
        reference_id=phenotype.record_id,
        reference_sha256=phenotype.content_sha256,
        observed_at=phenotype.assessed_at,
        relation=relation,
        details=dict(details or {}),
    )


def host_state_evidence_from_dict(data: dict) -> HostStateEvidence:
    if not isinstance(data, dict):
        raise ValueError("HostState evidence must be an object.")
    required = {
        "evidence_id",
        "host_profile_id",
        "kind",
        "reference_id",
        "reference_sha256",
        "observed_at",
        "relation",
        "details",
    }
    if set(data) != required:
        raise ValueError("HostState evidence has missing or unknown fields.")
    return HostStateEvidence(
        evidence_id=data["evidence_id"],
        host_profile_id=data["host_profile_id"],
        kind=data["kind"],
        reference_id=data["reference_id"],
        reference_sha256=data["reference_sha256"],
        observed_at=data["observed_at"],
        relation=data["relation"],
        details=data["details"],
    )


def host_state_component_from_dict(data: dict) -> HostStateComponent:
    if not isinstance(data, dict):
        raise ValueError("HostState component must be an object.")
    required = {
        "domain",
        "name",
        "value",
        "basis",
        "evidence_ids",
        "unit",
        "note",
    }
    if set(data) != required:
        raise ValueError("HostState component has missing or unknown fields.")
    if not isinstance(data["evidence_ids"], list):
        raise ValueError("HostState component evidence_ids must be an array.")
    return HostStateComponent(
        domain=data["domain"],
        name=data["name"],
        value=data["value"],
        basis=data["basis"],
        evidence_ids=tuple(data["evidence_ids"]),
        unit=data["unit"],
        note=data["note"],
    )


def host_state_reference_from_dict(data: dict) -> HostStateReference:
    if not isinstance(data, dict):
        raise ValueError("HostStateReference must be an object.")
    required = {
        "record_id",
        "content_sha256",
        "host_profile_id",
        "host_genome_sha256",
        "as_of",
    }
    if set(data) != required:
        raise ValueError("HostStateReference has missing or unknown fields.")
    return HostStateReference(
        record_id=data["record_id"],
        content_sha256=data["content_sha256"],
        host_profile_id=data["host_profile_id"],
        host_genome_sha256=data["host_genome_sha256"],
        as_of=data["as_of"],
    )


def host_state_from_dict(data: dict) -> HostState:
    if not isinstance(data, dict):
        raise ValueError("HostState must be an object.")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("HostState schema_version is not supported.")
    required = {
        "content_sha256",
        "schema_version",
        "record_id",
        "host_state_id",
        "revision",
        "host_profile_id",
        "host_genome_sha256",
        "as_of",
        "components",
        "evidence",
        "limitations",
        "previous_state",
        "created_at",
    }
    if set(data) != required:
        raise ValueError("HostState has missing or unknown fields.")
    for field_name in ("components", "evidence", "limitations"):
        if not isinstance(data[field_name], list):
            raise ValueError(f"HostState {field_name} must be an array.")

    state = HostState(
        schema_version=data["schema_version"],
        host_state_id=data["host_state_id"],
        revision=data["revision"],
        host_profile_id=data["host_profile_id"],
        host_genome_sha256=data["host_genome_sha256"],
        as_of=data["as_of"],
        components=tuple(
            host_state_component_from_dict(item) for item in data["components"]
        ),
        evidence=tuple(
            host_state_evidence_from_dict(item) for item in data["evidence"]
        ),
        limitations=tuple(data["limitations"]),
        previous_state=(
            None
            if data["previous_state"] is None
            else host_state_reference_from_dict(data["previous_state"])
        ),
        created_at=data["created_at"],
    )
    if data["record_id"] != state.record_id:
        raise ValueError("record_id does not match host_state_id and revision.")
    if data["content_sha256"] != state.content_sha256:
        raise ValueError("content_sha256 does not match the HostState content.")
    return state


def write_host_state(state: HostState, path: Path) -> None:
    if not isinstance(state, HostState):
        raise ValueError("state must be a HostState.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(state.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def load_host_state(path: Path) -> HostState:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"HostState could not be loaded: {exc}") from None
    return host_state_from_dict(data)

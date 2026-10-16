"""Versioned phage identity and provenance records.

PhageProfile keeps phage identity separate from phage-host interaction evidence.
Version 1 focuses on provenance and sequence identity. It deliberately does not
turn database host annotations, PHIST rankings, or other interaction signals
into properties of the phage itself.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re

SCHEMA_VERSION = 1
PROVENANCE_KINDS = ("retrieved", "natural", "engineered")
SHA256_PATTERN = re.compile(r"\A[0-9a-f]{64}\Z")


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


def _validate_sha256(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not SHA256_PATTERN.match(value):
        raise ValueError(f"{field_name} must be a SHA-256 digest.")


@dataclass(frozen=True)
class SequenceRef:
    """Sequence identity without embedding sequence content in the profile."""

    accession: str | None = None
    sha256: str | None = None
    length: int | None = None

    def __post_init__(self) -> None:
        if self.accession is None and self.sha256 is None:
            raise ValueError("SequenceRef requires an accession or sha256.")
        if self.accession is not None:
            _require_text(self.accession, "sequence accession")
        if self.sha256 is not None:
            _validate_sha256(self.sha256, "sequence sha256")
        if self.length is not None and (
            type(self.length) is not int or self.length < 1
        ):
            raise ValueError("sequence length must be a positive integer.")

    def to_dict(self) -> dict:
        result = {}
        if self.accession is not None:
            result["accession"] = self.accession
        if self.sha256 is not None:
            result["sha256"] = self.sha256
        if self.length is not None:
            result["length"] = self.length
        return result


@dataclass(frozen=True)
class RetrievedProvenance:
    """Profile constructed from an external reference record.

    This provenance class says where the record came from. It does not assert
    that the biological phage was natural or engineered unless that fact is
    represented by a separate admitted evidence source later.
    """

    source_db: str
    accession: str
    retrieved_at: str
    source_uri: str
    snapshot_version: str | None = None
    snapshot_sha256: str | None = None
    kind: str = "retrieved"

    def __post_init__(self) -> None:
        if self.kind != "retrieved":
            raise ValueError("RetrievedProvenance kind must be 'retrieved'.")
        _require_text(self.source_db, "source_db")
        _require_text(self.accession, "accession")
        _require_text(self.source_uri, "source_uri")
        _validate_timestamp(self.retrieved_at, "retrieved_at")
        snapshot_fields = (self.snapshot_version, self.snapshot_sha256)
        if any(value is not None for value in snapshot_fields):
            if not all(
                isinstance(value, str) and value.strip() for value in snapshot_fields
            ):
                raise ValueError(
                    "snapshot_version and snapshot_sha256 must be provided together."
                )
            _validate_sha256(self.snapshot_sha256, "snapshot_sha256")

    def to_dict(self) -> dict:
        result = {
            "kind": self.kind,
            "source_db": self.source_db,
            "accession": self.accession,
            "retrieved_at": self.retrieved_at,
            "source_uri": self.source_uri,
        }
        if self.snapshot_version is not None:
            result["snapshot_version"] = self.snapshot_version
            result["snapshot_sha256"] = self.snapshot_sha256
        return result


@dataclass(frozen=True)
class NaturalProvenance:
    """Locally tracked natural isolate with an explicit collection identity."""

    collection_id: str
    isolate_id: str
    recorded_at: str
    source_description: str
    kind: str = "natural"

    def __post_init__(self) -> None:
        if self.kind != "natural":
            raise ValueError("NaturalProvenance kind must be 'natural'.")
        _require_text(self.collection_id, "collection_id")
        _require_text(self.isolate_id, "isolate_id")
        _require_text(self.source_description, "source_description")
        _validate_timestamp(self.recorded_at, "recorded_at")

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "collection_id": self.collection_id,
            "isolate_id": self.isolate_id,
            "recorded_at": self.recorded_at,
            "source_description": self.source_description,
        }


@dataclass(frozen=True)
class EngineeredProvenance:
    """Designed/engineered phage lineage.

    The profile records design identity and parent profiles only. The exact
    engineering procedure belongs in separately governed design/build records,
    not in this identity object.
    """

    design_id: str
    parent_profile_ids: tuple[str, ...]
    designed_at: str
    design_tool: str | None = None
    design_version: str | None = None
    kind: str = "engineered"

    def __post_init__(self) -> None:
        if self.kind != "engineered":
            raise ValueError("EngineeredProvenance kind must be 'engineered'.")
        _require_text(self.design_id, "design_id")
        _validate_timestamp(self.designed_at, "designed_at")
        if not self.parent_profile_ids:
            raise ValueError(
                "engineered provenance requires at least one parent profile."
            )
        if any(
            not isinstance(value, str) or not value.strip()
            for value in self.parent_profile_ids
        ):
            raise ValueError("parent_profile_ids must be nonempty strings.")
        if len(set(self.parent_profile_ids)) != len(self.parent_profile_ids):
            raise ValueError("parent_profile_ids must be unique.")
        for field_name in ("design_tool", "design_version"):
            value = getattr(self, field_name)
            if value is not None:
                _require_text(value, field_name)

    def to_dict(self) -> dict:
        result = {
            "kind": self.kind,
            "design_id": self.design_id,
            "parent_profile_ids": list(self.parent_profile_ids),
            "designed_at": self.designed_at,
        }
        if self.design_tool is not None:
            result["design_tool"] = self.design_tool
        if self.design_version is not None:
            result["design_version"] = self.design_version
        return result


PhageProvenance = RetrievedProvenance | NaturalProvenance | EngineeredProvenance


@dataclass(frozen=True)
class PhageProfile:
    """Versioned phage identity independent of interaction evidence."""

    phage_id: str
    revision: int
    provenance: PhageProvenance
    sequence: SequenceRef | None
    source_annotations: dict
    created_at: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_text(self.phage_id, "phage_id")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("revision must be a positive integer.")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"PhageProfile schema_version must be {SCHEMA_VERSION}."
            )
        if not isinstance(
            self.provenance,
            (RetrievedProvenance, NaturalProvenance, EngineeredProvenance),
        ):
            raise ValueError("provenance must be a supported provenance object.")
        if self.sequence is not None and not isinstance(self.sequence, SequenceRef):
            raise ValueError("sequence must be a SequenceRef or None.")
        if not isinstance(self.source_annotations, dict):
            raise ValueError("source_annotations must be an object.")
        for key, value in self.source_annotations.items():
            _require_text(key, "source annotation key")
            if value is not None and not isinstance(value, (str, int, float, bool)):
                raise ValueError(
                    "source annotation values must be scalar values or null."
                )
        _validate_timestamp(self.created_at, "created_at")

    @property
    def profile_id(self) -> str:
        return f"{self.phage_id}:v{self.revision}"

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "phage_id": self.phage_id,
            "revision": self.revision,
            "created_at": self.created_at,
            "provenance": self.provenance.to_dict(),
            "sequence": self.sequence.to_dict() if self.sequence else None,
            "source_annotations": dict(self.source_annotations),
        }


def _sequence_from_dict(data: dict | None) -> SequenceRef | None:
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ValueError("sequence must be an object or null.")
    allowed = {"accession", "sha256", "length"}
    if set(data) - allowed:
        raise ValueError("sequence contains unknown fields.")
    return SequenceRef(
        accession=data.get("accession"),
        sha256=data.get("sha256"),
        length=data.get("length"),
    )


def _provenance_from_dict(data: dict) -> PhageProvenance:
    if not isinstance(data, dict):
        raise ValueError("provenance must be an object.")
    kind = data.get("kind")
    if kind == "retrieved":
        allowed = {
            "kind",
            "source_db",
            "accession",
            "retrieved_at",
            "source_uri",
            "snapshot_version",
            "snapshot_sha256",
        }
        if set(data) - allowed:
            raise ValueError("retrieved provenance contains unknown fields.")
        return RetrievedProvenance(
            source_db=data.get("source_db"),
            accession=data.get("accession"),
            retrieved_at=data.get("retrieved_at"),
            source_uri=data.get("source_uri"),
            snapshot_version=data.get("snapshot_version"),
            snapshot_sha256=data.get("snapshot_sha256"),
        )
    if kind == "natural":
        required = {
            "kind",
            "collection_id",
            "isolate_id",
            "recorded_at",
            "source_description",
        }
        if set(data) != required:
            raise ValueError("natural provenance has missing or unknown fields.")
        return NaturalProvenance(
            collection_id=data["collection_id"],
            isolate_id=data["isolate_id"],
            recorded_at=data["recorded_at"],
            source_description=data["source_description"],
        )
    if kind == "engineered":
        allowed = {
            "kind",
            "design_id",
            "parent_profile_ids",
            "designed_at",
            "design_tool",
            "design_version",
        }
        if set(data) - allowed:
            raise ValueError("engineered provenance contains unknown fields.")
        parents = data.get("parent_profile_ids")
        if not isinstance(parents, list):
            raise ValueError("parent_profile_ids must be an array.")
        return EngineeredProvenance(
            design_id=data.get("design_id"),
            parent_profile_ids=tuple(parents),
            designed_at=data.get("designed_at"),
            design_tool=data.get("design_tool"),
            design_version=data.get("design_version"),
        )
    raise ValueError(
        "provenance.kind must be one of " + ", ".join(PROVENANCE_KINDS) + "."
    )


def phage_profile_from_dict(data: dict) -> PhageProfile:
    """Validate and reconstruct a serialized PhageProfile."""

    if not isinstance(data, dict):
        raise ValueError("PhageProfile must be an object.")
    required = {
        "schema_version",
        "profile_id",
        "phage_id",
        "revision",
        "created_at",
        "provenance",
        "sequence",
        "source_annotations",
    }
    if set(data) != required:
        raise ValueError("PhageProfile has missing or unknown fields.")
    profile = PhageProfile(
        schema_version=data["schema_version"],
        phage_id=data["phage_id"],
        revision=data["revision"],
        provenance=_provenance_from_dict(data["provenance"]),
        sequence=_sequence_from_dict(data["sequence"]),
        source_annotations=data["source_annotations"],
        created_at=data["created_at"],
    )
    if data["profile_id"] != profile.profile_id:
        raise ValueError("profile_id does not match phage_id and revision.")
    return profile


def new_natural_phage_profile(
    phage_id: str,
    *,
    collection_id: str,
    isolate_id: str,
    recorded_at: str,
    source_description: str,
    sequence: SequenceRef | None = None,
    source_annotations: dict | None = None,
    revision: int = 1,
    created_at: str | None = None,
) -> PhageProfile:
    """Create a profile for a locally tracked natural isolate."""

    return PhageProfile(
        phage_id=phage_id,
        revision=revision,
        provenance=NaturalProvenance(
            collection_id=collection_id,
            isolate_id=isolate_id,
            recorded_at=recorded_at,
            source_description=source_description,
        ),
        sequence=sequence,
        source_annotations=dict(source_annotations or {}),
        created_at=created_at or utc_now(),
    )


def new_engineered_phage_profile(
    phage_id: str,
    *,
    design_id: str,
    parent_profile_ids: tuple[str, ...] | list[str],
    designed_at: str,
    design_tool: str | None = None,
    design_version: str | None = None,
    sequence: SequenceRef | None = None,
    source_annotations: dict | None = None,
    revision: int = 1,
    created_at: str | None = None,
) -> PhageProfile:
    """Create a profile for an engineered design while preserving parent lineage."""

    return PhageProfile(
        phage_id=phage_id,
        revision=revision,
        provenance=EngineeredProvenance(
            design_id=design_id,
            parent_profile_ids=tuple(parent_profile_ids),
            designed_at=designed_at,
            design_tool=design_tool,
            design_version=design_version,
        ),
        sequence=sequence,
        source_annotations=dict(source_annotations or {}),
        created_at=created_at or utc_now(),
    )


def _optional_positive_int(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def retrieved_candidate_to_phage_profile(
    candidate: dict,
    *,
    revision: int = 1,
    created_at: str | None = None,
) -> PhageProfile:
    """Convert one sourced candidate record into a retrieved PhageProfile.

    Host queries and ranking blocks are intentionally not copied. They describe
    a retrieval context or phage-host interaction evidence, not intrinsic phage
    identity.
    """

    if not isinstance(candidate, dict):
        raise ValueError("candidate must be an object.")
    required = ("id", "source_db", "accession", "retrieved_at", "source_uri")
    missing = [
        field
        for field in required
        if not isinstance(candidate.get(field), str) or not candidate[field].strip()
    ]
    if missing:
        raise ValueError(
            "retrieved candidate is missing provenance: " + ", ".join(missing)
        )
    if candidate.get("simulated") is True:
        raise ValueError("simulated candidates cannot become PhageProfile records.")

    snapshot_version = candidate.get("snapshot_version")
    snapshot_sha256 = candidate.get("snapshot_sha256")
    if bool(snapshot_version) != bool(snapshot_sha256):
        raise ValueError(
            "snapshot_version and snapshot_sha256 must be provided together."
        )

    provenance = RetrievedProvenance(
        source_db=candidate["source_db"],
        accession=candidate["accession"],
        retrieved_at=candidate["retrieved_at"],
        source_uri=candidate["source_uri"],
        snapshot_version=snapshot_version,
        snapshot_sha256=snapshot_sha256,
    )
    sequence = SequenceRef(
        accession=candidate["accession"],
        length=_optional_positive_int(candidate.get("genome_length")),
    )
    copied_fields = (
        "description",
        "recorded_host",
        "host_annotation_source",
        "classification",
        "molecule",
        "coding_capacity",
        "cds_count",
        "jumbophage",
    )
    annotations = {
        field: candidate[field]
        for field in copied_fields
        if candidate.get(field) not in (None, "")
    }
    return PhageProfile(
        phage_id=candidate["id"],
        revision=revision,
        provenance=provenance,
        sequence=sequence,
        source_annotations=annotations,
        created_at=created_at or utc_now(),
    )


def write_phage_profile(profile: PhageProfile, path: Path) -> None:
    """Atomically write one PhageProfile JSON document."""

    if not isinstance(profile, PhageProfile):
        raise ValueError("profile must be a PhageProfile.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(profile.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def load_phage_profile(path: Path) -> PhageProfile:
    """Load and validate one PhageProfile JSON document."""

    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"PhageProfile could not be loaded: {exc}") from None
    return phage_profile_from_dict(data)

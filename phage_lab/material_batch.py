"""Versioned physical material identities for experiment execution.

MaterialBatch represents an actual tracked host or phage material batch. It is
not a database candidate and it does not imply biological quality merely because
it exists. Test-ready binding requires an explicitly released, usable batch.
"""

from dataclasses import dataclass
from pathlib import Path

from .artifacts import (
    ContentAddressed,
    atomic_write_json,
    parse_timestamp as _validate_timestamp,
    read_json,
    require_text as _require_text,
    require_text_tuple,
    utc_now,
)

from .experiment_spec import ExperimentSpec

SCHEMA_VERSION = 1
MATERIAL_TYPES = ("host", "phage")
SOURCE_KINDS = ("acquired", "local_collection", "built")
QUALITY_STATUSES = ("pending", "released", "rejected")
AVAILABILITY_STATUSES = ("available", "reserved", "consumed", "unavailable")
USABLE_AVAILABILITY = ("available", "reserved")


@dataclass(frozen=True)
class MaterialSource:
    kind: str
    reference: str
    recorded_at: str

    def __post_init__(self) -> None:
        if self.kind not in SOURCE_KINDS:
            raise ValueError(f"source kind must be one of {SOURCE_KINDS}.")
        _require_text(self.reference, "source reference")
        _validate_timestamp(self.recorded_at, "source recorded_at")

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "reference": self.reference,
            "recorded_at": self.recorded_at,
        }


@dataclass(frozen=True)
class MaterialBatch(ContentAddressed):
    """Immutable material-batch record tied to one versioned profile."""

    batch_id: str
    revision: int
    material_type: str
    profile_id: str
    source: MaterialSource
    quality_status: str
    availability_status: str
    quality_evidence: tuple[str, ...]
    created_at: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_text(self.batch_id, "batch_id")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("revision must be a positive integer.")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"MaterialBatch schema_version must be {SCHEMA_VERSION}."
            )
        if self.material_type not in MATERIAL_TYPES:
            raise ValueError(
                f"material_type must be one of {MATERIAL_TYPES}."
            )
        _require_text(self.profile_id, "profile_id")
        if not isinstance(self.source, MaterialSource):
            raise ValueError("source must be a MaterialSource.")
        if self.quality_status not in QUALITY_STATUSES:
            raise ValueError(
                f"quality_status must be one of {QUALITY_STATUSES}."
            )
        if self.availability_status not in AVAILABILITY_STATUSES:
            raise ValueError(
                f"availability_status must be one of {AVAILABILITY_STATUSES}."
            )
        require_text_tuple(self.quality_evidence, "quality_evidence")
        if (
            self.quality_status in {"released", "rejected"}
            and not self.quality_evidence
        ):
            raise ValueError(
                f"{self.quality_status} material requires quality_evidence."
            )
        _validate_timestamp(self.created_at, "created_at")

    @property
    def record_id(self) -> str:
        return f"{self.batch_id}:v{self.revision}"

    @property
    def test_ready(self) -> bool:
        return (
            self.quality_status == "released"
            and self.availability_status in USABLE_AVAILABILITY
        )

    def _content_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "record_id": self.record_id,
            "batch_id": self.batch_id,
            "revision": self.revision,
            "material_type": self.material_type,
            "profile_id": self.profile_id,
            "source": self.source.to_dict(),
            "quality_status": self.quality_status,
            "availability_status": self.availability_status,
            "quality_evidence": list(self.quality_evidence),
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ExperimentMaterials:
    """Exact test-ready batches bound to an ExperimentSpec."""

    host_batch: MaterialBatch
    phage_batches: tuple[MaterialBatch, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.host_batch, MaterialBatch):
            raise ValueError("host_batch must be a MaterialBatch.")
        if self.host_batch.material_type != "host":
            raise ValueError("host_batch must have material_type='host'.")
        if not self.phage_batches:
            raise ValueError("phage_batches must not be empty.")
        if any(
            not isinstance(batch, MaterialBatch)
            or batch.material_type != "phage"
            for batch in self.phage_batches
        ):
            raise ValueError("phage_batches must contain phage MaterialBatch objects.")

    @property
    def batch_ids(self) -> tuple[str, ...]:
        return (
            self.host_batch.record_id,
            *(batch.record_id for batch in self.phage_batches),
        )

    def to_dict(self) -> dict:
        return {
            "host_batch": self.host_batch.to_dict(),
            "phage_batches": [batch.to_dict() for batch in self.phage_batches],
            "batch_ids": list(self.batch_ids),
        }


def new_material_batch(
    batch_id: str,
    *,
    material_type: str,
    profile_id: str,
    source_kind: str,
    source_reference: str,
    quality_status: str = "pending",
    availability_status: str = "available",
    quality_evidence: tuple[str, ...] = (),
    revision: int = 1,
    recorded_at: str | None = None,
    created_at: str | None = None,
) -> MaterialBatch:
    now = created_at or utc_now()
    return MaterialBatch(
        batch_id=batch_id,
        revision=revision,
        material_type=material_type,
        profile_id=profile_id,
        source=MaterialSource(
            kind=source_kind,
            reference=source_reference,
            recorded_at=recorded_at or now,
        ),
        quality_status=quality_status,
        availability_status=availability_status,
        quality_evidence=quality_evidence,
        created_at=now,
    )


def _source_from_dict(data: dict) -> MaterialSource:
    if not isinstance(data, dict) or set(data) != {
        "kind",
        "reference",
        "recorded_at",
    }:
        raise ValueError("source has missing or unknown fields.")
    return MaterialSource(
        kind=data["kind"],
        reference=data["reference"],
        recorded_at=data["recorded_at"],
    )


def material_batch_from_dict(data: dict) -> MaterialBatch:
    if not isinstance(data, dict):
        raise ValueError("MaterialBatch must be an object.")
    required = {
        "content_sha256",
        "schema_version",
        "record_id",
        "batch_id",
        "revision",
        "material_type",
        "profile_id",
        "source",
        "quality_status",
        "availability_status",
        "quality_evidence",
        "created_at",
    }
    if set(data) != required:
        raise ValueError("MaterialBatch has missing or unknown fields.")
    if not isinstance(data["quality_evidence"], list):
        raise ValueError("quality_evidence must be an array.")

    batch = MaterialBatch(
        schema_version=data["schema_version"],
        batch_id=data["batch_id"],
        revision=data["revision"],
        material_type=data["material_type"],
        profile_id=data["profile_id"],
        source=_source_from_dict(data["source"]),
        quality_status=data["quality_status"],
        availability_status=data["availability_status"],
        quality_evidence=tuple(data["quality_evidence"]),
        created_at=data["created_at"],
    )
    if data["record_id"] != batch.record_id:
        raise ValueError("record_id does not match batch_id and revision.")
    if data["content_sha256"] != batch.content_sha256:
        raise ValueError("content_sha256 does not match the MaterialBatch content.")
    return batch


def bind_material_batches_to_spec(
    spec: ExperimentSpec,
    batches: list[MaterialBatch],
) -> ExperimentMaterials:
    """Resolve exactly one test-ready host and phage batch per locked profile."""

    if not isinstance(spec, ExperimentSpec):
        raise ValueError("spec must be an ExperimentSpec.")
    if not isinstance(batches, list):
        raise ValueError("batches must be a list.")
    if any(not isinstance(batch, MaterialBatch) for batch in batches):
        raise ValueError("batches must contain MaterialBatch objects.")

    def select(material_type: str, profile_id: str) -> MaterialBatch:
        matches = [
            batch
            for batch in batches
            if batch.material_type == material_type
            and batch.profile_id == profile_id
            and batch.test_ready
        ]
        if not matches:
            raise ValueError(
                f"No test-ready {material_type} MaterialBatch matches {profile_id!r}."
            )
        if len(matches) > 1:
            raise ValueError(
                f"Multiple test-ready {material_type} MaterialBatches match "
                f"{profile_id!r}; select an unambiguous batch set."
            )
        return matches[0]

    host = select("host", spec.target_host.profile_id)
    phages = tuple(
        select("phage", profile_id)
        for profile_id in spec.member_phage_profile_ids
    )
    return ExperimentMaterials(host_batch=host, phage_batches=phages)


def write_material_batch(batch: MaterialBatch, path: Path) -> None:
    if not isinstance(batch, MaterialBatch):
        raise ValueError("batch must be a MaterialBatch.")
    atomic_write_json(batch.to_dict(), path)


def load_material_batch(path: Path) -> MaterialBatch:
    data = read_json(path, 'MaterialBatch')
    return material_batch_from_dict(data)

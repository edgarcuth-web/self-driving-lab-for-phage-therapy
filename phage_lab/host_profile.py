"""Versioned host characterization records.

HostProfile is the scientific entry point for the closed-loop platform. The
first version is intentionally conservative: it records genome identity,
feature-class assessment state and analysis provenance without pretending that
receptor, defense or other biological predictors already exist.

Raw FASTA content is never stored in the profile.
"""

from dataclasses import dataclass, field
from pathlib import Path

from .artifacts import (
    atomic_write_json,
    is_sha256,
    parse_timestamp as _validate_timestamp,
    read_json,
    require_text as _require_text,
    utc_now,
)

from .biology import GenomeSummary

SCHEMA_VERSION = 1
FEATURE_GROUPS = (
    "receptors",
    "surface_structures",
    "defense_systems",
    "amr",
    "virulence",
)
FEATURE_STATUSES = ("unknown", "assessed")


@dataclass(frozen=True)
class FeatureItem:
    """One reported feature with explicit evidence provenance."""

    name: str
    source: str
    method: str | None = None
    reference: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.name, "feature name")
        _require_text(self.source, "feature source")
        for field_name in ("method", "reference"):
            value = getattr(self, field_name)
            if value is not None:
                _require_text(value, field_name)

    def to_dict(self) -> dict:
        result = {"name": self.name, "source": self.source}
        if self.method is not None:
            result["method"] = self.method
        if self.reference is not None:
            result["reference"] = self.reference
        return result


@dataclass(frozen=True)
class FeatureGroup:
    """Assessment state for one biological feature class.

    "unknown" means no admitted analysis has assessed the class.
    "assessed" means an identified analysis did assess it; an empty item list
    is then a legitimate assessed-negative result rather than missing data.
    """

    status: str = "unknown"
    items: tuple[FeatureItem, ...] = ()
    note: str | None = None

    def __post_init__(self) -> None:
        if self.status not in FEATURE_STATUSES:
            raise ValueError(
                f"feature status must be one of {', '.join(FEATURE_STATUSES)}."
            )
        if self.status == "unknown" and self.items:
            raise ValueError("An unknown feature group cannot contain reported items.")
        if self.note is not None:
            _require_text(self.note, "feature note")
        if any(not isinstance(item, FeatureItem) for item in self.items):
            raise ValueError("FeatureGroup items must be FeatureItem objects.")

    def to_dict(self) -> dict:
        result = {
            "status": self.status,
            "items": [item.to_dict() for item in self.items],
        }
        if self.note is not None:
            result["note"] = self.note
        return result


@dataclass(frozen=True)
class AnalysisRun:
    """Identity of an analysis that contributed to a HostProfile."""

    analyzer: str
    version: str
    analyzed_at: str
    input_sha256: str
    parameters: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.analyzer, "analyzer")
        _require_text(self.version, "analysis version")
        _validate_timestamp(self.analyzed_at, "analyzed_at")
        if not is_sha256(self.input_sha256):
            raise ValueError("analysis input_sha256 must be a SHA-256 digest.")
        if not isinstance(self.parameters, dict):
            raise ValueError("analysis parameters must be an object.")

    def to_dict(self) -> dict:
        return {
            "analyzer": self.analyzer,
            "version": self.version,
            "analyzed_at": self.analyzed_at,
            "input_sha256": self.input_sha256,
            "parameters": dict(self.parameters),
        }


@dataclass(frozen=True)
class HostProfile:
    """Versioned, provenance-preserving representation of one target host."""

    host_id: str
    revision: int
    genome: GenomeSummary
    taxonomy: dict
    features: dict[str, FeatureGroup]
    analysis_runs: tuple[AnalysisRun, ...]
    created_at: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_text(self.host_id, "host_id")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("revision must be a positive integer.")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"HostProfile schema_version must be {SCHEMA_VERSION}."
            )
        if not isinstance(self.genome, GenomeSummary):
            raise ValueError("genome must be a GenomeSummary.")
        if not isinstance(self.taxonomy, dict):
            raise ValueError("taxonomy must be an object.")
        for key, value in self.taxonomy.items():
            _require_text(key, "taxonomy key")
            if value is not None:
                _require_text(value, f"taxonomy.{key}")
        if set(self.features) != set(FEATURE_GROUPS):
            raise ValueError(
                "features must contain exactly: " + ", ".join(FEATURE_GROUPS)
            )
        if any(not isinstance(group, FeatureGroup) for group in self.features.values()):
            raise ValueError("features values must be FeatureGroup objects.")
        if (
            not is_sha256(self.genome.sha256)
            or type(self.genome.bases) is not int
            or self.genome.bases < 1
            or type(self.genome.contigs) is not int
            or self.genome.contigs < 1
        ):
            raise ValueError("genome summary is invalid.")
        if any(not isinstance(run, AnalysisRun) for run in self.analysis_runs):
            raise ValueError("analysis_runs must contain AnalysisRun objects.")
        if any(group.status == "assessed" for group in self.features.values()) and not self.analysis_runs:
            raise ValueError(
                "assessed feature groups require at least one analysis run."
            )
        for run in self.analysis_runs:
            if run.input_sha256 != self.genome.sha256:
                raise ValueError(
                    "analysis input_sha256 must match the HostProfile genome."
                )
        _validate_timestamp(self.created_at, "created_at")

    @property
    def profile_id(self) -> str:
        return f"{self.host_id}:v{self.revision}"

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "host_id": self.host_id,
            "revision": self.revision,
            "created_at": self.created_at,
            "genome": self.genome.public_metadata(),
            "taxonomy": dict(self.taxonomy),
            "features": {
                name: self.features[name].to_dict() for name in FEATURE_GROUPS
            },
            "analysis_runs": [run.to_dict() for run in self.analysis_runs],
        }


def new_host_profile(
    host_id: str,
    genome: GenomeSummary,
    *,
    taxonomy: dict | None = None,
    revision: int = 1,
    created_at: str | None = None,
) -> HostProfile:
    """Create an uncharacterized HostProfile from a validated genome summary."""

    unknown = {
        name: FeatureGroup(
            status="unknown",
            note="No admitted analyzer has assessed this feature class.",
        )
        for name in FEATURE_GROUPS
    }
    return HostProfile(
        host_id=host_id,
        revision=revision,
        genome=genome,
        taxonomy=dict(taxonomy or {}),
        features=unknown,
        analysis_runs=(),
        created_at=created_at or utc_now(),
    )


def _feature_item_from_dict(data: dict) -> FeatureItem:
    if not isinstance(data, dict):
        raise ValueError("feature item must be an object.")
    allowed = {"name", "source", "method", "reference"}
    if set(data) - allowed:
        raise ValueError("feature item contains unknown fields.")
    return FeatureItem(
        name=data.get("name"),
        source=data.get("source"),
        method=data.get("method"),
        reference=data.get("reference"),
    )


def _feature_group_from_dict(data: dict) -> FeatureGroup:
    if not isinstance(data, dict):
        raise ValueError("feature group must be an object.")
    if set(data) - {"status", "items", "note"}:
        raise ValueError("feature group contains unknown fields.")
    items = data.get("items", [])
    if not isinstance(items, list):
        raise ValueError("feature group items must be an array.")
    return FeatureGroup(
        status=data.get("status", "unknown"),
        items=tuple(_feature_item_from_dict(item) for item in items),
        note=data.get("note"),
    )


def _analysis_run_from_dict(data: dict) -> AnalysisRun:
    if not isinstance(data, dict):
        raise ValueError("analysis run must be an object.")
    required = {"analyzer", "version", "analyzed_at", "input_sha256", "parameters"}
    if set(data) != required:
        raise ValueError("analysis run has missing or unknown fields.")
    return AnalysisRun(
        analyzer=data["analyzer"],
        version=data["version"],
        analyzed_at=data["analyzed_at"],
        input_sha256=data["input_sha256"],
        parameters=data["parameters"],
    )


def host_profile_from_dict(data: dict) -> HostProfile:
    """Validate and reconstruct a serialized HostProfile."""

    if not isinstance(data, dict):
        raise ValueError("HostProfile must be an object.")
    required = {
        "schema_version",
        "profile_id",
        "host_id",
        "revision",
        "created_at",
        "genome",
        "taxonomy",
        "features",
        "analysis_runs",
    }
    if set(data) != required:
        raise ValueError("HostProfile has missing or unknown fields.")
    genome_data = data["genome"]
    if not isinstance(genome_data, dict) or set(genome_data) != {
        "sha256",
        "bases",
        "contigs",
    }:
        raise ValueError("HostProfile genome has an invalid shape.")
    genome = GenomeSummary(
        sha256=genome_data["sha256"],
        bases=genome_data["bases"],
        contigs=genome_data["contigs"],
    )
    if (
        not is_sha256(genome.sha256)
        or type(genome.bases) is not int
        or genome.bases < 1
        or type(genome.contigs) is not int
        or genome.contigs < 1
    ):
        raise ValueError("HostProfile genome summary is invalid.")
    features_data = data["features"]
    if not isinstance(features_data, dict) or set(features_data) != set(FEATURE_GROUPS):
        raise ValueError("HostProfile features have an invalid shape.")
    runs = data["analysis_runs"]
    if not isinstance(runs, list):
        raise ValueError("HostProfile analysis_runs must be an array.")
    profile = HostProfile(
        schema_version=data["schema_version"],
        host_id=data["host_id"],
        revision=data["revision"],
        genome=genome,
        taxonomy=data["taxonomy"],
        features={
            name: _feature_group_from_dict(features_data[name])
            for name in FEATURE_GROUPS
        },
        analysis_runs=tuple(_analysis_run_from_dict(run) for run in runs),
        created_at=data["created_at"],
    )
    if data["profile_id"] != profile.profile_id:
        raise ValueError("profile_id does not match host_id and revision.")
    return profile


def write_host_profile(profile: HostProfile, path: Path) -> None:
    """Atomically write a HostProfile JSON document."""

    if not isinstance(profile, HostProfile):
        raise ValueError("profile must be a HostProfile.")
    atomic_write_json(profile.to_dict(), path)


def load_host_profile(path: Path) -> HostProfile:
    """Load and validate a HostProfile JSON document."""

    data = read_json(path, 'HostProfile')
    return host_profile_from_dict(data)

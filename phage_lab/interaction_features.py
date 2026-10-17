"""Provenance-bound numeric feature vectors for host-phage interaction models."""

from dataclasses import dataclass, field
import math
from pathlib import Path

from .artifacts import (
    atomic_write_json,
    content_hash,
    parse_timestamp,
    read_json,
    require_text,
    utc_now,
    validate_digest,
    with_content_hash,
)
from .host_state import HostState, HostStateReference, host_state_reference
from .interaction_prediction import phage_profile_sha256
from .phage_profile import PhageProfile

SCHEMA_VERSION = 1
_FEATURE_VECTOR_FIELDS = {
    "content_sha256", "schema_version", "record_id", "vector_id", "revision",
    "host_state", "phage_profile_id", "phage_profile_sha256", "features",
    "feature_sources", "producer", "created_at",
}


def _text_tuple(values, field_name, *, nonempty=False):
    if not isinstance(values, tuple) or (nonempty and not values):
        raise ValueError(
            f"{field_name} must be a {'nonempty ' if nonempty else ''}tuple."
        )
    for value in values:
        require_text(value, field_name)
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} values must be unique.")


def _scalar_mapping(value, field_name):
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object.")
    for key, item in value.items():
        require_text(key, f"{field_name} key")
        if item is None or isinstance(item, (str, int, bool)):
            continue
        if isinstance(item, float) and math.isfinite(item):
            continue
        raise ValueError(f"{field_name} values must be finite JSON scalars or null.")


def _finite_number(value, field_name, *, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field_name} must be a finite number.")
    if minimum is not None and value < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}.")
    if maximum is not None and value > maximum:
        raise ValueError(f"{field_name} must be at most {maximum}.")


@dataclass(frozen=True)
class FeatureSource:
    """Provenance for one derived feature; the source artifact is not embedded."""

    source: str
    version: str
    method: str
    input_sha256: str
    reference: str | None = None
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self):
        for name in ("source", "version", "method"):
            require_text(getattr(self, name), name)
        validate_digest(self.input_sha256, "feature source input_sha256")
        if self.reference is not None:
            require_text(self.reference, "feature source reference")
        _text_tuple(self.evidence_ids, "feature source evidence_id")

    def to_dict(self):
        return {
            "source": self.source,
            "version": self.version,
            "method": self.method,
            "input_sha256": self.input_sha256,
            "reference": self.reference,
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(frozen=True)
class FeatureProducer:
    """Identity of the process that emitted a feature vector."""

    name: str
    version: str
    parameters: dict = field(default_factory=dict)
    code_sha256: str | None = None

    def __post_init__(self):
        require_text(self.name, "feature producer name")
        require_text(self.version, "feature producer version")
        _scalar_mapping(self.parameters, "feature producer parameters")
        if self.code_sha256 is not None:
            validate_digest(self.code_sha256, "feature producer code_sha256")

    def to_dict(self):
        return {
            "name": self.name,
            "version": self.version,
            "parameters": dict(self.parameters),
            "code_sha256": self.code_sha256,
        }


@dataclass(frozen=True)
class InteractionFeatureVector:
    """Content-addressed numeric features for one exact host-state/phage pair."""

    vector_id: str
    revision: int
    host_state: HostStateReference
    phage_profile_id: str
    phage_profile_sha256: str
    features: dict
    feature_sources: dict[str, FeatureSource]
    producer: FeatureProducer
    created_at: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self):
        require_text(self.vector_id, "vector_id")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("feature vector revision must be a positive integer.")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"InteractionFeatureVector schema_version must be {SCHEMA_VERSION}.")
        if not isinstance(self.host_state, HostStateReference):
            raise ValueError("feature vector host_state must be a HostStateReference.")
        require_text(self.phage_profile_id, "phage_profile_id")
        validate_digest(self.phage_profile_sha256, "phage_profile_sha256")
        if not isinstance(self.features, dict) or not self.features:
            raise ValueError("features must be a nonempty object.")
        for name, value in self.features.items():
            require_text(name, "feature name")
            if value is not None:
                _finite_number(value, f"feature {name}")
        if not isinstance(self.feature_sources, dict):
            raise ValueError("feature_sources must be an object.")
        if set(self.feature_sources) != set(self.features):
            raise ValueError("feature_sources must provide provenance for every feature and no others.")
        if any(not isinstance(source, FeatureSource) for source in self.feature_sources.values()):
            raise ValueError("feature_sources values must be FeatureSource objects.")
        if not isinstance(self.producer, FeatureProducer):
            raise ValueError("producer must be a FeatureProducer.")
        parse_timestamp(self.created_at, "feature vector created_at")

    @property
    def record_id(self):
        return f"{self.vector_id}:v{self.revision}"

    @property
    def feature_schema_id(self):
        return content_hash({
            "feature_names": sorted(self.features),
            "feature_sources": {
                name: {
                    "source": self.feature_sources[name].source,
                    "version": self.feature_sources[name].version,
                    "method": self.feature_sources[name].method,
                }
                for name in sorted(self.feature_sources)
            },
            "producer": {
                "name": self.producer.name,
                "version": self.producer.version,
                "parameters": self.producer.parameters,
                "code_sha256": self.producer.code_sha256,
            },
        })

    @property
    def content_sha256(self):
        return content_hash(self._content_dict())

    def _content_dict(self):
        return {
            "schema_version": self.schema_version,
            "record_id": self.record_id,
            "vector_id": self.vector_id,
            "revision": self.revision,
            "host_state": self.host_state.to_dict(),
            "phage_profile_id": self.phage_profile_id,
            "phage_profile_sha256": self.phage_profile_sha256,
            "features": {key: self.features[key] for key in sorted(self.features)},
            "feature_sources": {
                key: self.feature_sources[key].to_dict()
                for key in sorted(self.feature_sources)
            },
            "producer": self.producer.to_dict(),
            "created_at": self.created_at,
        }

    def to_dict(self):
        return with_content_hash(self._content_dict())


def new_interaction_feature_vector(
    host_state: HostState,
    phage_profile: PhageProfile,
    features: dict,
    feature_sources: dict[str, FeatureSource],
    producer: FeatureProducer,
    *,
    vector_id: str,
    revision: int = 1,
    created_at: str | None = None,
) -> InteractionFeatureVector:
    """Bind externally extracted features to exact domain artifacts."""

    if not isinstance(host_state, HostState):
        raise ValueError("host_state must be a HostState.")
    if not isinstance(phage_profile, PhageProfile):
        raise ValueError("phage_profile must be a PhageProfile.")
    if not isinstance(producer, FeatureProducer):
        raise ValueError("producer must be a FeatureProducer.")
    return InteractionFeatureVector(
        vector_id=vector_id,
        revision=revision,
        host_state=host_state_reference(host_state),
        phage_profile_id=phage_profile.profile_id,
        phage_profile_sha256=phage_profile_sha256(phage_profile),
        features=dict(features),
        feature_sources=dict(feature_sources),
        producer=producer,
        created_at=created_at or utc_now(),
    )


def feature_source_from_dict(data):
    expected = {"source", "version", "method", "input_sha256", "reference", "evidence_ids"}
    if not isinstance(data, dict) or set(data) != expected:
        raise ValueError("FeatureSource has missing or unknown fields.")
    if not isinstance(data["evidence_ids"], list):
        raise ValueError("FeatureSource evidence_ids must be an array.")
    return FeatureSource(
        source=data["source"],
        version=data["version"],
        method=data["method"],
        input_sha256=data["input_sha256"],
        reference=data["reference"],
        evidence_ids=tuple(data["evidence_ids"]),
    )


def feature_producer_from_dict(data):
    expected = {"name", "version", "parameters", "code_sha256"}
    if not isinstance(data, dict) or set(data) != expected:
        raise ValueError("FeatureProducer has missing or unknown fields.")
    return FeatureProducer(
        name=data["name"],
        version=data["version"],
        parameters=data["parameters"],
        code_sha256=data["code_sha256"],
    )


def interaction_feature_vector_from_dict(data):
    if not isinstance(data, dict) or set(data) != _FEATURE_VECTOR_FIELDS:
        raise ValueError("InteractionFeatureVector has missing or unknown fields.")
    if data["schema_version"] != SCHEMA_VERSION:
        raise ValueError("Unsupported InteractionFeatureVector schema_version.")
    if not isinstance(data["host_state"], dict) or set(data["host_state"]) != {
        "record_id", "content_sha256", "host_profile_id", "host_genome_sha256", "as_of"
    }:
        raise ValueError("feature vector host_state reference is malformed.")
    if not isinstance(data["feature_sources"], dict):
        raise ValueError("feature_sources must be an object.")
    vector = InteractionFeatureVector(
        vector_id=data["vector_id"],
        revision=data["revision"],
        host_state=HostStateReference(**data["host_state"]),
        phage_profile_id=data["phage_profile_id"],
        phage_profile_sha256=data["phage_profile_sha256"],
        features=data["features"],
        feature_sources={
            name: feature_source_from_dict(source)
            for name, source in data["feature_sources"].items()
        },
        producer=feature_producer_from_dict(data["producer"]),
        created_at=data["created_at"],
        schema_version=data["schema_version"],
    )
    if vector.to_dict() != data:
        raise ValueError("InteractionFeatureVector content hash or derived fields mismatch.")
    return vector


def write_interaction_feature_vector(vector: InteractionFeatureVector, path: Path):
    if not isinstance(vector, InteractionFeatureVector):
        raise ValueError("vector must be an InteractionFeatureVector.")
    atomic_write_json(vector.to_dict(), path)


def load_interaction_feature_vector(path: Path):
    return interaction_feature_vector_from_dict(read_json(path, "InteractionFeatureVector"))



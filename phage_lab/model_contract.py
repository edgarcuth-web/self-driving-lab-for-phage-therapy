"""Versioned exchange contract between the lab and an external model repository.

This module owns request/result lineage and admission only. It does not extract
features, train models, fit calibrators, or execute external model code.
"""

from dataclasses import dataclass
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
from .interaction_evidence import InteractionEvidence
from .interaction_prediction import (
    InteractionPrediction,
    PredictionProducer,
    ProbabilityEstimate,
    new_interaction_prediction,
    phage_profile_sha256,
    prediction_producer_from_dict,
    probability_estimate_from_dict,
)
from .phage_profile import PhageProfile

SCHEMA_VERSION = 1
PREDICTION_TARGETS = (
    "adsorption",
    "productive_infection",
    "resistance_emergence",
)


def _text_tuple(values, field_name, *, nonempty=False):
    if not isinstance(values, tuple) or (nonempty and not values):
        raise ValueError(
            f"{field_name} must be a {'nonempty ' if nonempty else ''}tuple."
        )
    for value in values:
        require_text(value, field_name)
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} values must be unique.")


def _host_reference_from_dict(data):
    expected = {
        "record_id",
        "content_sha256",
        "host_profile_id",
        "host_genome_sha256",
        "as_of",
    }
    if not isinstance(data, dict) or set(data) != expected:
        raise ValueError("host_state reference has missing or unknown fields.")
    return HostStateReference(**data)


@dataclass(frozen=True)
class ModelRequest:
    """Exact scientific input identity handed to an external model system."""

    request_id: str
    host_state: HostStateReference
    phage_profile_id: str
    phage_profile_sha256: str
    requested_targets: tuple[str, ...]
    created_at: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self):
        require_text(self.request_id, "request_id")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"ModelRequest schema_version must be {SCHEMA_VERSION}.")
        if not isinstance(self.host_state, HostStateReference):
            raise ValueError("host_state must be a HostStateReference.")
        require_text(self.phage_profile_id, "phage_profile_id")
        validate_digest(self.phage_profile_sha256, "phage_profile_sha256")
        _text_tuple(self.requested_targets, "requested target", nonempty=True)
        if any(target not in PREDICTION_TARGETS for target in self.requested_targets):
            raise ValueError(
                "requested_targets must contain only "
                + ", ".join(PREDICTION_TARGETS)
                + "."
            )
        created = parse_timestamp(self.created_at, "ModelRequest created_at")
        host_as_of = parse_timestamp(self.host_state.as_of, "host_state as_of")
        if created < host_as_of:
            raise ValueError("ModelRequest created_at cannot predate HostState as_of.")

    @property
    def record_id(self):
        return self.request_id

    def _content_dict(self):
        return {
            "schema_version": self.schema_version,
            "record_id": self.record_id,
            "request_id": self.request_id,
            "host_state": self.host_state.to_dict(),
            "phage_profile_id": self.phage_profile_id,
            "phage_profile_sha256": self.phage_profile_sha256,
            "requested_targets": list(self.requested_targets),
            "created_at": self.created_at,
        }

    @property
    def content_sha256(self):
        return content_hash(self._content_dict())

    def to_dict(self):
        return with_content_hash(self._content_dict())


def new_model_request(
    host_state: HostState,
    phage_profile: PhageProfile,
    *,
    request_id: str,
    requested_targets: tuple[str, ...] = PREDICTION_TARGETS,
    created_at: str | None = None,
) -> ModelRequest:
    if not isinstance(host_state, HostState):
        raise ValueError("host_state must be a HostState.")
    if not isinstance(phage_profile, PhageProfile):
        raise ValueError("phage_profile must be a PhageProfile.")
    return ModelRequest(
        request_id=request_id,
        host_state=host_state_reference(host_state),
        phage_profile_id=phage_profile.profile_id,
        phage_profile_sha256=phage_profile_sha256(phage_profile),
        requested_targets=tuple(requested_targets),
        created_at=created_at or utc_now(),
    )


def model_request_from_dict(data):
    expected = {
        "content_sha256",
        "schema_version",
        "record_id",
        "request_id",
        "host_state",
        "phage_profile_id",
        "phage_profile_sha256",
        "requested_targets",
        "created_at",
    }
    if not isinstance(data, dict) or set(data) != expected:
        raise ValueError("ModelRequest has missing or unknown fields.")
    if not isinstance(data["requested_targets"], list):
        raise ValueError("requested_targets must be an array.")
    request = ModelRequest(
        request_id=data["request_id"],
        host_state=_host_reference_from_dict(data["host_state"]),
        phage_profile_id=data["phage_profile_id"],
        phage_profile_sha256=data["phage_profile_sha256"],
        requested_targets=tuple(data["requested_targets"]),
        created_at=data["created_at"],
        schema_version=data["schema_version"],
    )
    if request.to_dict() != data:
        raise ValueError("ModelRequest content hash or derived fields mismatch.")
    return request


def write_model_request(request: ModelRequest, path: Path):
    if not isinstance(request, ModelRequest):
        raise ValueError("request must be a ModelRequest.")
    atomic_write_json(request.to_dict(), path)


def load_model_request(path: Path):
    return model_request_from_dict(read_json(path, "ModelRequest"))


@dataclass(frozen=True)
class ModelResult:
    """External model output still awaiting admission as InteractionPrediction."""

    result_id: str
    request_id: str
    request_sha256: str
    host_state: HostStateReference
    phage_profile_id: str
    phage_profile_sha256: str
    adsorption: ProbabilityEstimate
    productive_infection: ProbabilityEstimate
    resistance_emergence: ProbabilityEstimate
    mechanistic_explanation: str
    limitations: tuple[str, ...]
    producer: PredictionProducer
    predicted_at: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self):
        require_text(self.result_id, "result_id")
        require_text(self.request_id, "request_id")
        validate_digest(self.request_sha256, "request_sha256")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"ModelResult schema_version must be {SCHEMA_VERSION}.")
        if not isinstance(self.host_state, HostStateReference):
            raise ValueError("host_state must be a HostStateReference.")
        require_text(self.phage_profile_id, "phage_profile_id")
        validate_digest(self.phage_profile_sha256, "phage_profile_sha256")
        estimates = []
        for name in PREDICTION_TARGETS:
            estimate = getattr(self, name)
            if not isinstance(estimate, ProbabilityEstimate):
                raise ValueError(f"{name} must be a ProbabilityEstimate.")
            estimates.append(estimate)
        require_text(self.mechanistic_explanation, "mechanistic_explanation")
        _text_tuple(self.limitations, "limitation")
        if not isinstance(self.producer, PredictionProducer):
            raise ValueError("producer must be a PredictionProducer.")
        predicted = parse_timestamp(self.predicted_at, "ModelResult predicted_at")
        host_as_of = parse_timestamp(self.host_state.as_of, "host_state as_of")
        if predicted < host_as_of:
            raise ValueError("ModelResult predicted_at cannot predate HostState as_of.")
        if any(item.status == "estimated" for item in estimates):
            if self.producer.artifact_sha256 is None:
                raise ValueError(
                    "estimated external model output requires producer.artifact_sha256."
                )

    @property
    def record_id(self):
        return self.result_id

    def _content_dict(self):
        return {
            "schema_version": self.schema_version,
            "record_id": self.record_id,
            "result_id": self.result_id,
            "request_id": self.request_id,
            "request_sha256": self.request_sha256,
            "host_state": self.host_state.to_dict(),
            "phage_profile_id": self.phage_profile_id,
            "phage_profile_sha256": self.phage_profile_sha256,
            "probabilities": {
                "adsorption": self.adsorption.to_dict(),
                "productive_infection": self.productive_infection.to_dict(),
                "resistance_emergence": self.resistance_emergence.to_dict(),
            },
            "mechanistic_explanation": self.mechanistic_explanation,
            "limitations": list(self.limitations),
            "producer": self.producer.to_dict(),
            "predicted_at": self.predicted_at,
        }

    @property
    def content_sha256(self):
        return content_hash(self._content_dict())

    def to_dict(self):
        return with_content_hash(self._content_dict())


def model_result_from_dict(data):
    expected = {
        "content_sha256",
        "schema_version",
        "record_id",
        "result_id",
        "request_id",
        "request_sha256",
        "host_state",
        "phage_profile_id",
        "phage_profile_sha256",
        "probabilities",
        "mechanistic_explanation",
        "limitations",
        "producer",
        "predicted_at",
    }
    if not isinstance(data, dict) or set(data) != expected:
        raise ValueError("ModelResult has missing or unknown fields.")
    probabilities = data["probabilities"]
    if not isinstance(probabilities, dict) or set(probabilities) != set(PREDICTION_TARGETS):
        raise ValueError(
            "ModelResult probabilities must contain exactly "
            + ", ".join(PREDICTION_TARGETS)
            + "."
        )
    if not isinstance(data["limitations"], list):
        raise ValueError("limitations must be an array.")
    result = ModelResult(
        result_id=data["result_id"],
        request_id=data["request_id"],
        request_sha256=data["request_sha256"],
        host_state=_host_reference_from_dict(data["host_state"]),
        phage_profile_id=data["phage_profile_id"],
        phage_profile_sha256=data["phage_profile_sha256"],
        adsorption=probability_estimate_from_dict(probabilities["adsorption"]),
        productive_infection=probability_estimate_from_dict(
            probabilities["productive_infection"]
        ),
        resistance_emergence=probability_estimate_from_dict(
            probabilities["resistance_emergence"]
        ),
        mechanistic_explanation=data["mechanistic_explanation"],
        limitations=tuple(data["limitations"]),
        producer=prediction_producer_from_dict(data["producer"]),
        predicted_at=data["predicted_at"],
        schema_version=data["schema_version"],
    )
    if result.to_dict() != data:
        raise ValueError("ModelResult content hash or derived fields mismatch.")
    return result


def write_model_result(result: ModelResult, path: Path):
    if not isinstance(result, ModelResult):
        raise ValueError("result must be a ModelResult.")
    atomic_write_json(result.to_dict(), path)


def load_model_result(path: Path):
    return model_result_from_dict(read_json(path, "ModelResult"))


def admit_model_result(
    request: ModelRequest,
    result: ModelResult,
    host_state: HostState,
    phage_profile: PhageProfile,
    supporting_evidence: tuple[InteractionEvidence, ...] | list[InteractionEvidence] = (),
    *,
    prediction_id: str,
    revision: int = 1,
) -> InteractionPrediction:
    """Admit an exact external result into the lab's prediction contract.

    Passing this boundary establishes lineage consistency only. It does not prove
    scientific validity, calibration, assay comparability, or clinical utility.
    """

    if not isinstance(request, ModelRequest):
        raise ValueError("request must be a ModelRequest.")
    if not isinstance(result, ModelResult):
        raise ValueError("result must be a ModelResult.")
    if not isinstance(host_state, HostState):
        raise ValueError("host_state must be a HostState.")
    if not isinstance(phage_profile, PhageProfile):
        raise ValueError("phage_profile must be a PhageProfile.")

    if request.host_state != host_state_reference(host_state):
        raise ValueError("ModelRequest does not match the exact HostState.")
    if (
        request.phage_profile_id != phage_profile.profile_id
        or request.phage_profile_sha256 != phage_profile_sha256(phage_profile)
    ):
        raise ValueError("ModelRequest does not match the exact PhageProfile.")
    if (
        result.request_id != request.request_id
        or result.request_sha256 != request.content_sha256
    ):
        raise ValueError("ModelResult does not bind the exact ModelRequest.")
    if result.host_state != request.host_state:
        raise ValueError("ModelResult HostState does not match ModelRequest.")
    if (
        result.phage_profile_id != request.phage_profile_id
        or result.phage_profile_sha256 != request.phage_profile_sha256
    ):
        raise ValueError("ModelResult PhageProfile does not match ModelRequest.")
    if parse_timestamp(result.predicted_at, "predicted_at") < parse_timestamp(
        request.created_at, "request created_at"
    ):
        raise ValueError("ModelResult predicted_at cannot predate ModelRequest creation.")

    requested = set(request.requested_targets)
    for name in PREDICTION_TARGETS:
        if name not in requested and getattr(result, name).status == "estimated":
            raise ValueError(f"ModelResult estimated unrequested target {name!r}.")

    return new_interaction_prediction(
        host_state,
        phage_profile,
        supporting_evidence,
        prediction_id=prediction_id,
        revision=revision,
        adsorption=result.adsorption,
        productive_infection=result.productive_infection,
        resistance_emergence=result.resistance_emergence,
        mechanistic_explanation=result.mechanistic_explanation,
        limitations=result.limitations,
        producer=result.producer,
        predicted_at=result.predicted_at,
    )

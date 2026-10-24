"""Traceable host-phage probability predictions.

InteractionPrediction is deliberately separate from InteractionEvidence.
Evidence records what a source observed or computed. Prediction is the only
layer allowed to emit calibrated probability-shaped outputs.

Every prediction binds an exact HostState snapshot, an exact PhageProfile
fingerprint, model provenance and the exact pairwise InteractionEvidence records
used at prediction time. Predictions for unseen pairs may have no pairwise
InteractionEvidence, but that absence is explicit rather than silently filled.
"""

from dataclasses import dataclass, field
from hashlib import sha256
import json
import math
from pathlib import Path

from .artifacts import (
    ContentAddressed,
    atomic_write_json,
    parse_timestamp as _parse_timestamp,
    read_json,
    require_text as _require_text,
    require_text_tuple,
    utc_now,
    validate_digest as _validate_digest,
    validate_scalar_mapping,
)

from .host_state import HostState, HostStateReference, host_state_reference
from .interaction_evidence import InteractionEvidence
from .phage_profile import PhageProfile

SCHEMA_VERSION = 1
ESTIMATE_STATUSES = ("estimated", "not_estimated")


def _validate_probability(value: float, field_name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0.0 <= float(value) <= 1.0
    ):
        raise ValueError(f"{field_name} must be a finite probability in [0, 1].")


@dataclass(frozen=True)
class ProbabilityEstimate:
    """One calibrated probability plus an explicit uncertainty interval.

    A not_estimated value contains no numeric placeholder. An estimated value
    requires both probability and an uncertainty interval so downstream code
    cannot mistake a point estimate for certainty.
    """

    status: str
    probability: float | None = None
    uncertainty_lower: float | None = None
    uncertainty_upper: float | None = None
    uncertainty_method: str | None = None

    def __post_init__(self) -> None:
        if self.status not in ESTIMATE_STATUSES:
            raise ValueError(
                "estimate status must be one of "
                + ", ".join(ESTIMATE_STATUSES)
                + "."
            )
        fields = (
            self.probability,
            self.uncertainty_lower,
            self.uncertainty_upper,
            self.uncertainty_method,
        )
        if self.status == "not_estimated":
            if any(value is not None for value in fields):
                raise ValueError(
                    "not_estimated probability must not contain numeric or uncertainty values."
                )
            return

        if self.probability is None:
            raise ValueError("estimated probability requires probability.")
        if self.uncertainty_lower is None or self.uncertainty_upper is None:
            raise ValueError(
                "estimated probability requires uncertainty_lower and uncertainty_upper."
            )
        if self.uncertainty_method is None:
            raise ValueError(
                "estimated probability requires uncertainty_method."
            )
        _validate_probability(self.probability, "probability")
        _validate_probability(self.uncertainty_lower, "uncertainty_lower")
        _validate_probability(self.uncertainty_upper, "uncertainty_upper")
        _require_text(self.uncertainty_method, "uncertainty_method")
        if not (
            float(self.uncertainty_lower)
            <= float(self.probability)
            <= float(self.uncertainty_upper)
        ):
            raise ValueError(
                "uncertainty interval must contain the predicted probability."
            )

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "probability": self.probability,
            "uncertainty_lower": self.uncertainty_lower,
            "uncertainty_upper": self.uncertainty_upper,
            "uncertainty_method": self.uncertainty_method,
        }


@dataclass(frozen=True)
class PredictionProducer:
    """Identity of the model or rule system that emitted a prediction."""

    name: str
    version: str
    parameters: dict = field(default_factory=dict)
    artifact_sha256: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.name, "producer name")
        _require_text(self.version, "producer version")
        validate_scalar_mapping(self.parameters, "producer parameters")
        if self.artifact_sha256 is not None:
            _validate_digest(self.artifact_sha256, "artifact_sha256")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "parameters": dict(self.parameters),
            "artifact_sha256": self.artifact_sha256,
        }


def phage_profile_sha256(profile: PhageProfile) -> str:
    """Fingerprint the exact PhageProfile content used as model input."""

    if not isinstance(profile, PhageProfile):
        raise ValueError("profile must be a PhageProfile.")
    canonical = json.dumps(
        profile.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


@dataclass(frozen=True)
class InteractionPrediction(ContentAddressed):
    """Content-addressed prediction for one exact H(t)-phage pair."""

    prediction_id: str
    revision: int
    host_state: HostStateReference
    phage_profile_id: str
    phage_profile_sha256: str
    supporting_evidence_ids: tuple[str, ...]
    adsorption: ProbabilityEstimate
    productive_infection: ProbabilityEstimate
    resistance_emergence: ProbabilityEstimate
    mechanistic_explanation: str
    limitations: tuple[str, ...]
    producer: PredictionProducer
    predicted_at: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_text(self.prediction_id, "prediction_id")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("revision must be a positive integer.")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"InteractionPrediction schema_version must be {SCHEMA_VERSION}."
            )
        if not isinstance(self.host_state, HostStateReference):
            raise ValueError("host_state must be a HostStateReference.")
        _require_text(self.phage_profile_id, "phage_profile_id")
        _validate_digest(self.phage_profile_sha256, "phage_profile_sha256")
        require_text_tuple(
            self.supporting_evidence_ids,
            "supporting evidence_id",
        )
        for field_name in (
            "adsorption",
            "productive_infection",
            "resistance_emergence",
        ):
            if not isinstance(getattr(self, field_name), ProbabilityEstimate):
                raise ValueError(
                    f"{field_name} must be a ProbabilityEstimate."
                )
        _require_text(self.mechanistic_explanation, "mechanistic_explanation")
        require_text_tuple(self.limitations, "limitation")
        if all(
            estimate.status == "not_estimated"
            for estimate in (
                self.adsorption,
                self.productive_infection,
                self.resistance_emergence,
            )
        ) and not self.limitations:
            raise ValueError(
                "an entirely not_estimated prediction requires at least one limitation."
            )
        if not isinstance(self.producer, PredictionProducer):
            raise ValueError("producer must be a PredictionProducer.")
        predicted = _parse_timestamp(self.predicted_at, "predicted_at")
        if predicted < _parse_timestamp(self.host_state.as_of, "host_state as_of"):
            raise ValueError(
                "predicted_at must not be earlier than the HostState as_of time."
            )

    @property
    def record_id(self) -> str:
        return f"{self.prediction_id}:v{self.revision}"

    def _content_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "record_id": self.record_id,
            "prediction_id": self.prediction_id,
            "revision": self.revision,
            "host_state": self.host_state.to_dict(),
            "phage_profile_id": self.phage_profile_id,
            "phage_profile_sha256": self.phage_profile_sha256,
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
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


def _validate_supporting_evidence(
    host_state: HostState,
    phage_profile_id: str,
    evidence: tuple[InteractionEvidence, ...],
) -> tuple[str, ...]:
    if any(not isinstance(item, InteractionEvidence) for item in evidence):
        raise ValueError(
            "supporting evidence must contain InteractionEvidence objects."
        )
    as_of = _parse_timestamp(host_state.as_of, "host_state as_of")
    ids = []
    for item in evidence:
        if item.phage_profile_id != phage_profile_id:
            raise ValueError(
                "supporting InteractionEvidence phage_profile_id does not match the prediction phage."
            )
        if item.host.genome_sha256 != host_state.host_genome_sha256:
            raise ValueError(
                "supporting InteractionEvidence host genome does not match HostState."
            )
        if (
            item.host.profile_id is not None
            and item.host.profile_id != host_state.host_profile_id
        ):
            raise ValueError(
                "supporting InteractionEvidence HostProfile does not match HostState."
            )
        if _parse_timestamp(item.observed_at, "evidence observed_at") > as_of:
            raise ValueError(
                "supporting InteractionEvidence observed after HostState as_of would leak future information."
            )
        ids.append(item.evidence_id)
    if len(set(ids)) != len(ids):
        raise ValueError("supporting InteractionEvidence records must be unique.")
    return tuple(ids)


def new_interaction_prediction(
    host_state: HostState,
    phage_profile: PhageProfile,
    supporting_evidence: tuple[InteractionEvidence, ...] | list[InteractionEvidence],
    *,
    prediction_id: str,
    adsorption: ProbabilityEstimate,
    productive_infection: ProbabilityEstimate,
    resistance_emergence: ProbabilityEstimate,
    mechanistic_explanation: str,
    producer: PredictionProducer,
    limitations: tuple[str, ...] = (),
    revision: int = 1,
    predicted_at: str | None = None,
) -> InteractionPrediction:
    """Create one fully lineage-checked InteractionPrediction."""

    if not isinstance(host_state, HostState):
        raise ValueError("host_state must be a HostState.")
    if not isinstance(phage_profile, PhageProfile):
        raise ValueError("phage_profile must be a PhageProfile.")
    if not isinstance(supporting_evidence, (tuple, list)):
        raise ValueError("supporting_evidence must be a tuple or list.")

    evidence_ids = _validate_supporting_evidence(
        host_state,
        phage_profile.profile_id,
        tuple(supporting_evidence),
    )
    return InteractionPrediction(
        prediction_id=prediction_id,
        revision=revision,
        host_state=host_state_reference(host_state),
        phage_profile_id=phage_profile.profile_id,
        phage_profile_sha256=phage_profile_sha256(phage_profile),
        supporting_evidence_ids=evidence_ids,
        adsorption=adsorption,
        productive_infection=productive_infection,
        resistance_emergence=resistance_emergence,
        mechanistic_explanation=mechanistic_explanation,
        limitations=tuple(limitations),
        producer=producer,
        predicted_at=predicted_at or utc_now(),
    )


def evidence_only_unresolved_prediction(
    host_state: HostState,
    phage_profile: PhageProfile,
    supporting_evidence: tuple[InteractionEvidence, ...] | list[InteractionEvidence],
    *,
    prediction_id: str,
    revision: int = 1,
    predicted_at: str | None = None,
) -> InteractionPrediction:
    """Create an explicit unresolved record without inventing probabilities.

    This is useful while the system has pairwise signals such as PHIST but no
    calibrated model that maps those signals to adsorption, productive infection
    or resistance-emergence probabilities.
    """

    unknown = ProbabilityEstimate(status="not_estimated")
    return new_interaction_prediction(
        host_state,
        phage_profile,
        supporting_evidence,
        prediction_id=prediction_id,
        adsorption=unknown,
        productive_infection=unknown,
        resistance_emergence=unknown,
        mechanistic_explanation=(
            "No calibrated interaction model was applied. Supporting evidence "
            "is preserved without conversion into infection probabilities."
        ),
        limitations=(
            "P(adsorption), P(productive infection), and P(resistance emergence) are not estimated.",
            "Pairwise source signals must not be interpreted as calibrated probabilities.",
        ),
        producer=PredictionProducer(
            name="evidence-only-unresolved",
            version="1",
            parameters={},
        ),
        revision=revision,
        predicted_at=predicted_at,
    )


def probability_estimate_from_dict(data: dict) -> ProbabilityEstimate:
    if not isinstance(data, dict):
        raise ValueError("ProbabilityEstimate must be an object.")
    required = {
        "status",
        "probability",
        "uncertainty_lower",
        "uncertainty_upper",
        "uncertainty_method",
    }
    if set(data) != required:
        raise ValueError("ProbabilityEstimate has missing or unknown fields.")
    return ProbabilityEstimate(
        status=data["status"],
        probability=data["probability"],
        uncertainty_lower=data["uncertainty_lower"],
        uncertainty_upper=data["uncertainty_upper"],
        uncertainty_method=data["uncertainty_method"],
    )


def prediction_producer_from_dict(data: dict) -> PredictionProducer:
    if not isinstance(data, dict):
        raise ValueError("PredictionProducer must be an object.")
    required = {
        "name",
        "version",
        "parameters",
        "artifact_sha256",
    }
    if set(data) != required:
        raise ValueError("PredictionProducer has missing or unknown fields.")
    return PredictionProducer(
        name=data["name"],
        version=data["version"],
        parameters=data["parameters"],
        artifact_sha256=data["artifact_sha256"],
    )


def _host_state_reference_from_dict(data: dict) -> HostStateReference:
    if not isinstance(data, dict):
        raise ValueError("host_state must be an object.")
    required = {
        "record_id",
        "content_sha256",
        "host_profile_id",
        "host_genome_sha256",
        "as_of",
    }
    if set(data) != required:
        raise ValueError("host_state has missing or unknown fields.")
    return HostStateReference(
        record_id=data["record_id"],
        content_sha256=data["content_sha256"],
        host_profile_id=data["host_profile_id"],
        host_genome_sha256=data["host_genome_sha256"],
        as_of=data["as_of"],
    )


def interaction_prediction_from_dict(data: dict) -> InteractionPrediction:
    if not isinstance(data, dict):
        raise ValueError("InteractionPrediction must be an object.")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("InteractionPrediction schema_version is not supported.")
    required = {
        "content_sha256",
        "schema_version",
        "record_id",
        "prediction_id",
        "revision",
        "host_state",
        "phage_profile_id",
        "phage_profile_sha256",
        "supporting_evidence_ids",
        "probabilities",
        "mechanistic_explanation",
        "limitations",
        "producer",
        "predicted_at",
    }
    if set(data) != required:
        raise ValueError("InteractionPrediction has missing or unknown fields.")
    if not isinstance(data["supporting_evidence_ids"], list):
        raise ValueError("supporting_evidence_ids must be an array.")
    if not isinstance(data["limitations"], list):
        raise ValueError("limitations must be an array.")
    probabilities = data["probabilities"]
    if not isinstance(probabilities, dict) or set(probabilities) != {
        "adsorption",
        "productive_infection",
        "resistance_emergence",
    }:
        raise ValueError("probabilities must contain exactly the three v1 targets.")

    prediction = InteractionPrediction(
        schema_version=data["schema_version"],
        prediction_id=data["prediction_id"],
        revision=data["revision"],
        host_state=_host_state_reference_from_dict(data["host_state"]),
        phage_profile_id=data["phage_profile_id"],
        phage_profile_sha256=data["phage_profile_sha256"],
        supporting_evidence_ids=tuple(data["supporting_evidence_ids"]),
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
    )
    if data["record_id"] != prediction.record_id:
        raise ValueError("record_id does not match prediction_id and revision.")
    if data["content_sha256"] != prediction.content_sha256:
        raise ValueError(
            "content_sha256 does not match the InteractionPrediction content."
        )
    return prediction


def write_interaction_prediction(
    prediction: InteractionPrediction,
    path: Path,
) -> None:
    if not isinstance(prediction, InteractionPrediction):
        raise ValueError("prediction must be an InteractionPrediction.")
    atomic_write_json(prediction.to_dict(), path)


def load_interaction_prediction(path: Path) -> InteractionPrediction:
    data = read_json(path, 'InteractionPrediction')
    return interaction_prediction_from_dict(data)

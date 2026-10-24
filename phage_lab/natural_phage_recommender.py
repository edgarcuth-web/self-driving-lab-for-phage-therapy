"""Prediction-aware screening candidates and a single-phage experiment bridge.

This policy chooses what to test, not a treatment or a cocktail. Unresolved
predictions remain an explicit exploration queue; no raw PHIST rank is read.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from .artifacts import (
    ContentAddressed,
    atomic_write_json,
    canonical_json as _canonical,
    parse_timestamp as _time,
    read_json,
    require_text as _text,
    validate_digest as _digest,
)

from .host_state import HostState, HostStateReference, host_state_reference
from .interaction_prediction import (
    InteractionPrediction,
    interaction_prediction_from_dict,
    phage_profile_sha256,
)
from .phage_profile import PhageProfile, PROVENANCE_KINDS

SCHEMA_VERSION = 1
POLICY_NAME = "natural-phage-screening"
POLICY_VERSION = "1"


def _fields(data, names, label):
    if not isinstance(data, dict) or set(data) != set(names.split()):
        raise ValueError(f"{label} has missing or unknown fields.")


@dataclass(frozen=True)
class RecommendationPolicy:
    """Reserve unresolved exploration slots; fill other slots by lower bound.

    If either queue is short, the other queue fills the remaining budget.
    Profile ID breaks ties reproducibly and has no biological meaning.
    """

    max_candidates: int = 3
    exploration_slots: int = 1

    def __post_init__(self):
        if type(self.max_candidates) is not int or self.max_candidates < 1:
            raise ValueError("max_candidates must be a positive integer.")
        if (type(self.exploration_slots) is not int
                or not 0 <= self.exploration_slots <= self.max_candidates):
            raise ValueError("exploration_slots must be between 0 and max_candidates.")

    def to_dict(self):
        return {
            "name": POLICY_NAME,
            "version": POLICY_VERSION,
            "max_candidates": self.max_candidates,
            "exploration_slots": self.exploration_slots,
        }


@dataclass(frozen=True)
class CandidateEvaluation:
    """One input profile and its exact prediction snapshot, including exclusions."""

    phage_profile_id: str
    phage_profile_sha256: str
    provenance_kind: str
    prediction: InteractionPrediction | None
    disposition: str

    def __post_init__(self):
        _text(self.phage_profile_id, "phage_profile_id")
        _digest(self.phage_profile_sha256, "phage_profile_sha256")
        if self.provenance_kind not in PROVENANCE_KINDS:
            raise ValueError("Unsupported provenance_kind.")
        if self.disposition not in ("selected", "deferred", "excluded"):
            raise ValueError("Unsupported candidate disposition.")
        if self.prediction is not None:
            if not isinstance(self.prediction, InteractionPrediction):
                raise ValueError("prediction must be an InteractionPrediction or null.")
            if (self.prediction.phage_profile_id != self.phage_profile_id
                    or self.prediction.phage_profile_sha256 != self.phage_profile_sha256):
                raise ValueError("Prediction does not match the exact PhageProfile.")
        if (self.basis in ("engineered", "missing_prediction")) != (
            self.disposition == "excluded"
        ):
            raise ValueError("Candidate disposition conflicts with eligibility.")

    @property
    def basis(self):
        if self.provenance_kind == "engineered":
            return "engineered"
        if self.prediction is None:
            return "missing_prediction"
        if self.prediction.productive_infection.status == "not_estimated":
            return "exploration"
        return "predicted"

    @property
    def reasons(self):
        reasons = [{
            "engineered": "Engineered provenance is outside the natural-first screening policy.",
            "missing_prediction": "An explicit InteractionPrediction is required, including for unresolved pairs.",
            "exploration": "Productive infection is not_estimated; exploration order is by profile ID, not efficacy.",
            "predicted": "Prioritized by the productive-infection uncertainty lower bound; profile ID breaks ties.",
        }[self.basis]]
        if self.disposition == "deferred":
            reasons.append("Outside this policy's candidate budget; this is not a negative phenotype.")
        if self.provenance_kind == "retrieved":
            reasons.append("Retrieved record provenance does not establish natural biological origin.")
        if self.prediction is not None and not self.prediction.supporting_evidence_ids:
            reasons.append("The prediction has no pair-specific InteractionEvidence.")
        return tuple(reasons)

    def to_dict(self):
        return {
            "phage_profile_id": self.phage_profile_id,
            "phage_profile_sha256": self.phage_profile_sha256,
            "provenance_kind": self.provenance_kind,
            "prediction": self.prediction.to_dict() if self.prediction else None,
            "disposition": self.disposition,
            "basis": self.basis,
            "reasons": list(self.reasons),
        }


def _select(entries, policy):
    predicted = [entry for entry in entries if entry.basis == "predicted"]
    # Different producers/parameters/interval semantics are not a common scale.
    cohorts = {
        (_canonical(entry.prediction.producer.to_dict()),
         entry.prediction.productive_infection.uncertainty_method)
        for entry in predicted
    }
    if len(cohorts) > 1:
        raise ValueError(
            "Estimated predictions must share producer/version/parameters/artifact "
            "and uncertainty method; provide separate comparable candidate pools."
        )
    predicted.sort(key=lambda entry: (
        -entry.prediction.productive_infection.uncertainty_lower,
        entry.phage_profile_id,
    ))
    exploration = sorted(
        (entry for entry in entries if entry.basis == "exploration"),
        key=lambda entry: entry.phage_profile_id,
    )
    reserved = min(policy.exploration_slots, len(exploration))
    selected = predicted[:policy.max_candidates - reserved]
    selected += exploration[:policy.max_candidates - len(selected)]
    return tuple(entry.phage_profile_id for entry in selected)


@dataclass(frozen=True)
class CandidateSet(ContentAddressed):
    """Content-addressed screening decision for an exact H(t) and input pool."""

    candidate_set_id: str
    revision: int
    host_state: HostStateReference
    policy: RecommendationPolicy
    evaluations: tuple[CandidateEvaluation, ...]
    selected_phage_profile_ids: tuple[str, ...]
    created_at: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self):
        _text(self.candidate_set_id, "candidate_set_id")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("revision must be a positive integer.")
        if type(self.schema_version) is not int or self.schema_version != SCHEMA_VERSION:
            raise ValueError("Unsupported CandidateSet schema_version.")
        if not isinstance(self.host_state, HostStateReference):
            raise ValueError("host_state must be a HostStateReference.")
        if not isinstance(self.policy, RecommendationPolicy):
            raise ValueError("policy must be a RecommendationPolicy.")
        if (not isinstance(self.evaluations, tuple)
                or any(not isinstance(e, CandidateEvaluation) for e in self.evaluations)):
            raise ValueError("evaluations must be a tuple of CandidateEvaluation objects.")
        profile_ids = [e.phage_profile_id for e in self.evaluations]
        if len(set(profile_ids)) != len(profile_ids):
            raise ValueError("CandidateSet PhageProfile IDs must be unique.")
        if profile_ids != sorted(profile_ids):
            raise ValueError("evaluations must be sorted by PhageProfile ID.")
        created = _time(self.created_at, "created_at")
        if created < _time(self.host_state.as_of, "host_state as_of"):
            raise ValueError("CandidateSet cannot precede its HostState.")
        prediction_ids = []
        for entry in self.evaluations:
            if entry.prediction is not None:
                prediction = entry.prediction
                if prediction.host_state != self.host_state:
                    raise ValueError("Prediction does not match the exact HostState.")
                if _time(prediction.predicted_at, "predicted_at") > created:
                    raise ValueError("CandidateSet cannot use a future prediction.")
                prediction_ids.append(prediction.record_id)
        if len(set(prediction_ids)) != len(prediction_ids):
            raise ValueError("Prediction record IDs must be unique.")
        if self.selected_phage_profile_ids != _select(self.evaluations, self.policy):
            raise ValueError("Selected candidates do not match the recorded policy.")
        for entry in self.evaluations:
            if (entry.disposition == "selected") != (
                entry.phage_profile_id in self.selected_phage_profile_ids
            ):
                raise ValueError("Candidate disposition does not match selection.")

    @property
    def record_id(self):
        return f"{self.candidate_set_id}:v{self.revision}"

    @property
    def limitations(self):
        result = [
            "This is a screening policy, not a calibrated predictor, efficacy claim or cocktail optimizer.",
            "Only productive-infection lower bounds guide predicted selection; adsorption and resistance estimates remain in source predictions.",
            "Matching model provenance is necessary but does not establish calibration or comparable assay contexts; the caller must establish these.",
            "Profile-ID tie-breaking and exploration ordering have no biological meaning or information-gain guarantee.",
            "Material availability, safety, receptor diversity and phage-phage compatibility are not assessed by this policy.",
        ]
        if any(e.provenance_kind == "retrieved" for e in self.evaluations):
            result.append("Retrieved records do not establish natural biological origin.")
        if not any(e.basis == "predicted" for e in self.evaluations):
            result.append("No eligible productive-infection estimates; any selection is exploration only.")
        if not self.selected_phage_profile_ids:
            result.append("No eligible candidates were selected; no biological failure is inferred.")
        return tuple(result)

    def _content_dict(self):
        return {
            "schema_version": self.schema_version,
            "record_id": self.record_id,
            "candidate_set_id": self.candidate_set_id,
            "revision": self.revision,
            "host_state": self.host_state.to_dict(),
            "policy": self.policy.to_dict(),
            "evaluations": [e.to_dict() for e in self.evaluations],
            "selected_phage_profile_ids": list(self.selected_phage_profile_ids),
            "limitations": list(self.limitations),
            "created_at": self.created_at,
        }


def recommend_natural_phages(
    host_state: HostState,
    phage_profiles: list[PhageProfile] | tuple[PhageProfile, ...],
    predictions: list[InteractionPrediction] | tuple[InteractionPrediction, ...],
    *,
    candidate_set_id: str,
    policy: RecommendationPolicy | None = None,
    revision: int = 1,
    created_at: str | None = None,
) -> CandidateSet:
    """Evaluate the full supplied pool; reject ambiguous or mismatched inputs."""

    if not isinstance(host_state, HostState):
        raise ValueError("host_state must be a HostState.")
    if (not isinstance(phage_profiles, (list, tuple))
            or any(not isinstance(p, PhageProfile) for p in phage_profiles)):
        raise ValueError("phage_profiles must be a list or tuple of PhageProfile objects.")
    if (not isinstance(predictions, (list, tuple))
            or any(not isinstance(p, InteractionPrediction) for p in predictions)):
        raise ValueError("predictions must be a list or tuple of InteractionPrediction objects.")
    policy = policy if policy is not None else RecommendationPolicy()
    if not isinstance(policy, RecommendationPolicy):
        raise ValueError("policy must be a RecommendationPolicy.")
    profiles = {p.profile_id: p for p in phage_profiles}
    if len(profiles) != len(phage_profiles):
        raise ValueError("PhageProfile IDs must be unique; select one exact record per ID.")
    by_phage = {}
    for prediction in predictions:
        if prediction.phage_profile_id not in profiles:
            raise ValueError("Prediction refers to a PhageProfile outside the supplied pool.")
        if prediction.phage_profile_id in by_phage:
            raise ValueError("Provide exactly one prediction per phage, not competing revisions or models.")
        # Detach mutable producer parameters from the caller's object.
        by_phage[prediction.phage_profile_id] = interaction_prediction_from_dict(
            prediction.to_dict()
        )
    entries = []
    for profile_id, profile in sorted(profiles.items()):
        prediction = by_phage.get(profile_id)
        excluded = profile.provenance.kind == "engineered" or prediction is None
        entries.append(CandidateEvaluation(
            phage_profile_id=profile_id,
            phage_profile_sha256=phage_profile_sha256(profile),
            provenance_kind=profile.provenance.kind,
            prediction=prediction,
            disposition="excluded" if excluded else "deferred",
        ))
    selected = _select(entries, policy)
    return CandidateSet(
        candidate_set_id=candidate_set_id,
        revision=revision,
        host_state=host_state_reference(host_state),
        policy=policy,
        evaluations=tuple(
            replace(e, disposition="selected") if e.phage_profile_id in selected else e
            for e in entries
        ),
        selected_phage_profile_ids=selected,
        created_at=created_at or datetime.now(timezone.utc).isoformat(),
    )


def candidate_set_from_dict(data: dict) -> CandidateSet:
    _fields(data, "content_sha256 schema_version record_id candidate_set_id revision "
            "host_state policy evaluations selected_phage_profile_ids limitations created_at",
            "CandidateSet")
    _fields(data["policy"], "name version max_candidates exploration_slots", "policy")
    if (data["policy"]["name"], data["policy"]["version"]) != (POLICY_NAME, POLICY_VERSION):
        raise ValueError("Unsupported recommendation policy.")
    _fields(data["host_state"], "record_id content_sha256 host_profile_id host_genome_sha256 as_of",
            "host_state")
    for name in ("evaluations", "selected_phage_profile_ids", "limitations"):
        if not isinstance(data[name], list):
            raise ValueError(f"{name} must be an array.")
    entries = []
    for item in data["evaluations"]:
        _fields(item, "phage_profile_id phage_profile_sha256 provenance_kind prediction "
                "disposition basis reasons", "CandidateEvaluation")
        entry = CandidateEvaluation(
            phage_profile_id=item["phage_profile_id"],
            phage_profile_sha256=item["phage_profile_sha256"],
            provenance_kind=item["provenance_kind"],
            prediction=(interaction_prediction_from_dict(item["prediction"])
                        if item["prediction"] is not None else None),
            disposition=item["disposition"],
        )
        if item["basis"] != entry.basis or item["reasons"] != list(entry.reasons):
            raise ValueError("Candidate basis/reasons do not match its inputs and disposition.")
        entries.append(entry)
    result = CandidateSet(
        candidate_set_id=data["candidate_set_id"],
        revision=data["revision"],
        host_state=HostStateReference(**data["host_state"]),
        policy=RecommendationPolicy(
            max_candidates=data["policy"]["max_candidates"],
            exploration_slots=data["policy"]["exploration_slots"],
        ),
        evaluations=tuple(entries),
        selected_phage_profile_ids=tuple(data["selected_phage_profile_ids"]),
        created_at=data["created_at"],
        schema_version=data["schema_version"],
    )
    if data["record_id"] != result.record_id or data["limitations"] != list(result.limitations):
        raise ValueError("CandidateSet record_id/limitations do not match its content.")
    if data["content_sha256"] != result.content_sha256:
        raise ValueError("content_sha256 does not match CandidateSet content.")
    return result


def write_candidate_set(candidate_set: CandidateSet, path: Path) -> None:
    if not isinstance(candidate_set, CandidateSet):
        raise ValueError("candidate_set must be a CandidateSet.")
    atomic_write_json(candidate_set.to_dict(), path)


def load_candidate_set(path: Path) -> CandidateSet:
    data = read_json(path, 'CandidateSet')
    return candidate_set_from_dict(data)


def experiment_spec_from_candidate_set(
    candidate_set: CandidateSet,
    *,
    experiment_id: str,
    workflow: dict,
    objective: str,
    expected_readouts: tuple[str, ...],
    conditions: dict | None = None,
    revision: int = 1,
    created_at: str | None = None,
):
    """One host control plus a separate single-phage arm per selected candidate.

    Readouts and conditions are caller-supplied scientific intent. This adapter
    does not choose a wet-lab protocol, combine phages, or dispatch hardware.
    """
    from .experiment_spec import ExperimentArm, SourceReference, experiment_spec_from_arms
    from .interaction_evidence import HostReference

    if not isinstance(candidate_set, CandidateSet):
        raise ValueError("candidate_set must be a CandidateSet.")
    # Revalidate the complete serialized decision before crossing the boundary.
    candidate_set = candidate_set_from_dict(candidate_set.to_dict())
    if not candidate_set.selected_phage_profile_ids:
        raise ValueError("Cannot create a screening experiment from an empty selection.")
    created_at = created_at or datetime.now(timezone.utc).isoformat()
    if _time(created_at, "created_at") < _time(candidate_set.created_at, "CandidateSet created_at"):
        raise ValueError("ExperimentSpec cannot precede its CandidateSet.")
    if conditions is not None and not isinstance(conditions, dict):
        raise ValueError("conditions must be an object.")
    host = HostReference(
        genome_sha256=candidate_set.host_state.host_genome_sha256,
        profile_id=candidate_set.host_state.host_profile_id,
    )
    arms = [ExperimentArm(
        arm_id="host-control", role="control", target_host=host,
        phage_profile_ids=(), conditions=dict(conditions or {}),
        expected_readouts=expected_readouts,
    )]
    for index, profile_id in enumerate(candidate_set.selected_phage_profile_ids, start=1):
        arms.append(ExperimentArm(
            arm_id=f"single-phage-{index}", role="treatment", target_host=host,
            phage_profile_ids=(profile_id,), conditions=dict(conditions or {}),
            expected_readouts=expected_readouts,
        ))
    return experiment_spec_from_arms(
        arms, experiment_id=experiment_id, workflow=workflow, objective=objective,
        scientific_questions=tuple(
            f"Compare {arm.arm_id} ({arm.phage_profile_ids[0]}) with host-control for the declared readouts."
            for arm in arms[1:]
        ),
        source_references=(SourceReference(
            artifact_type="CandidateSet", artifact_id=candidate_set.record_id,
            content_sha256=candidate_set.content_sha256,
        ),),
        revision=revision, created_at=created_at,
    )

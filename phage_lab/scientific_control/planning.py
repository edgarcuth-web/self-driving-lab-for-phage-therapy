"""Deterministic scientific task decomposition for natural-phage screening."""

from ..artifacts import content_hash, parse_timestamp
from ..feature_artifact import validate_feature_artifact
from ..host_profile import HostProfile
from ..host_state import HostState, host_state_reference
from ..interaction_prediction import InteractionPrediction, phage_profile_sha256
from ..model_contract import ModelRequest
from ..padloc_adapter import PADLOC_VERSION
from ..phage_profile import PhageProfile
from .contracts import ArtifactReference, ScientificObjective, ScientificPlan, ScientificTask
from .registry import (
    MODEL_REQUEST_BUILDER_ID,
    NATURAL_PHAGE_RECOMMENDER_ID,
    PADLOC_HOST_DEFENSE_ID,
    TRUSTED_MODULES,
)


HOST_DEFENSE_ADMISSION_ID = "host_defense_admission"
HOST_DEFENSE_ADMISSION_VERSION = "1"


def _ref(artifact_type: str, artifact_id: str, content_sha256: str) -> ArtifactReference:
    return ArtifactReference(artifact_type, artifact_id, content_sha256)


def _objective_ref(objective: ScientificObjective) -> ArtifactReference:
    return _ref("ScientificObjective", objective.record_id, objective.content_sha256)


def _host_ref(host_state: HostState) -> ArtifactReference:
    return _ref("HostState", host_state.record_id, host_state.content_sha256)


def _host_profile_ref(profile: HostProfile) -> ArtifactReference:
    return _ref("HostProfile", profile.profile_id, content_hash(profile.to_dict()))


def _profile_ref(profile: PhageProfile) -> ArtifactReference:
    return _ref("PhageProfile", profile.profile_id, phage_profile_sha256(profile))


def _prediction_ref(prediction: InteractionPrediction) -> ArtifactReference:
    return _ref("InteractionPrediction", prediction.record_id, prediction.content_sha256)


def _request_ref(request: ModelRequest) -> ArtifactReference:
    return _ref("ModelRequest", request.record_id, request.content_sha256)


def _feature_ref(artifact: dict) -> ArtifactReference:
    return _ref("FeatureArtifact", artifact["artifact_id"], artifact["content_sha256"])


def _validate_inputs(
    objective: ScientificObjective,
    host_state: HostState,
    phage_profiles: list[PhageProfile] | tuple[PhageProfile, ...],
    predictions: list[InteractionPrediction] | tuple[InteractionPrediction, ...],
    *,
    created_at: str,
) -> tuple[dict[str, PhageProfile], dict[str, InteractionPrediction]]:
    if not isinstance(objective, ScientificObjective):
        raise ValueError("objective must be a ScientificObjective.")
    if objective.kind != "prioritize_natural_phages":
        raise ValueError("Objective kind is not supported by this scientific plan.")
    if not isinstance(host_state, HostState):
        raise ValueError("host_state must be a HostState.")
    exact_host = host_state_reference(host_state)
    if exact_host != objective.host_state:
        raise ValueError("Objective does not reference the exact supplied HostState.")
    if parse_timestamp(created_at, "created_at") < parse_timestamp(
        objective.created_at, "objective created_at"
    ):
        raise ValueError("ScientificPlan cannot precede its objective.")
    if (
        not isinstance(phage_profiles, (list, tuple))
        or any(not isinstance(item, PhageProfile) for item in phage_profiles)
    ):
        raise ValueError("phage_profiles must contain PhageProfile objects.")
    if (
        not isinstance(predictions, (list, tuple))
        or any(not isinstance(item, InteractionPrediction) for item in predictions)
    ):
        raise ValueError("predictions must contain InteractionPrediction objects.")

    profiles = {item.profile_id: item for item in phage_profiles}
    if len(profiles) != len(phage_profiles):
        raise ValueError("PhageProfile IDs must be unique.")

    by_phage: dict[str, InteractionPrediction] = {}
    for item in predictions:
        profile = profiles.get(item.phage_profile_id)
        if profile is None:
            raise ValueError("Prediction refers to a PhageProfile outside the supplied pool.")
        if item.phage_profile_id in by_phage:
            raise ValueError("Provide exactly one prediction per phage.")
        if item.host_state != exact_host:
            raise ValueError("Prediction does not match the exact HostState.")
        if item.phage_profile_sha256 != phage_profile_sha256(profile):
            raise ValueError("Prediction does not match the exact PhageProfile.")
        by_phage[item.phage_profile_id] = item
    return profiles, by_phage


def _validate_host_profile(profile: HostProfile, host_state: HostState) -> None:
    if not isinstance(profile, HostProfile):
        raise ValueError("host_profile must be a HostProfile.")
    if (
        profile.profile_id != host_state.host_profile_id
        or profile.genome.sha256 != host_state.host_genome_sha256
    ):
        raise ValueError("HostProfile does not match the exact supplied HostState.")


def _matching_padloc_artifact(
    feature_artifacts: tuple[dict, ...] | list[dict],
    host_state: HostState,
    host_profile: HostProfile,
) -> dict | None:
    if not isinstance(feature_artifacts, (tuple, list)):
        raise ValueError("feature_artifacts must be a list or tuple.")
    matches = []
    for artifact in feature_artifacts:
        validate_feature_artifact(artifact)
        if artifact["feature_set"] != "host_defense_systems":
            continue
        if artifact["analysis"]["tool"]["name"] != "PADLOC":
            continue
        subject = artifact["subject"]
        if (
            artifact["status"] != "complete"
            or artifact["analysis"]["tool"]["version"] != PADLOC_VERSION
            or subject["kind"] != "host_genome"
            or subject["id"] != host_state.record_id
            or subject["sequence_sha256"] != host_profile.genome.sha256
            or subject.get("source_record_sha256") != host_state.content_sha256
        ):
            raise ValueError(
                "PADLOC FeatureArtifact does not match the exact HostState/HostProfile."
            )
        matches.append(artifact)
    if len(matches) > 1:
        raise ValueError("Provide at most one matching PADLOC FeatureArtifact.")
    return matches[0] if matches else None


def _characterization_gate(
    host_profile: HostProfile,
    host_state: HostState,
    feature_artifacts: tuple[dict, ...] | list[dict],
) -> ScientificTask | None:
    _validate_host_profile(host_profile, host_state)
    artifact = _matching_padloc_artifact(feature_artifacts, host_state, host_profile)
    if host_profile.features["defense_systems"].status == "assessed":
        return None

    profile_ref = _host_profile_ref(host_profile)
    host_ref = _host_ref(host_state)
    if artifact is None:
        module = TRUSTED_MODULES[PADLOC_HOST_DEFENSE_ID]
        return ScientificTask(
            task_id="characterize-host-defense",
            kind="characterize_host_defense",
            state="ready",
            module_id=module.module_id,
            module_version=module.version,
            inputs=(profile_ref, host_ref),
            outputs=(),
            depends_on=(),
            reason=(
                "HostProfile defense_systems is unknown. Run the trusted PADLOC adapter "
                "against the exact registry-verified host genome before pair-level planning."
            ),
        )
    return ScientificTask(
        task_id="admit-host-defense-characterization",
        kind="admit_host_defense_characterization",
        state="handoff_required",
        module_id=HOST_DEFENSE_ADMISSION_ID,
        module_version=HOST_DEFENSE_ADMISSION_VERSION,
        inputs=(profile_ref, host_ref, _feature_ref(artifact)),
        outputs=(),
        depends_on=(),
        reason=(
            "A complete matching PADLOC FeatureArtifact exists, but computational output "
            "must be explicitly reviewed/mapped into a new HostProfile revision before use."
        ),
    )


def decompose_natural_phage_screening(
    objective: ScientificObjective,
    host_state: HostState,
    phage_profiles: list[PhageProfile] | tuple[PhageProfile, ...],
    predictions: list[InteractionPrediction] | tuple[InteractionPrediction, ...],
    *,
    plan_id: str,
    created_at: str,
    revision: int = 1,
    host_profile: HostProfile | None = None,
    feature_artifacts: tuple[dict, ...] | list[dict] = (),
) -> tuple[ScientificPlan, tuple[ModelRequest, ...]]:
    """Derive characterization/model handoffs and readiness without inventing evidence."""

    profiles, by_phage = _validate_inputs(
        objective, host_state, phage_profiles, predictions, created_at=created_at
    )
    required = tuple(sorted(
        profile_id for profile_id, profile in profiles.items()
        if profile.provenance.kind != "engineered"
    ))

    gate = None
    if host_profile is not None:
        gate = _characterization_gate(
            host_profile, host_state, feature_artifacts
        )
    elif feature_artifacts:
        raise ValueError("feature_artifacts require the exact HostProfile.")

    recommendation_module = TRUSTED_MODULES[NATURAL_PHAGE_RECOMMENDER_ID]
    base_inputs = [_host_ref(host_state)]
    if host_profile is not None:
        base_inputs.append(_host_profile_ref(host_profile))
    base_inputs.extend(_profile_ref(profiles[profile_id]) for profile_id in required)

    if gate is not None:
        recommendation_task = ScientificTask(
            task_id="prioritize-natural-phages",
            kind="prioritize_natural_phages",
            state="blocked",
            module_id=recommendation_module.module_id,
            module_version=recommendation_module.version,
            inputs=tuple(base_inputs),
            outputs=(),
            depends_on=(gate.task_id,),
            reason=(
                "Recommendation is blocked until host defense characterization is "
                "explicitly admitted; no pair-model handoffs are emitted before that gate."
            ),
        )
        return (
            ScientificPlan(
                plan_id=plan_id,
                revision=revision,
                objective=_objective_ref(objective),
                required_pair_profile_ids=required,
                tasks=(gate, recommendation_task),
                created_at=created_at,
            ),
            (),
        )

    request_module = TRUSTED_MODULES[MODEL_REQUEST_BUILDER_ID]
    handoff_tasks: list[ScientificTask] = []
    requests: list[ModelRequest] = []
    for profile_id in required:
        if profile_id in by_phage:
            continue
        profile = profiles[profile_id]
        request = request_module.call(
            host_state,
            profile,
            request_id=f"{plan_id}:model-request:{profile_id}",
            created_at=created_at,
        )
        requests.append(request)
        task_id = f"obtain-pair-prediction:{profile_id}"
        handoff_tasks.append(ScientificTask(
            task_id=task_id,
            kind="obtain_pair_prediction",
            state="handoff_required",
            module_id=request_module.module_id,
            module_version=request_module.version,
            inputs=(_host_ref(host_state), _profile_ref(profile)),
            outputs=(_request_ref(request),),
            depends_on=(),
            reason=(
                "The pair has no admitted InteractionPrediction. An exact ModelRequest "
                "has been prepared, but external model inference is not implemented or "
                "claimed by SDL."
            ),
            subject_phage_profile_id=profile_id,
        ))

    recommendation_inputs = list(base_inputs)
    recommendation_inputs.extend(
        _prediction_ref(by_phage[profile_id])
        for profile_id in required if profile_id in by_phage
    )
    recommendation_task = ScientificTask(
        task_id="prioritize-natural-phages",
        kind="prioritize_natural_phages",
        state="blocked" if handoff_tasks else "ready",
        module_id=recommendation_module.module_id,
        module_version=recommendation_module.version,
        inputs=tuple(recommendation_inputs),
        outputs=(),
        depends_on=tuple(task.task_id for task in handoff_tasks),
        reason=(
            "Recommendation is blocked because required pair predictions are missing; "
            "missing pairs are planning gaps, not negative labels."
            if handoff_tasks
            else
            "Every natural-first candidate has an explicit InteractionPrediction, "
            "including any not_estimated pair state; recommendation may run explicitly."
        ),
    )
    plan = ScientificPlan(
        plan_id=plan_id,
        revision=revision,
        objective=_objective_ref(objective),
        required_pair_profile_ids=required,
        tasks=tuple(handoff_tasks) + (recommendation_task,),
        created_at=created_at,
    )
    return plan, tuple(requests)

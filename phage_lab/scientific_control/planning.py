"""Deterministic scientific task decomposition for natural-phage screening."""

from ..artifacts import parse_timestamp
from ..host_state import HostState, host_state_reference
from ..interaction_prediction import InteractionPrediction, phage_profile_sha256
from ..model_contract import ModelRequest
from ..phage_profile import PhageProfile
from .contracts import (
    ArtifactReference,
    ScientificObjective,
    ScientificPlan,
    ScientificTask,
)
from .registry import (
    MODEL_REQUEST_BUILDER_ID,
    NATURAL_PHAGE_RECOMMENDER_ID,
    TRUSTED_MODULES,
)


def _ref(artifact_type: str, artifact_id: str, content_sha256: str) -> ArtifactReference:
    return ArtifactReference(
        artifact_type=artifact_type,
        artifact_id=artifact_id,
        content_sha256=content_sha256,
    )


def _objective_ref(objective: ScientificObjective) -> ArtifactReference:
    return _ref("ScientificObjective", objective.record_id, objective.content_sha256)


def _host_ref(host_state: HostState) -> ArtifactReference:
    return _ref("HostState", host_state.record_id, host_state.content_sha256)


def _profile_ref(profile: PhageProfile) -> ArtifactReference:
    return _ref("PhageProfile", profile.profile_id, phage_profile_sha256(profile))


def _prediction_ref(prediction: InteractionPrediction) -> ArtifactReference:
    return _ref(
        "InteractionPrediction",
        prediction.record_id,
        prediction.content_sha256,
    )


def _request_ref(request: ModelRequest) -> ArtifactReference:
    return _ref("ModelRequest", request.record_id, request.content_sha256)


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


def decompose_natural_phage_screening(
    objective: ScientificObjective,
    host_state: HostState,
    phage_profiles: list[PhageProfile] | tuple[PhageProfile, ...],
    predictions: list[InteractionPrediction] | tuple[InteractionPrediction, ...],
    *,
    plan_id: str,
    created_at: str,
    revision: int = 1,
) -> tuple[ScientificPlan, tuple[ModelRequest, ...]]:
    """Derive exact model handoffs and readiness without inventing predictions."""

    profiles, by_phage = _validate_inputs(
        objective,
        host_state,
        phage_profiles,
        predictions,
        created_at=created_at,
    )
    required = tuple(sorted(
        profile_id
        for profile_id, profile in profiles.items()
        if profile.provenance.kind != "engineered"
    ))

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

    recommendation_module = TRUSTED_MODULES[NATURAL_PHAGE_RECOMMENDER_ID]
    missing = tuple(task.subject_phage_profile_id for task in handoff_tasks)
    recommendation_inputs = [_host_ref(host_state)]
    recommendation_inputs.extend(_profile_ref(profiles[profile_id]) for profile_id in required)
    recommendation_inputs.extend(
        _prediction_ref(by_phage[profile_id])
        for profile_id in required
        if profile_id in by_phage
    )
    recommendation_task = ScientificTask(
        task_id="prioritize-natural-phages",
        kind="prioritize_natural_phages",
        state="blocked" if missing else "ready",
        module_id=recommendation_module.module_id,
        module_version=recommendation_module.version,
        inputs=tuple(recommendation_inputs),
        outputs=(),
        depends_on=tuple(task.task_id for task in handoff_tasks),
        reason=(
            "Recommendation is blocked because required pair predictions are missing; "
            "missing pairs are planning gaps, not negative labels."
            if missing
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

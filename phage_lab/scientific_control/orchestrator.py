"""Deterministic scientific orchestration over explicitly trusted modules."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable

from ..artifacts import parse_timestamp
from ..host_state import HostState, host_state_reference
from ..interaction_prediction import InteractionPrediction, phage_profile_sha256
from ..natural_phage_recommender import (
    CandidateSet,
    RecommendationPolicy,
    recommend_natural_phages,
)
from ..phage_profile import PhageProfile
from .contracts import (
    ArtifactReference,
    ModuleInvocation,
    ScientificClaim,
    ScientificObjective,
    ScientificProposal,
)


NATURAL_PHAGE_RECOMMENDER_ID = "natural_phage_recommender"
NATURAL_PHAGE_RECOMMENDER_VERSION = "1"


@dataclass(frozen=True)
class _TrustedModule:
    module_id: str
    version: str
    call: Callable


_TRUSTED_MODULES = MappingProxyType({
    NATURAL_PHAGE_RECOMMENDER_ID: _TrustedModule(
        module_id=NATURAL_PHAGE_RECOMMENDER_ID,
        version=NATURAL_PHAGE_RECOMMENDER_VERSION,
        call=recommend_natural_phages,
    ),
})

TRUSTED_MODULE_IDENTITIES = frozenset(
    (module.module_id, module.version) for module in _TRUSTED_MODULES.values()
)


def _objective_reference(objective: ScientificObjective) -> ArtifactReference:
    return ArtifactReference(
        artifact_type="ScientificObjective",
        artifact_id=objective.record_id,
        content_sha256=objective.content_sha256,
    )


def _candidate_set_reference(candidate_set: CandidateSet) -> ArtifactReference:
    return ArtifactReference(
        artifact_type="CandidateSet",
        artifact_id=candidate_set.record_id,
        content_sha256=candidate_set.content_sha256,
    )


def _module_inputs(
    host_state: HostState,
    phage_profiles: list[PhageProfile] | tuple[PhageProfile, ...],
    predictions: list[InteractionPrediction] | tuple[InteractionPrediction, ...],
) -> tuple[ArtifactReference, ...]:
    refs = [
        ArtifactReference(
            artifact_type="HostState",
            artifact_id=host_state.record_id,
            content_sha256=host_state.content_sha256,
        )
    ]
    refs.extend(
        ArtifactReference(
            artifact_type="PhageProfile",
            artifact_id=profile.profile_id,
            content_sha256=phage_profile_sha256(profile),
        )
        for profile in sorted(phage_profiles, key=lambda item: item.profile_id)
    )
    refs.extend(
        ArtifactReference(
            artifact_type="InteractionPrediction",
            artifact_id=prediction.record_id,
            content_sha256=prediction.content_sha256,
        )
        for prediction in sorted(predictions, key=lambda item: item.record_id)
    )
    return tuple(refs)


def _evidence_state(candidate_set: CandidateSet) -> str:
    selected = [
        entry
        for entry in candidate_set.evaluations
        if entry.disposition == "selected"
    ]
    if not selected:
        return "empty"
    bases = {entry.basis for entry in selected}
    if bases == {"predicted"}:
        return "predicted"
    if bases == {"exploration"}:
        return "exploration_only"
    return "mixed"


def _screening_claim(evidence_state: str) -> ScientificClaim:
    statements = {
        "predicted": (
            "Prioritize the selected existing phages for screening under the "
            "recorded natural-phage policy; this is not a treatment-performance claim."
        ),
        "mixed": (
            "Prioritize the selected existing phages for screening; some selections "
            "use comparable productive-infection lower bounds and others remain unresolved exploration."
        ),
        "exploration_only": (
            "Prioritize the selected existing phages only as unresolved screening candidates; "
            "no biological success claim is made."
        ),
        "empty": (
            "No eligible natural-phage screening candidate was selected; no biological "
            "failure conclusion is inferred."
        ),
    }
    return ScientificClaim(kind="screening_priority", statement=statements[evidence_state])


class ScientificOrchestrator:
    """Coordinate trusted science; never execute or mutate laboratory workflows."""

    def prioritize_natural_phages(
        self,
        objective: ScientificObjective,
        host_state: HostState,
        phage_profiles: list[PhageProfile] | tuple[PhageProfile, ...],
        predictions: list[InteractionPrediction] | tuple[InteractionPrediction, ...],
        *,
        candidate_set_id: str,
        proposal_id: str,
        policy: RecommendationPolicy | None = None,
        candidate_set_revision: int = 1,
        proposal_revision: int = 1,
        created_at: str,
    ) -> tuple[CandidateSet, ScientificProposal]:
        if not isinstance(objective, ScientificObjective):
            raise ValueError("objective must be a ScientificObjective.")
        if objective.kind != "prioritize_natural_phages":
            raise ValueError("Objective kind is not supported by this vertical slice.")
        if not isinstance(host_state, HostState):
            raise ValueError("host_state must be a HostState.")
        if host_state_reference(host_state) != objective.host_state:
            raise ValueError("Objective does not reference the exact supplied HostState.")
        if parse_timestamp(created_at, "created_at") < parse_timestamp(
            objective.created_at, "objective created_at"
        ):
            raise ValueError("ScientificProposal cannot precede its objective.")

        module = _TRUSTED_MODULES[NATURAL_PHAGE_RECOMMENDER_ID]
        candidate_set = module.call(
            host_state,
            phage_profiles,
            predictions,
            candidate_set_id=candidate_set_id,
            policy=policy,
            revision=candidate_set_revision,
            created_at=created_at,
        )
        candidate_ref = _candidate_set_reference(candidate_set)
        evidence_state = _evidence_state(candidate_set)
        invocation = ModuleInvocation(
            module_id=module.module_id,
            module_version=module.version,
            inputs=_module_inputs(host_state, phage_profiles, predictions),
            output=candidate_ref,
        )
        proposal = ScientificProposal(
            proposal_id=proposal_id,
            revision=proposal_revision,
            objective=_objective_reference(objective),
            invocation=invocation,
            candidate_set=candidate_ref,
            selected_phage_profile_ids=candidate_set.selected_phage_profile_ids,
            evidence_state=evidence_state,
            claim=_screening_claim(evidence_state),
            limitations=tuple(candidate_set.limitations) + (
                "Scientific control records screening intent only; it does not execute "
                "workflow steps or modify a frozen ExperimentSpec.",
            ),
            created_at=created_at,
        )
        return candidate_set, proposal

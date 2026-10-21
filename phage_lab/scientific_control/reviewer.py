"""Deterministic adversarial review for scientific-control proposals."""

from ..host_state import HostStateReference
from ..natural_phage_recommender import CandidateSet
from .contracts import (
    ArtifactReference,
    ReviewFinding,
    ScientificObjective,
    ScientificProposal,
    ScientificReview,
)
from .registry import TRUSTED_MODULE_IDENTITIES


def _ref(artifact_type: str, artifact_id: str, content_sha256: str) -> ArtifactReference:
    return ArtifactReference(
        artifact_type=artifact_type,
        artifact_id=artifact_id,
        content_sha256=content_sha256,
    )


def _derive_evidence_state(candidate_set: CandidateSet) -> str:
    selected = [entry for entry in candidate_set.evaluations if entry.disposition == "selected"]
    if not selected:
        return "empty"
    bases = {entry.basis for entry in selected}
    if bases == {"predicted"}:
        return "predicted"
    if bases == {"exploration"}:
        return "exploration_only"
    return "mixed"


class ScientificReviewer:
    """Review evidence semantics and lineage without changing source artifacts."""

    def review(
        self,
        objective: ScientificObjective,
        proposal: ScientificProposal,
        candidate_set: CandidateSet,
        *,
        review_id: str,
        reviewed_at: str,
        revision: int = 1,
    ) -> ScientificReview:
        if not isinstance(objective, ScientificObjective):
            raise ValueError("objective must be a ScientificObjective.")
        if not isinstance(proposal, ScientificProposal):
            raise ValueError("proposal must be a ScientificProposal.")
        if not isinstance(candidate_set, CandidateSet):
            raise ValueError("candidate_set must be a CandidateSet.")

        findings: list[ReviewFinding] = []

        expected_objective = _ref(
            "ScientificObjective", objective.record_id, objective.content_sha256
        )
        if proposal.objective != expected_objective:
            findings.append(ReviewFinding(
                code="objective_lineage_mismatch",
                severity="error",
                message="Proposal does not bind the exact ScientificObjective revision.",
            ))

        expected_candidate_set = _ref(
            "CandidateSet", candidate_set.record_id, candidate_set.content_sha256
        )
        if proposal.candidate_set != expected_candidate_set:
            findings.append(ReviewFinding(
                code="candidate_set_lineage_mismatch",
                severity="error",
                message="Proposal does not bind the exact CandidateSet revision.",
            ))

        if (
            proposal.invocation.module_id,
            proposal.invocation.module_version,
        ) not in TRUSTED_MODULE_IDENTITIES:
            findings.append(ReviewFinding(
                code="untrusted_scientific_module",
                severity="error",
                message="Proposal cites a scientific module outside the explicit trusted registry.",
            ))

        if proposal.invocation.output != proposal.candidate_set:
            findings.append(ReviewFinding(
                code="module_output_mismatch",
                severity="error",
                message="Recorded module output does not match the proposal CandidateSet.",
            ))

        if candidate_set.host_state != objective.host_state:
            findings.append(ReviewFinding(
                code="host_state_lineage_mismatch",
                severity="error",
                message="CandidateSet and ScientificObjective reference different HostState content.",
            ))

        if proposal.selected_phage_profile_ids != candidate_set.selected_phage_profile_ids:
            findings.append(ReviewFinding(
                code="selection_lineage_mismatch",
                severity="error",
                message="Proposal selection differs from the immutable CandidateSet selection.",
            ))

        selected = [
            entry for entry in candidate_set.evaluations
            if entry.phage_profile_id in candidate_set.selected_phage_profile_ids
        ]
        if any(entry.basis in ("engineered", "missing_prediction") for entry in selected):
            findings.append(ReviewFinding(
                code="ineligible_selected_candidate",
                severity="error",
                message="An engineered or missing-prediction candidate cannot be approved by the natural-first slice.",
            ))

        derived_state = _derive_evidence_state(candidate_set)
        if proposal.evidence_state != derived_state:
            findings.append(ReviewFinding(
                code="evidence_state_mismatch",
                severity="error",
                message="Proposal evidence_state does not match the selected CandidateSet evidence.",
            ))

        if proposal.claim.kind != "screening_priority":
            findings.append(ReviewFinding(
                code="unsupported_semantic_upgrade",
                severity="error",
                message=(
                    "This vertical slice supports screening priority only; probability, "
                    "efficacy, treatment or causal claims require separate validated evidence."
                ),
            ))

        if derived_state == "exploration_only":
            findings.append(ReviewFinding(
                code="exploration_only",
                severity="warning",
                message=(
                    "All selected candidates are unresolved exploration; approval means "
                    "screening priority only and does not establish productive infection."
                ),
            ))
        elif derived_state == "mixed":
            findings.append(ReviewFinding(
                code="mixed_evidence",
                severity="warning",
                message=(
                    "Selection mixes prediction-based priority with unresolved exploration; "
                    "the two bases must remain distinguishable downstream."
                ),
            ))
        elif derived_state == "predicted":
            findings.append(ReviewFinding(
                code="prediction_based_screening",
                severity="info",
                message=(
                    "Selection is based on comparable productive-infection prediction lower "
                    "bounds under the recorded CandidateSet policy."
                ),
            ))
        else:
            findings.append(ReviewFinding(
                code="empty_selection",
                severity="info",
                message="No eligible screening candidate was selected.",
            ))

        findings.append(ReviewFinding(
            code="execution_boundary",
            severity="info",
            message=(
                "This review addresses scientific screening intent only; it does not dispatch "
                "workflow execution or establish a biological outcome."
            ),
        ))

        if any(item.severity == "error" for item in findings):
            decision = "revision_required"
        elif not candidate_set.selected_phage_profile_ids:
            decision = "abstained"
        else:
            decision = "approved"

        return ScientificReview(
            review_id=review_id,
            revision=revision,
            proposal=_ref("ScientificProposal", proposal.record_id, proposal.content_sha256),
            decision=decision,
            findings=tuple(findings),
            reviewed_at=reviewed_at,
        )

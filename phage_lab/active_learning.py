"""Bounded feedback-driven screening, without fitting a biological model.

The fixed CandidateSet is a campaign pool, not a mutable ranking. Reviews retire
single-phage screening questions in one explicit assay context. Inconclusive or
conflicting reviews require human review; cocktail results never retire members.
"""

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

from .artifacts import (
    ContentAddressed,
    atomic_write_json,
    parse_timestamp as _time,
    read_json,
    require_text as _text,
)

from .experiment_spec import (
    ExperimentSpec, SourceReference, experiment_spec_from_dict,
)
from .failure_attribution import (
    FailureAttribution, failure_attribution_from_dict,
)
from .natural_phage_recommender import (
    CandidateSet, RecommendationPolicy, candidate_set_from_dict, _select,
)

SCHEMA_VERSION = 1
POLICY_NAME = "feedback-screening"
POLICY_VERSION = "1"


def _reference(kind, artifact):
    return SourceReference(kind, artifact.record_id, artifact.content_sha256)


def _context(arm):
    return (arm.target_host, arm.conditions, arm.expected_readouts)


def _check_spec(spec, pool, anchor):
    """Compare explicit context; shared identity alone is insufficient."""
    source = _reference("CandidateSet", pool)
    sources = [r for r in spec.source_references if r.artifact_type == "CandidateSet"]
    if sources != [source]:
        raise ValueError("Screening spec must reference the exact source CandidateSet.")
    if _time(spec.created_at) < _time(pool.created_at):
        raise ValueError("Screening spec cannot precede its CandidateSet.")
    if (spec.target_host.profile_id != pool.host_state.host_profile_id
            or spec.target_host.genome_sha256 != pool.host_state.host_genome_sha256):
        raise ValueError("Screening spec host does not match the CandidateSet HostState.")
    eligible = {e.phage_profile_id for e in pool.evaluations if e.disposition != "excluded"}
    if not set(spec.member_phage_profile_ids) <= eligible:
        raise ValueError("Screening spec contains an ineligible or out-of-pool member.")
    controls = [a for a in spec.arms if a.role == "control"]
    treatments = [a for a in spec.arms if a.role == "treatment"]
    if len(controls) != 1 or controls[0].phage_profile_ids or not treatments:
        raise ValueError("Screening context requires one host-only control and treatment arms.")
    template = anchor.arms[0]
    if any(_context(a) != _context(template) for a in spec.arms):
        raise ValueError("Screening conditions/readouts/host must match the fixed assay context.")
    if (spec.objective != anchor.objective or spec.workflow != anchor.workflow
            or spec.execution_constraints != anchor.execution_constraints):
        raise ValueError("Screening objective/workflow/constraints must match the fixed context.")


@dataclass(frozen=True)
class ActiveLearningDecision(ContentAddressed):
    decision_id: str
    revision: int
    candidate_set: CandidateSet
    screening_spec: ExperimentSpec
    criterion: str
    feedback: tuple[FailureAttribution, ...]
    policy: RecommendationPolicy
    created_at: str
    previous_decision: SourceReference | None = None
    schema_version: int = SCHEMA_VERSION
    _source_hashes: tuple = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        _text(self.decision_id, "decision_id")
        _text(self.criterion, "criterion")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("revision must be a positive integer.")
        if type(self.schema_version) is not int or self.schema_version != SCHEMA_VERSION:
            raise ValueError("Unsupported ActiveLearningDecision schema_version.")
        if not isinstance(self.candidate_set, CandidateSet):
            raise ValueError("candidate_set must be a CandidateSet.")
        if not isinstance(self.screening_spec, ExperimentSpec):
            raise ValueError("screening_spec must be an ExperimentSpec.")
        if not isinstance(self.policy, RecommendationPolicy):
            raise ValueError("policy must be a RecommendationPolicy.")
        # Frozen dataclasses may still contain mutable nested dictionaries.
        candidate_set_from_dict(self.candidate_set.to_dict())
        experiment_spec_from_dict(self.screening_spec.to_dict())
        _check_spec(self.screening_spec, self.candidate_set, self.screening_spec)
        if (self.screening_spec.member_phage_profile_ids
                != self.candidate_set.selected_phage_profile_ids
                or len([a for a in self.screening_spec.arms if a.role == "treatment"])
                != len(self.candidate_set.selected_phage_profile_ids)
                or any(len(a.phage_profile_ids) != 1 for a in self.screening_spec.arms
                       if a.role == "treatment")):
            raise ValueError("Initial screening spec must test the original selected single phages.")
        if _time(self.created_at) < _time(self.screening_spec.created_at):
            raise ValueError("Decision cannot precede its screening spec.")
        if self.previous_decision is not None:
            if (not isinstance(self.previous_decision, SourceReference)
                    or self.previous_decision.artifact_type != "ActiveLearningDecision"
                    or self.previous_decision.artifact_id == self.record_id):
                raise ValueError("previous_decision must reference a different ActiveLearningDecision.")
        if not isinstance(self.feedback, tuple) or any(
            not isinstance(f, FailureAttribution) for f in self.feedback
        ):
            raise ValueError("feedback must be a tuple of FailureAttribution objects.")
        ids = [f.record_id for f in self.feedback]
        if ids != sorted(ids) or len(set(ids)) != len(ids):
            raise ValueError("Feedback must have unique, sorted record IDs.")
        if len({f.attribution_id for f in self.feedback}) != len(self.feedback):
            raise ValueError("Competing attribution revisions require explicit review.")
        reviewed_arms = set()
        spec_hashes = {self.screening_spec.spec_id: self.screening_spec.content_sha256}
        for review in self.feedback:
            failure_attribution_from_dict(review.to_dict())
            spec = review.experiment_spec
            _check_spec(spec, self.candidate_set, self.screening_spec)
            if spec.spec_id in spec_hashes and spec_hashes[spec.spec_id] != spec.content_sha256:
                raise ValueError("One ExperimentSpec ID cannot refer to different contents.")
            spec_hashes[spec.spec_id] = spec.content_sha256
            if _time(spec.created_at) < _time(self.screening_spec.created_at):
                raise ValueError("Feedback spec cannot precede the initial screening spec.")
            if _time(review.assessed_at) > _time(self.created_at):
                raise ValueError("Decision cannot use future feedback.")
            if review.criterion != self.criterion:
                raise ValueError("Feedback criterion must match the declared screening criterion.")
            key = (spec.spec_id, review.target_arm_id)
            if key in reviewed_arms:
                raise ValueError("Duplicate reviews of the same experiment arm require explicit review.")
            reviewed_arms.add(key)
        object.__setattr__(self, "_source_hashes", self._current_source_hashes())

    def _current_source_hashes(self):
        return (self.candidate_set.content_sha256, self.screening_spec.content_sha256,
                tuple(f.content_sha256 for f in self.feedback))

    @property
    def record_id(self):
        return f"{self.decision_id}:v{self.revision}"

    def _feedback_evaluations(self):
        reviews_by_profile = {}
        for review in self.feedback:
            target = next(a for a in review.experiment_spec.arms
                          if a.arm_id == review.target_arm_id)
            if len(target.phage_profile_ids) == 1:
                reviews_by_profile.setdefault(target.phage_profile_ids[0], []).append(review)
        entries = []
        for entry in self.candidate_set.evaluations:
            reviews = reviews_by_profile.get(entry.phage_profile_id, [])
            outcomes = {f.outcome for f in reviews}
            if entry.disposition == "excluded":
                state = "excluded"
                reason = "Source CandidateSet exclusion remains in force."
            elif not outcomes:
                state = "untested"
                reason = "No single-phage review in the supplied campaign feedback."
            elif "inconclusive" in outcomes or len(outcomes) > 1:
                state = "needs_review"
                reason = "Inconclusive or conflicting reviews; no automatic repeat or biological verdict."
            elif outcomes == {"failure_observed"}:
                state = "reviewed_failure"
                reason = "Declared criterion failed in this context; retire this screening question only."
            else:
                state = "reviewed_no_failure"
                reason = "No failure observed against this criterion; retire this screening question only."
            entries.append({
                "phage_profile_id": entry.phage_profile_id,
                "state": state, "reason": reason,
                "feedback_references": [_reference("FailureAttribution", f).to_dict() for f in reviews],
            })
        return tuple(entries)

    def _selection(self):
        """Derive feedback state, selection and status once per public access/export."""
        feedback_entries = self._feedback_evaluations()
        available = {e["phage_profile_id"] for e in feedback_entries
                     if e["state"] == "untested"}
        selected_ids = _select([e for e in self.candidate_set.evaluations
                                if e.phage_profile_id in available], self.policy)
        selected = set(selected_ids)
        source_entries = {e.phage_profile_id: e for e in self.candidate_set.evaluations}
        entries = []
        for entry in feedback_entries:
            source = source_entries[entry["phage_profile_id"]]
            if entry["phage_profile_id"] in selected:
                disposition = "selected"
                reason = "Selected by the recorded lower-bound/exploration budget policy."
            elif entry["state"] == "untested":
                disposition = "deferred"
                reason = "Outside this round's budget; no negative conclusion."
            else:
                disposition = "withheld"
                reason = entry["reason"]
            entries.append({**entry, "disposition": disposition,
                            "selection_basis": source.basis, "selection_reason": reason})
        if not selected_ids:
            status = "abstained"
        elif not self.feedback:
            status = "no_feedback"
        elif all(e["state"] in ("untested", "excluded") for e in entries):
            status = "no_actionable_feedback"
        else:
            status = "feedback_applied"
        return selected_ids, tuple(entries), status

    @property
    def selected_phage_profile_ids(self):
        return self._selection()[0]

    @property
    def evaluations(self):
        return self._selection()[1]

    @property
    def status(self):
        return self._selection()[2]

    @property
    def limitations(self):
        return (
            "Feedback-driven screening heuristic; no model fitting, probability update or information-gain guarantee.",
            "Retirement is specific to the exact pool, supplied assay context and declared criterion; it is not permanent resistance or efficacy.",
            "Inconclusive/conflicting reviews require explicit review; no automatic retest or causal inference.",
            "Cocktail reviews are retained but never allocated to individual members.",
            "Declared matching conditions cannot establish that physical host state remained unchanged; no H(t) is updated.",
            "Feedback history is explicit; pass previous_decision to carry it forward. Missing results remain unknown.",
            "Source CandidateSet exclusions and prediction comparability limits remain in force; no safety or material readiness assessment.",
        )

    def _content_dict(self):
        if self._current_source_hashes() != self._source_hashes:
            raise ValueError("Decision source snapshots were mutated; create a new decision.")
        selected, evaluations, status = self._selection()
        return {
            "schema_version": self.schema_version, "record_id": self.record_id,
            "decision_id": self.decision_id, "revision": self.revision,
            "candidate_set": self.candidate_set.to_dict(),
            "screening_spec": self.screening_spec.to_dict(), "criterion": self.criterion,
            "feedback": [f.to_dict() for f in self.feedback],
            "policy": {**self.policy.to_dict(), "name": POLICY_NAME, "version": POLICY_VERSION},
            "created_at": self.created_at,
            "previous_decision": self.previous_decision.to_dict() if self.previous_decision else None,
            "evaluations": list(evaluations),
            "selected_phage_profile_ids": list(selected),
            "status": status, "limitations": list(self.limitations),
        }


def plan_next_screen(candidate_set, screening_spec, feedback, *, decision_id, criterion,
                     policy=None, previous_decision=None, revision=1, created_at=None):
    """Carry previous feedback forward; never silently replace a reviewed artifact."""
    if not isinstance(candidate_set, CandidateSet) or not isinstance(screening_spec, ExperimentSpec):
        raise ValueError("An exact CandidateSet and screening ExperimentSpec are required.")
    if not isinstance(feedback, (list, tuple)) or any(
        not isinstance(f, FailureAttribution) for f in feedback
    ):
        raise ValueError("feedback must be a list or tuple of FailureAttribution objects.")
    pool = candidate_set_from_dict(candidate_set.to_dict())
    anchor = experiment_spec_from_dict(screening_spec.to_dict())
    history = {}
    previous_reference = None
    created_at = created_at or datetime.now(timezone.utc).isoformat()
    if previous_decision is not None:
        if not isinstance(previous_decision, ActiveLearningDecision):
            raise ValueError("previous_decision must be an ActiveLearningDecision.")
        previous = active_learning_decision_from_dict(previous_decision.to_dict())
        if (previous.candidate_set.content_sha256 != pool.content_sha256
                or previous.screening_spec.content_sha256 != anchor.content_sha256
                or previous.criterion != criterion):
            raise ValueError("Previous decision must belong to the exact campaign and criterion.")
        if _time(created_at) < _time(previous.created_at):
            raise ValueError("Decision cannot precede its previous decision.")
        history.update((f.record_id, f) for f in previous.feedback)
        previous_reference = _reference("ActiveLearningDecision", previous)
        if policy is None:
            policy = previous.policy
    for review in feedback:
        review = failure_attribution_from_dict(review.to_dict())
        if review.record_id in history and history[review.record_id].content_sha256 != review.content_sha256:
            raise ValueError("Feedback record ID cannot replace different historical content.")
        if review.record_id in history and previous_decision is None:
            raise ValueError("Duplicate feedback record ID.")
        history[review.record_id] = review
    return ActiveLearningDecision(
        decision_id=decision_id, revision=revision, candidate_set=pool,
        screening_spec=anchor, criterion=criterion,
        feedback=tuple(history[key] for key in sorted(history)),
        policy=policy if policy is not None else pool.policy,
        created_at=created_at, previous_decision=previous_reference,
    )


def active_learning_decision_from_dict(data):
    expected = {
        "schema_version", "record_id", "decision_id", "revision", "candidate_set",
        "screening_spec", "criterion", "feedback", "policy", "created_at",
        "previous_decision", "evaluations", "selected_phage_profile_ids", "status",
        "limitations", "content_sha256",
    }
    if not isinstance(data, dict) or set(data) != expected:
        raise ValueError("ActiveLearningDecision has missing or unknown fields.")
    policy = data["policy"]
    if (not isinstance(policy, dict)
            or set(policy) != {"name", "version", "max_candidates", "exploration_slots"}
            or (policy["name"], policy["version"]) != (POLICY_NAME, POLICY_VERSION)):
        raise ValueError("Unsupported active-learning policy.")
    if not isinstance(data["feedback"], list):
        raise ValueError("feedback must be an array.")
    reference = data["previous_decision"]
    if reference is not None:
        if not isinstance(reference, dict) or set(reference) != {
            "artifact_type", "artifact_id", "content_sha256",
        }:
            raise ValueError("Invalid previous_decision reference.")
        reference = SourceReference(**reference)
    result = ActiveLearningDecision(
        decision_id=data["decision_id"], revision=data["revision"],
        candidate_set=candidate_set_from_dict(data["candidate_set"]),
        screening_spec=experiment_spec_from_dict(data["screening_spec"]),
        criterion=data["criterion"],
        feedback=tuple(failure_attribution_from_dict(f) for f in data["feedback"]),
        policy=RecommendationPolicy(policy["max_candidates"], policy["exploration_slots"]),
        created_at=data["created_at"], previous_decision=reference,
        schema_version=data["schema_version"],
    )
    if result.to_dict() != data:
        raise ValueError("ActiveLearningDecision derived fields or content hash mismatch.")
    return result


def write_active_learning_decision(decision, path: Path):
    data = decision.to_dict()
    active_learning_decision_from_dict(data)
    atomic_write_json(data, path)


def load_active_learning_decision(path: Path):
    data = read_json(path, 'ActiveLearningDecision')
    return active_learning_decision_from_dict(data)


def experiment_spec_from_active_learning(decision, *, experiment_id, created_at=None):
    """Preserve the campaign context and exact decision; never dispatch devices."""
    decision = active_learning_decision_from_dict(decision.to_dict())
    selected = decision.selected_phage_profile_ids
    if not selected:
        raise ValueError("Cannot create an experiment from an abstained decision.")
    created_at = created_at or datetime.now(timezone.utc).isoformat()
    if _time(created_at) < _time(decision.created_at):
        raise ValueError("ExperimentSpec cannot precede its active-learning decision.")
    anchor = decision.screening_spec
    if experiment_id == anchor.experiment_id or any(
        f.experiment_spec.experiment_id == experiment_id for f in decision.feedback
    ):
        raise ValueError("Next experiment must have a new experiment_id.")
    control = next(a for a in anchor.arms if a.role == "control")
    template = next(a for a in anchor.arms if a.role == "treatment")
    arms = (control,) + tuple(replace(
        template, arm_id=f"single-phage-{index}", phage_profile_ids=(profile_id,),
        conditions=dict(template.conditions),
    ) for index, profile_id in enumerate(selected, start=1))
    # Avoid a caller-chosen control arm ID colliding with generated treatment IDs.
    arms = (replace(control, arm_id="host-control", conditions=dict(control.conditions)),) + arms[1:]
    return replace(
        anchor, experiment_id=experiment_id, revision=1, arms=arms,
        scientific_questions=tuple(
            f"Compare {a.phage_profile_ids[0]} with host-control against the declared screening criterion."
            for a in arms[1:]
        ),
        source_references=(
            _reference("CandidateSet", decision.candidate_set),
            _reference("ActiveLearningDecision", decision),
            SourceReference("ExperimentSpec", anchor.spec_id, anchor.content_sha256),
        ), created_at=created_at,
    )

"""Software contract fixtures only; these are not experimental evidence."""

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from phage_lab.__main__ import main
from phage_lab.active_learning import (
    active_learning_decision_from_dict, experiment_spec_from_active_learning,
    load_active_learning_decision, plan_next_screen, write_active_learning_decision,
)
from phage_lab.experiment_spec import ExperimentStep, load_experiment_spec, write_experiment_spec
from phage_lab.failure_attribution import failure_attribution_from_results, write_failure_attribution
from phage_lab.material_batch import new_material_batch
from phage_lab.natural_phage_recommender import (
    RecommendationPolicy, experiment_spec_from_candidate_set, recommend_natural_phages,
    write_candidate_set,
)
from phage_lab.phenotype import phenotype_from_measurements, phenotype_comparison_from_phenotypes
from test_material_measurement_phenotype import physical_measurement, STAMP
from test_natural_phage_recommender import phage, prediction, recommend, state, T3

LATER = "2026-10-16T19:31:00+00:00"
LATEST = "2026-10-16T19:32:00+00:00"
CRITERION = "Fixture criterion, explicitly assessed; no biological claim."


def screen(pool):
    return experiment_spec_from_candidate_set(
        pool, experiment_id="screen-one", workflow={"measure": ()},
        objective="Contract-path comparison only.", expected_readouts=("device_result",),
        conditions={"assay_context": "fixture"}, created_at=T3,
    )


def review(spec, arm_id="single-phage-1", outcome="failure_observed", *,
           name="review", timestamp=STAMP, comparison=True):
    """Fabricated test doubles, confined to tests and never delivered as evidence."""
    batches = [new_material_batch(
        "fixture-host-batch", material_type="host", profile_id=spec.target_host.profile_id,
        source_kind="local_collection", source_reference="fixture://host",
        quality_status="released", quality_evidence=("fixture-qc",), created_at=T3,
    )]
    batches += [new_material_batch(
        f"fixture-phage-{index}", material_type="phage", profile_id=profile_id,
        source_kind="acquired", source_reference="fixture://phage",
        quality_status="released", quality_evidence=("fixture-qc",), created_at=T3,
    ) for index, profile_id in enumerate(spec.member_phage_profile_ids)]
    arm_ids = ("host-control", arm_id) if comparison else (arm_id,)
    measurements = [replace(physical_measurement(
        spec=spec, batches=batches, arm_id=key, measurement_id=f"{name}-measurement-{key}",
    ), recorded_at=timestamp, created_at=timestamp) for key in arm_ids]
    phenotypes = [phenotype_from_measurements(
        spec, [measurement], arm_id=measurement.experiment_arm_id,
        phenotype_id=f"{name}-phenotype-{measurement.experiment_arm_id}",
        phenotype_type="declared-response", outcome="negative",
        interpretation="Test fixture only; polarity does not determine failure.",
        assessor_name="fixture-reviewer", assessor_version="1", assessed_at=timestamp,
    ) for measurement in measurements]
    comparisons = [phenotype_comparison_from_phenotypes(
        spec, *phenotypes, comparison_id=f"{name}-comparison",
        comparison_type="declared", outcome="fixture-comparison",
        interpretation="Test fixture only.", assessor_name="fixture-reviewer",
        assessor_version="1", assessed_at=timestamp,
    )] if comparison else []
    return failure_attribution_from_results(
        spec, measurements, phenotypes, comparisons=comparisons,
        attribution_id=name, target_arm_id=arm_id, outcome=outcome, criterion=CRITERION,
        interpretation="Explicit fixture review only.", assessor_name="fixture-reviewer",
        assessor_version="1", limitations=("Test fixture, no biological claim.",),
        assessed_at=timestamp,
    )


class ActiveLearningTests(unittest.TestCase):
    def setUp(self):
        self.profiles = [phage(name) for name in "abcd"]
        self.pool = recommend(self.profiles, [prediction(p) for p in self.profiles],
                              policy=RecommendationPolicy(2, 1))
        self.spec = screen(self.pool)

    def decide(self, feedback=(), **changes):
        values = dict(decision_id="round-two", criterion=CRITERION, created_at=STAMP)
        values.update(changes)
        return plan_next_screen(self.pool, self.spec, feedback, **values)

    def states(self, decision):
        return {e["phage_profile_id"]: e["state"] for e in decision.evaluations}

    def test_no_feedback_preserves_original_selection_without_claiming_learning(self):
        decision = self.decide()
        self.assertEqual(decision.status, "no_feedback")
        self.assertEqual(decision.selected_phage_profile_ids, self.pool.selected_phage_profile_ids)
        self.assertTrue(all(e["state"] == "untested" for e in decision.evaluations))

    def test_explicit_failure_changes_next_selection_and_preserves_exact_inputs(self):
        feedback = review(self.spec)
        before = self.pool.to_dict()
        decision = self.decide([feedback])
        self.assertEqual(decision.status, "feedback_applied")
        self.assertEqual(decision.selected_phage_profile_ids, ("b:v1", "c:v1"))
        self.assertEqual(self.states(decision)["a:v1"], "reviewed_failure")
        self.assertEqual(self.states(decision)["d:v1"], "untested")
        self.assertEqual(decision.feedback[0].content_sha256, feedback.content_sha256)
        entries = {e["phage_profile_id"]: e for e in decision.evaluations}
        self.assertEqual(entries["a:v1"]["disposition"], "withheld")
        self.assertEqual(entries["b:v1"]["disposition"], "selected")
        self.assertEqual(entries["d:v1"]["disposition"], "deferred")
        self.assertIn("budget", entries["d:v1"]["selection_reason"])
        self.assertEqual(self.pool.to_dict(), before)
        self.assertEqual(decision.candidate_set.to_dict(), before)

    def test_no_failure_is_reviewed_not_an_efficacy_estimate(self):
        decision = self.decide([review(self.spec, outcome="failure_not_observed")])
        self.assertEqual(self.states(decision)["a:v1"], "reviewed_no_failure")
        self.assertNotIn("a:v1", decision.selected_phage_profile_ids)
        self.assertIsNone(decision.candidate_set.evaluations[0].prediction
                          .productive_infection.probability)

    def test_inconclusive_requires_review_and_does_not_become_failure(self):
        decision = self.decide([review(self.spec, outcome="inconclusive")])
        self.assertEqual(self.states(decision)["a:v1"], "needs_review")
        self.assertEqual(decision.feedback[0].outcome, "inconclusive")
        self.assertNotIn("a:v1", decision.selected_phage_profile_ids)

    def test_conflicting_independent_reviews_require_review_not_last_write_wins(self):
        repeat_spec = replace(self.spec, experiment_id="independent-repeat")
        left = review(self.spec, name="left")
        right = review(repeat_spec, name="right", outcome="failure_not_observed")
        decision = self.decide([left, right])
        self.assertEqual(self.states(decision)["a:v1"], "needs_review")
        self.assertEqual(decision.feedback, tuple(sorted([left, right], key=lambda f: f.record_id)))
        reordered = self.decide([right, left])
        self.assertEqual(reordered.content_sha256, decision.content_sha256)

    def test_cocktail_feedback_never_retires_individual_members(self):
        target = replace(self.spec.arms[1], phage_profile_ids=("a:v1", "b:v1"))
        cocktail_spec = replace(self.spec, experiment_id="cocktail-review", arms=(self.spec.arms[0], target))
        decision = self.decide([review(cocktail_spec)])
        self.assertEqual(decision.status, "no_actionable_feedback")
        self.assertEqual(decision.selected_phage_profile_ids, ("a:v1", "b:v1"))
        self.assertTrue(all(e["state"] == "untested" for e in decision.evaluations))
        self.assertEqual(len(decision.feedback), 1)

    def test_remaining_predictions_keep_lower_bound_and_exploration_policy(self):
        a, b, c, d = self.profiles
        pool = recommend([a, b, c, d], [prediction(a, 0.7), prediction(b, 0.6),
                                      prediction(c), prediction(d)],
                         policy=RecommendationPolicy(2, 1))
        spec = screen(pool)
        self.assertEqual(pool.selected_phage_profile_ids, ("a:v1", "c:v1"))
        decision = plan_next_screen(pool, spec, [review(spec)], decision_id="mixed",
                                    criterion=CRITERION, created_at=STAMP)
        self.assertEqual(decision.selected_phage_profile_ids, ("b:v1", "c:v1"))

    def test_missing_prediction_stays_excluded(self):
        a, b = self.profiles[:2]
        pool = recommend([a, b], [prediction(a)])
        spec = screen(pool)
        decision = plan_next_screen(pool, spec, [review(spec)], decision_id="empty",
                                    criterion=CRITERION, created_at=STAMP)
        self.assertEqual(decision.status, "abstained")
        self.assertEqual(self.states(decision)["b:v1"], "excluded")
        with self.assertRaisesRegex(ValueError, "abstained"):
            experiment_spec_from_active_learning(decision, experiment_id="no-experiment")

    def test_round_trip_checks_derived_selection_reasons_status_and_hash(self):
        decision = self.decide([review(self.spec)])
        self.assertEqual(active_learning_decision_from_dict(decision.to_dict()), decision)
        for field, value in (("content_sha256", "0" * 64), ("status", "no_feedback"),
                             ("selected_phage_profile_ids", ["a:v1"]), ("evaluations", []),
                             ("limitations", []), ("schema_version", True), ("extra", 1)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                active_learning_decision_from_dict({**decision.to_dict(), field: value})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "decision.json"
            write_active_learning_decision(decision, path)
            self.assertEqual(load_active_learning_decision(path), decision)

    def test_future_feedback_and_backward_decision_or_spec_time_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "future feedback"):
            self.decide([review(self.spec, timestamp=LATER)])
        with self.assertRaisesRegex(ValueError, "precede its screening"):
            self.decide(created_at="2026-01-02T00:00:00+00:00")
        with self.assertRaisesRegex(ValueError, "timezone"):
            self.decide(created_at="2026-10-16T20:00:00")
        decision = self.decide([review(self.spec)])
        with self.assertRaisesRegex(ValueError, "precede its active"):
            experiment_spec_from_active_learning(decision, experiment_id="early", created_at=T3)

    def test_different_contexts_sources_criteria_and_host_are_rejected(self):
        variants = [
            replace(self.spec, experiment_id="wrong-objective", objective="Other objective"),
            replace(self.spec, experiment_id="wrong-workflow", workflow=(replace(self.spec.workflow[0], name="other"),)),
            replace(self.spec, experiment_id="wrong-source", source_references=(
                replace(self.spec.source_references[0], content_sha256="f" * 64),)),
            replace(self.spec, experiment_id="no-source", source_references=()),
            replace(self.spec, experiment_id="wrong-condition", arms=tuple(
                replace(a, conditions={"assay_context": "other"}) for a in self.spec.arms)),
            replace(self.spec, experiment_id="wrong-readout", arms=tuple(
                replace(a, expected_readouts=("other",)) for a in self.spec.arms)),
            replace(self.spec, experiment_id="wrong-host", arms=tuple(
                replace(a, target_host=replace(a.target_host, genome_sha256="f" * 64))
                for a in self.spec.arms)),
        ]
        for spec in variants:
            with self.subTest(spec=spec.experiment_id), self.assertRaises(ValueError):
                self.decide([review(spec)])
        with self.assertRaisesRegex(ValueError, "criterion"):
            self.decide([replace(review(self.spec), criterion="Different criterion")])
        with self.assertRaisesRegex(ValueError, "ineligible or out-of-pool"):
            spec = replace(self.spec, experiment_id="outside", arms=(self.spec.arms[0],
                replace(self.spec.arms[1], phage_profile_ids=("outside:v1",))))
            self.decide([review(spec)])

    def test_duplicate_revisions_and_competing_arm_reviews_are_rejected(self):
        item = review(self.spec)
        for items in ([item, item], [item, replace(item, revision=2)],
                      [item, replace(item, attribution_id="another-review")]):
            with self.subTest(items=len(items)), self.assertRaises(ValueError):
                self.decide(items)

    def test_virtual_pending_invalid_measurements_cannot_enter_feedback(self):
        item = review(self.spec)
        for changes in (dict(origin="virtual_run", physical_execution=False),
                        dict(qc_status="pending", qc_evidence=()), dict(qc_status="invalid")):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                # A tampered, independently rehashed Measurement still fails admission.
                data = item.to_dict()
                data["measurements"][0] = replace(item.measurements[0], **changes).to_dict()
                from phage_lab.failure_attribution import failure_attribution_from_dict
                self.decide([failure_attribution_from_dict(data)])

    def test_inputs_are_detached_and_nested_mutation_is_rechecked_at_boundary(self):
        item = review(self.spec)
        decision = self.decide([item])
        digest = decision.content_sha256
        item.assessor.parameters["caller-mutation"] = True
        self.spec.arms[0].conditions["caller-mutation"] = True
        self.assertEqual(decision.content_sha256, digest)
        decision.feedback[0].measurements[0].data["signal"] = [999]
        with self.assertRaises(ValueError):
            experiment_spec_from_active_learning(decision, experiment_id="mutated")

    def test_feedback_history_survives_two_rounds_and_pool_exhaustion_abstains(self):
        first = self.decide([review(self.spec, name="first-a"),
                             review(self.spec, "single-phage-2", name="first-b")])
        self.assertEqual(first.selected_phage_profile_ids, ("c:v1", "d:v1"))
        next_spec = experiment_spec_from_active_learning(first, experiment_id="screen-two", created_at=LATER)
        self.assertEqual(next_spec.arms[1].conditions, self.spec.arms[1].conditions)
        self.assertEqual(next_spec.workflow, self.spec.workflow)
        self.assertEqual(next_spec.objective, self.spec.objective)
        self.assertEqual([r.artifact_type for r in next_spec.source_references],
                         ["CandidateSet", "ActiveLearningDecision", "ExperimentSpec"])
        self.assertEqual(next_spec.source_references[1].content_sha256, first.content_sha256)
        second = self.decide([
            review(next_spec, name="second-c", timestamp=LATER),
            review(next_spec, "single-phage-2", name="second-d", timestamp=LATER,
                   outcome="inconclusive"),
        ], decision_id="round-three", previous_decision=first, created_at=LATEST)
        self.assertEqual(len(second.feedback), 4)
        self.assertEqual(second.previous_decision.content_sha256, first.content_sha256)
        self.assertEqual(second.status, "abstained")
        self.assertEqual(self.states(second)["d:v1"], "needs_review")
        self.assertEqual(active_learning_decision_from_dict(second.to_dict()), second)

    def test_previous_campaign_mismatch_replacement_and_backward_time_rejected(self):
        item = review(self.spec)
        previous = self.decide([item])
        with self.assertRaisesRegex(ValueError, "historical content"):
            self.decide([replace(item, interpretation="Changed under the same ID")],
                        previous_decision=previous, decision_id="next")
        with self.assertRaisesRegex(ValueError, "exact campaign"):
            self.decide(previous_decision=previous, criterion="Another criterion", decision_id="next")
        with self.assertRaisesRegex(ValueError, "previous decision"):
            self.decide(previous_decision=previous, created_at=T3, decision_id="next")
        with self.assertRaisesRegex(ValueError, "different ActiveLearningDecision"):
            self.decide(previous_decision=previous)

    def test_same_spec_id_different_content_is_not_a_new_independent_experiment(self):
        changed = replace(self.spec, scientific_questions=("Different contents under same ID",))
        with self.assertRaisesRegex(ValueError, "different contents"):
            self.decide([review(changed)])
        with self.assertRaisesRegex(ValueError, "new experiment_id"):
            experiment_spec_from_active_learning(self.decide(), experiment_id=self.spec.experiment_id)

    def test_previous_policy_is_retained_and_replayed_feedback_is_idempotent(self):
        item = review(self.spec)
        previous = self.decide([item], policy=RecommendationPolicy(1, 1))
        again = self.decide([item], previous_decision=previous, decision_id="next", created_at=LATER)
        self.assertEqual(again.policy, previous.policy)
        self.assertEqual(again.selected_phage_profile_ids, ("b:v1",))
        self.assertEqual(len(again.feedback), 1)

    def test_same_id_changed_pool_and_nonuniform_initial_context_are_rejected(self):
        previous = self.decide([review(self.spec)])
        changed_pool = replace(self.pool, policy=RecommendationPolicy(2, 0))
        with self.assertRaisesRegex(ValueError, "exact campaign"):
            plan_next_screen(changed_pool, screen(changed_pool), [], decision_id="next",
                             criterion=CRITERION, previous_decision=previous, created_at=LATER)
        nonuniform = replace(self.spec, arms=(self.spec.arms[0],
            replace(self.spec.arms[1], conditions={"assay_context": "other"}), self.spec.arms[2]))
        with self.assertRaisesRegex(ValueError, "fixed assay context"):
            plan_next_screen(self.pool, nonuniform, [], decision_id="next", criterion=CRITERION,
                             created_at=STAMP)
        duplicate = replace(self.spec, arms=self.spec.arms + (
            replace(self.spec.arms[1], arm_id="duplicate-treatment"),))
        with self.assertRaisesRegex(ValueError, "original selected single"):
            plan_next_screen(self.pool, duplicate, [], decision_id="next", criterion=CRITERION,
                             created_at=STAMP)

    def test_cli_feedback_to_next_spec_and_previous_decision_carry_forward(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            root = Path(directory)
            write_candidate_set(self.pool, root / "pool.json")
            write_experiment_spec(self.spec, root / "screen.json")
            write_failure_attribution(review(self.spec), root / "review.json")
            args = ["active-learn", "--candidate-set", str(root / "pool.json"),
                    "--experiment-spec", str(root / "screen.json"),
                    "--failure-attribution", str(root / "review.json"),
                    "--decision-id", "cli-next", "--screening-criterion", CRITERION,
                    "--out", str(root / "decision.json")]
            self.assertEqual(main(args), 0)
            decision = load_active_learning_decision(root / "decision.json")
            self.assertEqual(decision.selected_phage_profile_ids, ("b:v1", "c:v1"))
            spec_args = ["experiment-spec", "--active-learning-decision", str(root / "decision.json"),
                         "--experiment-id", "cli-screen-two", "--out", str(root / "next-spec.json")]
            self.assertEqual(main(spec_args), 0)
            spec = load_experiment_spec(root / "next-spec.json")
            self.assertEqual(spec.member_phage_profile_ids, ("b:v1", "c:v1"))
            self.assertEqual(spec.arms[0].conditions, self.spec.arms[0].conditions)
            self.assertEqual(spec.source_references[1].content_sha256, decision.content_sha256)
            with self.assertRaises(SystemExit):
                main(spec_args + ["--conditions", str(root / "unused.json")])
            with self.assertRaises(SystemExit):
                main(spec_args + ["--candidate-set", str(root / "pool.json")])
            next_args = args.copy()
            next_args[next_args.index("cli-next")] = "cli-again"
            next_args[next_args.index(str(root / "decision.json"))] = str(root / "again.json")
            next_args += ["--previous-decision", str(root / "decision.json")]
            self.assertEqual(main(next_args), 0)
            self.assertEqual(len(load_active_learning_decision(root / "again.json").feedback), 1)
            bad = json.loads((root / "review.json").read_text())
            bad["outcome"] = "failure_not_observed"
            (root / "review.json").write_text(json.dumps(bad))
            (root / "again.json").unlink()
            self.assertEqual(main(next_args), 2)
            self.assertFalse((root / "again.json").exists())


class FeedbackRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_feedback_selected_arms_survive_virtual_execution_without_biological_evidence(self):
        from phage_lab.agents import RuleAgent
        from phage_lab.biology import read_fasta
        from phage_lab.host_profile import new_host_profile
        from phage_lab.host_state import new_host_state
        from phage_lab.interaction_prediction import evidence_only_unresolved_prediction
        from phage_lab.phage_profile import retrieved_candidate_to_phage_profile
        from phage_lab.workflow import run_experiment
        from support import CANDIDATES, WORKFLOW

        genome = Path(__file__).resolve().parent.parent / "examples" / "toy_genome.fasta"
        host = new_host_profile("runtime-fixture", read_fasta(genome), created_at=T3)
        snapshot = new_host_state(host, host_state_id="runtime-state", as_of=T3, created_at=T3)
        profiles = [retrieved_candidate_to_phage_profile(c) for c in CANDIDATES]
        predictions = [evidence_only_unresolved_prediction(
            snapshot, p, [], prediction_id=f"runtime-prediction-{index}", predicted_at=T3,
        ) for index, p in enumerate(profiles)]
        pool = recommend_natural_phages(snapshot, profiles, predictions, candidate_set_id="runtime-pool",
                                       policy=RecommendationPolicy(1, 1), created_at=T3)
        initial = replace(screen(pool), workflow=tuple(
            # Use the existing full orchestration contract for the runtime check.
            ExperimentStep(k, tuple(v))
            for k, v in WORKFLOW.items()
        ))
        reviewed = review(initial)
        decision = plan_next_screen(pool, initial, [reviewed], decision_id="runtime-next",
                                    criterion=CRITERION, created_at=STAMP)
        self.assertNotEqual(decision.selected_phage_profile_ids, pool.selected_phage_profile_ids)
        spec = experiment_spec_from_active_learning(decision, experiment_id="runtime-second")
        with tempfile.TemporaryDirectory() as directory:
            report, _ = await run_experiment(
                genome, Path(directory), sample_id="feedback-runtime", candidates=CANDIDATES,
                devices=None, workflow=WORKFLOW, agent=RuleAgent(), execution_mode="virtual_hardware",
                timeout_seconds=0.2, echo=False, experiment_spec=spec,
            )
        self.assertEqual(report["status"], "succeeded")
        self.assertEqual(report["experiment_spec"]["source_references"],
                         [r.to_dict() for r in spec.source_references])
        self.assertEqual(report["plan"]["candidate_ids"],
                         [p.rsplit(":v", 1)[0] for p in decision.selected_phage_profile_ids])
        self.assertEqual(set(report["results"]["measure"]["arms"]), {a.arm_id for a in spec.arms})
        self.assertTrue(all(a["evidence"] == "none" for a in report["results"]["measure"]["arms"].values()))
        self.assertEqual(report["evaluation"]["biological_conclusion"], "not_assessed")


if __name__ == "__main__":
    unittest.main()

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
import unittest
from phage_lab.__main__ import main
from phage_lab.experiment_spec import load_experiment_spec
from phage_lab.host_profile import new_host_profile
from phage_lab.host_state import new_host_state, write_host_state
from phage_lab.interaction_prediction import evidence_only_unresolved_prediction, write_interaction_prediction
from phage_lab.natural_phage_recommender import (
    RecommendationPolicy,
    candidate_set_from_dict,
    experiment_spec_from_candidate_set,
    load_candidate_set,
    recommend_natural_phages,
    write_candidate_set,
)
from phage_lab.phage_profile import RetrievedProvenance, new_engineered_phage_profile

from fixtures_screening import (
    T0, T1, T2, T3, UNKNOWN, state, phage, prediction, recommend,
)


class SelectionTests(unittest.TestCase):
    def test_lower_bound_beats_larger_point_estimate(self):
        a, b = phage("a"), phage("b")
        result = recommend(
            [a, b], [prediction(a, 0.1, 0.9, 1.0), prediction(b, 0.6, 0.7, 0.8)],
            policy=RecommendationPolicy(max_candidates=1, exploration_slots=0),
        )
        self.assertEqual(result.selected_phage_profile_ids, (b.profile_id,))
        self.assertEqual(result.evaluations[0].disposition, "deferred")
        self.assertEqual(result.evaluations[1].prediction.adsorption, UNKNOWN)
        self.assertEqual(result.evaluations[1].prediction.resistance_emergence, UNKNOWN)

    def test_mixed_pool_reserves_exploration_and_records_unselected_candidates(self):
        a, b, c, d = [phage(name) for name in "abcd"]
        result = recommend(
            [d, c, b, a],
            [prediction(a, 0.7), prediction(b, 0.6), prediction(c), prediction(d)],
            policy=RecommendationPolicy(2, 1),
        )
        self.assertEqual(result.selected_phage_profile_ids, (a.profile_id, c.profile_id))
        self.assertEqual([e.disposition for e in result.evaluations],
                         ["selected", "deferred", "selected", "deferred"])
        self.assertEqual(result.evaluations[2].basis, "exploration")
        self.assertIn("no pair-specific", " ".join(result.evaluations[2].reasons))

    def test_unresolved_only_pool_fills_budget_without_fabricated_scores(self):
        profiles = [phage(name) for name in "dcba"]
        predictions = [prediction(p) for p in profiles]
        result = recommend(profiles, predictions, policy=RecommendationPolicy(2, 1))
        self.assertEqual(result.selected_phage_profile_ids, ("a:v1", "b:v1"))
        for item in result.to_dict()["evaluations"]:
            self.assertEqual(item["basis"], "exploration")
            self.assertIsNone(item["prediction"]["probabilities"]["productive_infection"]["probability"])
            self.assertNotIn("score", item)
            self.assertNotIn("rank", item)
        # Input order is irrelevant to reproducible selection and hashing.
        reordered = recommend(list(reversed(profiles)), list(reversed(predictions)),
                              policy=RecommendationPolicy(2, 1))
        self.assertEqual(result.content_sha256, reordered.content_sha256)

    def test_predicted_only_pool_uses_unspent_exploration_budget(self):
        profiles = [phage(name) for name in "abc"]
        result = recommend(profiles, [prediction(p, 0.5) for p in profiles],
                           policy=RecommendationPolicy(3, 2))
        self.assertEqual(result.selected_phage_profile_ids, tuple(p.profile_id for p in profiles))

    def test_zero_probability_is_an_estimate_not_missing(self):
        p = phage("zero")
        result = recommend([p], [prediction(p, 0.0, 0.0, 0.0)])
        self.assertEqual(result.evaluations[0].basis, "predicted")
        self.assertEqual(result.selected_phage_profile_ids, (p.profile_id,))

    def test_engineered_and_missing_prediction_exclusions_and_retrieved_caveat(self):
        natural = phage("natural")
        retrieved = replace(phage("retrieved"), provenance=RetrievedProvenance(
            source_db="fixture", accession="fixture-record", retrieved_at=T0,
            source_uri="fixture://reference",
        ))
        engineered = new_engineered_phage_profile(
            "engineered", design_id="fixture-design", parent_profile_ids=(natural.profile_id,),
            designed_at=T0, created_at=T0,
        )
        result = recommend([natural, retrieved, engineered],
                           [prediction(retrieved), prediction(engineered, 0.8)])
        self.assertEqual(result.selected_phage_profile_ids, (retrieved.profile_id,))
        entries = {e.phage_profile_id: e for e in result.evaluations}
        self.assertEqual(entries[natural.profile_id].basis, "missing_prediction")
        self.assertEqual(entries[natural.profile_id].disposition, "excluded")
        self.assertEqual(entries[engineered.profile_id].basis, "engineered")
        self.assertEqual(entries[engineered.profile_id].disposition, "excluded")
        self.assertEqual(entries[retrieved.profile_id].provenance_kind, "retrieved")
        self.assertIn("does not establish", " ".join(entries[retrieved.profile_id].reasons))

    def test_empty_or_ineligible_pool_is_a_valid_empty_decision(self):
        for profiles in ([], [phage("missing")]):
            with self.subTest(profiles=profiles):
                result = recommend(profiles, [])
                self.assertEqual(result.selected_phage_profile_ids, ())
                self.assertIn("No eligible candidates", " ".join(result.limitations))
                self.assertEqual(candidate_set_from_dict(result.to_dict()), result)


class LineageTests(unittest.TestCase):
    def test_rejects_other_host_state_content_even_with_same_record_id(self):
        p = phage("a")
        item = prediction(p)
        changed = replace(state(), limitations=("Different state content.",))
        with self.assertRaisesRegex(ValueError, "exact HostState"):
            recommend_natural_phages(changed, [p], [item], candidate_set_id="bad", created_at=T3)

    def test_rejects_other_host_state_revision(self):
        p = phage("a")
        with self.assertRaisesRegex(ValueError, "exact HostState"):
            recommend_natural_phages(replace(state(), revision=2), [p], [prediction(p)],
                                     candidate_set_id="bad", created_at=T3)

    def test_rejects_profile_content_change_and_unmatched_prediction(self):
        p = phage("a")
        with self.assertRaisesRegex(ValueError, "exact PhageProfile"):
            recommend([replace(p, source_annotations={"new": "annotation"})], [prediction(p)])
        with self.assertRaisesRegex(ValueError, "outside the supplied pool"):
            recommend([p], [prediction(phage("other"))])

    def test_rejects_future_prediction(self):
        p = phage("a")
        with self.assertRaisesRegex(ValueError, "future prediction"):
            recommend_natural_phages(state(), [p], [prediction(p)],
                                     candidate_set_id="bad", created_at=T1)

    def test_rejects_duplicate_profiles_predictions_and_prediction_ids(self):
        a, b = phage("a"), phage("b")
        item = prediction(a)
        for profiles, predictions, error in (
            ([a, a], [item], "PhageProfile IDs must be unique"),
            ([a], [item, replace(item, revision=2)], "exactly one prediction per phage"),
            ([a, b], [item, prediction(b, prediction_id=item.prediction_id)],
             "Prediction record IDs must be unique"),
        ):
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                recommend(profiles, predictions)

    def test_different_model_configurations_or_uncertainty_methods_cannot_be_ranked(self):
        a, b = phage("a"), phage("b")
        left, right = prediction(a, 0.5), prediction(b, 0.6)
        variants = [replace(right, producer=replace(right.producer, **change)) for change in (
            {"name": "other"}, {"version": "2"}, {"parameters": {"context": "other"}},
            {"artifact_sha256": "b" * 64},
        )]
        variants.append(replace(right, productive_infection=replace(
            right.productive_infection, uncertainty_method="other-interval")))
        for variant in variants:
            with self.subTest(variant=variant), self.assertRaisesRegex(ValueError, "comparable candidate pools"):
                recommend([a, b], [left, variant])

    def test_policy_budget_validation(self):
        for maximum, exploration in ((0, 0), (True, 0), (2, -1), (2, 3), (2, True)):
            with self.subTest(maximum=maximum, exploration=exploration), self.assertRaises(ValueError):
                RecommendationPolicy(maximum, exploration)

    def test_round_trip_preserves_prediction_snapshot_and_detects_tampering(self):
        p = phage("a")
        item = prediction(p, 0.5)
        result = recommend([p], [item])
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "nested" / "set.json"
            write_candidate_set(result, path)
            self.assertEqual(load_candidate_set(path), result)
        self.assertEqual(result.evaluations[0].prediction.content_sha256, item.content_sha256)
        for key, value in (("content_sha256", "0" * 64), ("revision", 2),
                           ("selected_phage_profile_ids", []), ("limitations", []),
                           ("unknown_field", True), ("schema_version", True)):
            payload = result.to_dict()
            payload[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                candidate_set_from_dict(payload)
        for key, value in (("disposition", "deferred"), ("basis", "exploration"), ("reasons", [])):
            payload = result.to_dict()
            payload["evaluations"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                candidate_set_from_dict(payload)
        payload = result.to_dict()
        payload["evaluations"][0]["prediction"]["probabilities"]["productive_infection"]["probability"] = 0.7
        with self.assertRaisesRegex(ValueError, "content_sha256"):
            candidate_set_from_dict(payload)

    def test_input_model_parameter_mutation_does_not_rewrite_decision(self):
        p = phage("a")
        item = prediction(p, 0.5)
        result = recommend([p], [item])
        digest = result.content_sha256
        item.producer.parameters["new"] = "value"
        self.assertEqual(result.content_sha256, digest)


class ExperimentBridgeTests(unittest.TestCase):
    def test_one_control_and_independent_single_phage_arms_with_exact_source(self):
        profiles = [phage("a"), phage("b")]
        result = recommend(profiles, [prediction(p) for p in profiles])
        spec = experiment_spec_from_candidate_set(
            result, experiment_id="fixture-screen", workflow={"measure": ()},
            objective="Compare fixture arms.", expected_readouts=("declared-readout",),
            conditions={"assay_context": "fixture"}, created_at=T3,
        )
        self.assertIsNone(spec.source_design)
        self.assertEqual([arm.role for arm in spec.arms], ["control", "treatment", "treatment"])
        self.assertEqual([arm.phage_profile_ids for arm in spec.arms],
                         [(), ("a:v1",), ("b:v1",)])
        self.assertEqual(spec.member_phage_profile_ids, result.selected_phage_profile_ids)
        self.assertEqual(spec.source_references[0].artifact_type, "CandidateSet")
        self.assertEqual(spec.source_references[0].artifact_id, result.record_id)
        self.assertEqual(spec.source_references[0].content_sha256, result.content_sha256)
        self.assertEqual(spec.arms[1].conditions, {"assay_context": "fixture"})
        self.assertEqual(spec.arms[0].expected_readouts, ("declared-readout",))

    def test_empty_selection_or_backward_time_cannot_make_spec(self):
        p = phage("a")
        for result, created_at, error in (
            (recommend([p], []), T3, "empty selection"),
            (recommend([p], [prediction(p)]), T2, "cannot precede"),
        ):
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                experiment_spec_from_candidate_set(
                    result, experiment_id="fixture-screen", workflow={"measure": ()},
                    objective="Fixture", expected_readouts=("readout",), created_at=created_at,
                )

    def test_cli_prediction_to_recommendation_to_experiment(self):
        p = phage("a")
        with tempfile.TemporaryDirectory() as temporary, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            root = Path(temporary)
            write_host_state(state(), root / "state.json")
            (root / "profiles.json").write_text(json.dumps([p.to_dict()]), encoding="utf-8")
            write_interaction_prediction(prediction(p), root / "prediction.json")
            args = [
                "recommend-phages", "--host-state", str(root / "state.json"),
                "--phage-profiles", str(root / "profiles.json"),
                "--interaction-prediction", str(root / "prediction.json"),
                "--candidate-set-id", "screen", "--out", str(root / "set.json"),
            ]
            self.assertEqual(main(args), 0)
            result = load_candidate_set(root / "set.json")
            self.assertEqual(result.selected_phage_profile_ids, (p.profile_id,))
            self.assertEqual(main([
                "experiment-spec", "--candidate-set", str(root / "set.json"),
                "--experiment-id", "screen-001", "--objective", "Fixture comparison",
                "--expected-readout", "readout", "--out", str(root / "spec.json"),
            ]), 0)
            spec = load_experiment_spec(root / "spec.json")
            self.assertEqual(spec.member_phage_profile_ids, (p.profile_id,))
            self.assertEqual(len(spec.arms), 2)
            # Conflicting sources must not silently select a path.
            with self.assertRaises(SystemExit):
                main(["experiment-spec", "--candidate-set", str(root / "set.json"),
                      "--arms", "unused.json", "--experiment-id", "bad", "--out", str(root / "bad.json")])
            self.assertFalse((root / "bad.json").exists())
            # Bad predictions fail before an output artifact is written.
            write_interaction_prediction(prediction(phage("other")), root / "prediction.json")
            bad_args = args[:-1] + [str(root / "bad.json")]
            self.assertEqual(main(bad_args), 2)
            self.assertFalse((root / "bad.json").exists())


class CandidateSetRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_candidate_set_source_and_independent_arms_survive_virtual_execution(self):
        from phage_lab.agents import RuleAgent
        from phage_lab.biology import read_fasta
        from phage_lab.phage_profile import retrieved_candidate_to_phage_profile
        from phage_lab.workflow import run_experiment
        from support import CANDIDATES, WORKFLOW

        genome = Path(__file__).resolve().parent.parent / "examples" / "toy_genome.fasta"
        host = new_host_profile("fixture-runtime-host", read_fasta(genome), created_at=T0)
        snapshot = new_host_state(host, host_state_id="fixture-runtime-state", as_of=T1, created_at=T1)
        profiles = [retrieved_candidate_to_phage_profile(c) for c in CANDIDATES]
        predictions = [evidence_only_unresolved_prediction(
            snapshot, p, [], prediction_id=f"fixture-runtime-{index}",
        ) for index, p in enumerate(profiles)]
        result = recommend_natural_phages(
            snapshot, profiles, predictions, candidate_set_id="fixture-runtime-candidates",
            policy=RecommendationPolicy(2, 1),
        )
        spec = experiment_spec_from_candidate_set(
            result, experiment_id="fixture-runtime-screen", workflow=WORKFLOW,
            objective="Contract-path check only.", expected_readouts=("device_result",),
        )
        with tempfile.TemporaryDirectory() as temporary:
            report, _ = await run_experiment(
                genome, Path(temporary), sample_id="fixture-runtime",
                candidates=list(reversed(CANDIDATES)), devices=None, workflow=WORKFLOW,
                agent=RuleAgent(), execution_mode="virtual_hardware", timeout_seconds=0.2,
                echo=False, experiment_spec=spec,
            )
        self.assertEqual(report["status"], "succeeded")
        self.assertEqual(report["experiment_spec"]["source_references"],
                         [spec.source_references[0].to_dict()])
        self.assertEqual(report["plan"]["candidate_ids"],
                         [p.rsplit(":v", 1)[0] for p in result.selected_phage_profile_ids])
        self.assertEqual(set(report["results"]["measure"]["arms"]),
                         {"host-control", "single-phage-1", "single-phage-2"})
        self.assertTrue(all(arm["evidence"] == "none"
                            for arm in report["results"]["measure"]["arms"].values()))
        self.assertEqual(report["evaluation"]["biological_conclusion"], "not_assessed")


if __name__ == "__main__":
    unittest.main()

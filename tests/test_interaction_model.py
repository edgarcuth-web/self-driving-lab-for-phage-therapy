"""InteractionModel v0 software contracts; all data here are synthetic fixtures."""

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
import unittest

from phage_lab.biology import GenomeSummary
from phage_lab.host_profile import new_host_profile
from phage_lab.host_state import new_host_state, write_host_state
from phage_lab.interaction_features import (
    FeatureProducer,
    FeatureSource,
    interaction_feature_vector_from_dict,
    new_interaction_feature_vector,
)
from phage_lab.interaction_model import (
    ModelTrainingExample,
    interaction_model_from_dict,
    predict_research_score,
    research_prediction_from_dict,
    train_interaction_model,
)
from phage_lab.interaction_prediction import (
    PredictionProducer,
    ProbabilityEstimate,
    new_interaction_prediction,
)
from phage_lab.learning import new_learning_observation
from phage_lab.__main__ import main
from phage_lab.phage_profile import write_phage_profile
from phage_lab.natural_phage_recommender import recommend_natural_phages
from fixtures_feedback import LATEST, review, screen
from fixtures_screening import phage

T0 = "2026-01-01T00:00:00+00:00"
T1 = "2026-01-02T00:00:00+00:00"
T2 = "2026-01-03T00:00:00+00:00"
T3 = "2026-01-04T00:00:00+00:00"
UNKNOWN = ProbabilityEstimate(status="not_estimated")


def make_example(host_index, phage_suffix, observed):
    """Create a valid lineage fixture. These values are not biological evidence."""
    host_digest = f"{host_index:064x}"
    host_profile = new_host_profile(
        f"fixture-host-{host_index}",
        GenomeSummary(sha256=host_digest, bases=1000, contigs=1),
        created_at=T0,
    )
    state = new_host_state(
        host_profile,
        host_state_id=f"fixture-state-{host_index}",
        as_of=T1,
        created_at=T1,
    )
    profile = phage(f"fixture-phage-{host_index}-{phage_suffix}")
    prediction = new_interaction_prediction(
        state,
        profile,
        [],
        prediction_id=f"fixture-prediction-{host_index}-{phage_suffix}",
        adsorption=UNKNOWN,
        productive_infection=ProbabilityEstimate(
            status="estimated",
            probability=0.7,
            uncertainty_lower=0.6,
            uncertainty_upper=0.8,
            uncertainty_method="fixture-only",
        ),
        resistance_emergence=UNKNOWN,
        mechanistic_explanation="Software fixture only.",
        limitations=("Synthetic contract fixture; no biological claim.",),
        producer=PredictionProducer(name="fixture-model", version="1"),
        predicted_at=T2,
    )
    pool = recommend_natural_phages(
        state,
        [profile],
        [prediction],
        candidate_set_id=f"fixture-candidates-{host_index}-{phage_suffix}",
        created_at=T3,
    )
    spec = screen(pool)
    phenotype = next(
        item for item in review(
            spec,
            name=f"fixture-review-{host_index}-{phage_suffix}",
        ).phenotypes
        if item.experiment_arm_id == "single-phage-1"
    )
    observation = new_learning_observation(
        prediction,
        spec,
        phenotype,
        observation_id=f"fixture-learning-{host_index}-{phage_suffix}",
        target="productive_infection",
        observed=observed,
        interpretation="Explicit synthetic test label; no biological claim.",
        assessor_name="fixture-assessor",
        assessor_version="1",
        limitations=("Synthetic contract fixture only.",),
        assessed_at=LATEST,
    )
    features = {
        "fixture_signal": 1.0 if observed else 0.0,
        "host_group_marker": float(host_index % 3),
        "optional_feature": None if host_index % 2 else 2.0,
    }
    source_digest = "e" * 64
    feature_sources = {
        name: FeatureSource(
            source="software-test-fixture",
            version="1",
            method="contract-only",
            input_sha256=source_digest,
            available_at=T1,
            reference=f"fixture://{name}",
            evidence_ids=(),
        )
        for name in features
    }
    vector = new_interaction_feature_vector(
        state,
        profile,
        features,
        feature_sources,
        FeatureProducer(
            name="fixture-feature-producer",
            version="1",
            parameters={"fixture_only": True},
        ),
        vector_id=f"fixture-vector-{host_index}-{phage_suffix}",
        created_at=T3,
    )
    return ModelTrainingExample(feature_vector=vector, observation=observation)


def dataset():
    examples = []
    for host_index in range(1, 9):
        examples.append(make_example(host_index, "positive", True))
        examples.append(make_example(host_index, "negative", False))
    return examples


class InteractionFeatureVectorTests(unittest.TestCase):
    def test_round_trip_and_tamper_detection(self):
        item = make_example(1, "one", True).feature_vector
        loaded = interaction_feature_vector_from_dict(item.to_dict())
        self.assertEqual(loaded, item)
        tampered = item.to_dict()
        tampered["features"]["fixture_signal"] = 99.0
        with self.assertRaisesRegex(ValueError, "hash|content"):
            interaction_feature_vector_from_dict(tampered)

    def test_missing_feature_provenance_is_rejected(self):
        example = make_example(1, "one", True)
        sources = dict(example.feature_vector.feature_sources)
        sources.pop("fixture_signal")
        with self.assertRaisesRegex(ValueError, "feature_sources|provenance"):
            replace(
                example.feature_vector,
                features={"fixture_signal": 1.0},
                feature_sources=sources,
            )

    def test_non_finite_feature_is_rejected(self):
        example = make_example(1, "one", True)
        with self.assertRaisesRegex(ValueError, "finite"):
            replace(
                example.feature_vector,
                features={**example.feature_vector.features, "fixture_signal": float("nan")},
            )


    def test_feature_source_available_after_prediction_is_rejected(self):
        example = make_example(1, "future", True)
        sources = dict(example.feature_vector.feature_sources)
        sources["fixture_signal"] = replace(sources["fixture_signal"], available_at=T3)
        vector = replace(example.feature_vector, feature_sources=sources)
        with self.assertRaisesRegex(ValueError, "after the prediction|future information"):
            ModelTrainingExample(feature_vector=vector, observation=example.observation)

    def test_vector_must_match_observation_lineage(self):
        first = make_example(1, "one", True)
        other = make_example(2, "two", False)
        with self.assertRaisesRegex(ValueError, "HostState|host|lineage"):
            ModelTrainingExample(
                feature_vector=first.feature_vector,
                observation=other.observation,
            )


class InteractionModelTrainingTests(unittest.TestCase):
    def test_training_is_deterministic_and_host_grouped(self):
        examples = dataset()
        first = train_interaction_model(
            examples,
            model_id="fixture-model",
            seed=17,
            epochs=40,
            created_at=T3,
        )
        second = train_interaction_model(
            examples,
            model_id="fixture-model",
            seed=17,
            epochs=40,
            created_at=T3,
        )
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertTrue(set(first.training_host_groups).isdisjoint(first.test_host_groups))
        self.assertEqual(first.metrics["test_sample_count"], len(first.test_example_ids))
        self.assertGreaterEqual(first.metrics["test_host_group_count"], 2)
        self.assertEqual(first.model_status, "research_only")
        self.assertEqual(first.calibration_status, "not_calibrated")

    def test_round_trip_and_hash_integrity(self):
        model = train_interaction_model(
            dataset(), model_id="fixture-model", seed=19, epochs=30, created_at=T3
        )
        self.assertEqual(interaction_model_from_dict(model.to_dict()), model)
        tampered = model.to_dict()
        tampered["coefficients"][0] += 1
        with self.assertRaisesRegex(ValueError, "hash|content"):
            interaction_model_from_dict(tampered)

    def test_duplicate_host_phage_pair_is_rejected(self):
        examples = dataset()
        examples.append(examples[0])
        with self.assertRaisesRegex(ValueError, "duplicate|pair"):
            train_interaction_model(
                examples, model_id="duplicate-model", seed=17, epochs=10, created_at=T3
            )

    def test_insufficient_host_groups_is_rejected(self):
        examples = [
            make_example(1, "positive", True),
            make_example(1, "negative", False),
            make_example(2, "positive", True),
            make_example(2, "negative", False),
        ]
        with self.assertRaisesRegex(ValueError, "host groups|host-genome"):
            train_interaction_model(
                examples, model_id="small-model", seed=17, epochs=10, created_at=T3
            )

    def test_raw_score_is_explicitly_uncalibrated_and_not_an_interaction_prediction(self):
        examples = dataset()
        model = train_interaction_model(
            examples, model_id="fixture-model", seed=17, epochs=40, created_at=T3
        )
        vector = make_example(9, "query", True).feature_vector
        score = predict_research_score(
            model, vector, prediction_id="raw-score-001", predicted_at=T3
        )
        payload = score.to_dict()
        self.assertEqual(score.status, "uncalibrated_research_score")
        self.assertTrue(0.0 <= score.uncalibrated_probability <= 1.0)
        self.assertIn("model_artifact_sha256", payload)
        self.assertIn("feature_vector_sha256", payload)
        self.assertNotIn("probabilities", payload)
        self.assertEqual(research_prediction_from_dict(payload), score)


    def test_training_rejects_mixed_feature_producer_versions(self):
        examples = dataset()
        original = examples[-1]
        sources = dict(original.feature_vector.feature_sources)
        sources["fixture_signal"] = replace(sources["fixture_signal"], version="2")
        changed_vector = replace(original.feature_vector, feature_sources=sources)
        examples[-1] = replace(original, feature_vector=changed_vector)
        with self.assertRaisesRegex(ValueError, "source/method versions|producer configuration"):
            train_interaction_model(
                examples, model_id="mixed-schema-model", seed=17, epochs=10, created_at=T3
            )

    def test_score_rejects_same_names_with_different_feature_provenance(self):
        model = train_interaction_model(
            dataset(), model_id="fixture-model", seed=17, epochs=30, created_at=T3
        )
        example = make_example(9, "query", True)
        sources = dict(example.feature_vector.feature_sources)
        sources["fixture_signal"] = replace(sources["fixture_signal"], version="2")
        bad = replace(example.feature_vector, feature_sources=sources)
        with self.assertRaisesRegex(ValueError, "feature schema provenance"):
            predict_research_score(model, bad, prediction_id="bad-schema-score", predicted_at=T3)

    def test_feature_schema_mismatch_is_rejected(self):
        model = train_interaction_model(
            dataset(), model_id="fixture-model", seed=17, epochs=30, created_at=T3
        )
        example = make_example(9, "query", True)
        bad = replace(
            example.feature_vector,
            features={"different_feature": 1.0},
            feature_sources={
                "different_feature": next(iter(example.feature_vector.feature_sources.values()))
            },
        )
        with self.assertRaisesRegex(ValueError, "feature schema|feature names"):
            predict_research_score(model, bad, prediction_id="bad-score", predicted_at=T3)



class InteractionModelCliTests(unittest.TestCase):
    def test_cli_train_and_score_round_trip(self):
        examples = dataset()
        vector = make_example(9, "query", True).feature_vector
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset_path = root / "training-examples.json"
            vector_path = root / "feature-vector.json"
            model_path = root / "model.json"
            score_path = root / "research-score.json"
            dataset_path.write_text(
                json.dumps([item.to_dict() for item in examples], ensure_ascii=False),
                encoding="utf-8",
            )
            vector_path.write_text(
                json.dumps(vector.to_dict(), ensure_ascii=False),
                encoding="utf-8",
            )
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(main([
                    "interaction-model-train",
                    "--dataset", str(dataset_path),
                    "--model-id", "cli-model",
                    "--epochs", "30",
                    "--created-at", T3,
                    "--out", str(model_path),
                ]), 0)
                self.assertEqual(main([
                    "interaction-model-score",
                    "--model", str(model_path),
                    "--feature-vector", str(vector_path),
                    "--prediction-id", "cli-score",
                    "--predicted-at", T3,
                    "--out", str(score_path),
                ]), 0)
            payload = json.loads(score_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "uncalibrated_research_score")
            self.assertIn("model_artifact_sha256", payload)
            self.assertNotIn("probabilities", payload)

    def test_cli_feature_vector_binds_exact_host_and_phage(self):
        host_profile = new_host_profile(
            "cli-host",
            GenomeSummary(sha256="f" * 64, bases=1000, contigs=1),
            created_at=T0,
        )
        state = new_host_state(
            host_profile,
            host_state_id="cli-host-state",
            as_of=T1,
            created_at=T1,
        )
        profile = phage("cli-phage")
        source = FeatureSource(
            source="cli-fixture",
            version="1",
            method="contract-test",
            input_sha256="d" * 64,
            available_at=T1,
            reference="fixture://cli",
            evidence_ids=(),
        )
        producer = FeatureProducer(name="cli-fixture", version="1")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = root / "state.json"
            profile_path = root / "profile.json"
            feature_input_path = root / "feature-input.json"
            vector_path = root / "vector.json"
            write_host_state(state, state_path)
            write_phage_profile(profile, profile_path)
            feature_input_path.write_text(json.dumps({
                "features": {"feature_a": 1.0},
                "feature_sources": {"feature_a": source.to_dict()},
                "producer": producer.to_dict(),
            }), encoding="utf-8")
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(main([
                    "interaction-feature-vector",
                    "--host-state", str(state_path),
                    "--phage-profile", str(profile_path),
                    "--feature-input", str(feature_input_path),
                    "--vector-id", "cli-vector",
                    "--created-at", T3,
                    "--out", str(vector_path),
                ]), 0)
            payload = json.loads(vector_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["host_state"]["record_id"], state.record_id)
            self.assertEqual(payload["phage_profile_id"], profile.profile_id)


if __name__ == "__main__":
    unittest.main()

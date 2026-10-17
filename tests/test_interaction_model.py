"""InteractionModel v0 software contracts; all data here are synthetic fixtures."""

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from phage_lab.biology import GenomeSummary
from phage_lab.host_profile import new_host_profile
from phage_lab.host_state import new_host_state
from phage_lab.interaction_model import (
    FeatureProducer,
    FeatureSource,
    ModelTrainingExample,
    feature_vector_from_dict,
    interaction_model_from_dict,
    new_interaction_feature_vector,
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
        loaded = feature_vector_from_dict(item.to_dict())
        self.assertEqual(loaded, item)
        tampered = item.to_dict()
        tampered["features"]["fixture_signal"] = 99.0
        with self.assertRaisesRegex(ValueError, "hash|content"):
            feature_vector_from_dict(tampered)

    def test_missing_feature_provenance_is_rejected(self):
        example = make_example(1, "one", True)
        sources = dict(example.feature_vector.feature_sources)
        sources.pop("fixture_signal")
        with self.assertRaisesRegex(ValueError, "feature_sources|provenance"):
            new_interaction_feature_vector(
                example.observation.prediction.host_state,
                example.observation.prediction.phage_profile_id,
                {"fixture_signal": 1.0},
                sources,
                FeatureProducer(name="test", version="1"),
                vector_id="bad-vector",
                created_at=T3,
            )

    def test_non_finite_feature_is_rejected(self):
        example = make_example(1, "one", True)
        with self.assertRaisesRegex(ValueError, "finite"):
            replace(
                example.feature_vector,
                features={**example.feature_vector.features, "fixture_signal": float("nan")},
            )

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


if __name__ == "__main__":
    unittest.main()

import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from phage_lab.interaction_prediction import PredictionProducer
from phage_lab.learning import (
    calibration_report_from_dict,
    calibration_report_from_observations,
    learning_observation_from_dict,
    load_calibration_report,
    load_learning_observation,
    new_learning_observation,
    write_calibration_report,
    write_learning_observation,
)

from fixtures_feedback import LATEST, review, screen
from fixtures_screening import phage, prediction, recommend


def learning_case(*, estimated=True, observed=True, suffix="one"):
    profile = phage(f"phage-{suffix}")
    model_prediction = prediction(
        profile,
        lower=0.6 if estimated else None,
        point=0.7,
        upper=0.8,
    )
    pool = recommend([profile], [model_prediction])
    spec = screen(pool)
    target = next(
        item for item in review(spec, name=f"review-{suffix}").phenotypes
        if item.experiment_arm_id == "single-phage-1"
    )
    observation = new_learning_observation(
        model_prediction,
        spec,
        target,
        observation_id=f"learning-{suffix}",
        target="productive_infection",
        observed=observed,
        interpretation="Explicit fixture label; phenotype polarity is not auto-mapped.",
        assessor_name="fixture-learning-reviewer",
        assessor_version="1",
        limitations=("Contract fixture only; no biological claim.",),
        assessed_at=LATEST,
    )
    return observation


class LearningObservationTests(unittest.TestCase):
    def test_observation_binds_prediction_spec_and_physical_phenotype(self):
        item = learning_case()
        self.assertEqual(item.learning_status, "scorable")
        self.assertAlmostEqual(item.predicted_probability, 0.7)
        self.assertAlmostEqual(item.squared_error, 0.09)
        self.assertEqual(item.phenotype.experiment_arm_id, "single-phage-1")
        self.assertEqual(
            item.prediction.phage_profile_id,
            item.phenotype.phage_profile_ids[0],
        )

    def test_unestimated_prediction_is_retained_as_label_only(self):
        item = learning_case(estimated=False)
        self.assertEqual(item.learning_status, "label_only")
        self.assertIsNone(item.predicted_probability)
        self.assertIsNone(item.squared_error)

    def test_label_is_explicit_not_inferred_from_phenotype_outcome(self):
        positive_label = learning_case(observed=True, suffix="explicit")
        self.assertEqual(positive_label.phenotype.outcome, "negative")
        self.assertTrue(positive_label.observed)

    def test_rejects_prediction_for_different_phage(self):
        item = learning_case()
        wrong = phage("other-phage")
        wrong_prediction = prediction(
            wrong, lower=0.5, point=0.6, upper=0.7,
        )
        with self.assertRaisesRegex(ValueError, "Prediction phage"):
            new_learning_observation(
                wrong_prediction,
                item.experiment_spec,
                item.phenotype,
                observation_id="wrong",
                target="productive_infection",
                observed=True,
                interpretation="Fixture mismatch.",
                assessor_name="fixture",
                assessor_version="1",
                limitations=("Fixture.",),
                assessed_at=LATEST,
            )

    def test_round_trip_and_tamper_detection(self):
        item = learning_case()
        loaded = learning_observation_from_dict(item.to_dict())
        self.assertEqual(loaded, item)
        tampered = json.loads(json.dumps(item.to_dict()))
        tampered["observed"] = False
        with self.assertRaisesRegex(ValueError, "derived fields or hash"):
            learning_observation_from_dict(tampered)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "observation.json"
            write_learning_observation(item, path)
            self.assertEqual(load_learning_observation(path), item)


class CalibrationReportTests(unittest.TestCase):
    def test_report_computes_descriptive_metrics(self):
        first = learning_case(observed=True, suffix="first")
        second = learning_case(observed=False, suffix="second")
        report = calibration_report_from_observations(
            [first, second],
            report_id="calibration-001",
            target="productive_infection",
            created_at=LATEST,
        )
        self.assertEqual(report.metrics["sample_count"], 2)
        self.assertAlmostEqual(report.metrics["mean_predicted_probability"], 0.7)
        self.assertAlmostEqual(report.metrics["observed_rate"], 0.5)
        self.assertAlmostEqual(report.metrics["calibration_gap"], 0.2)
        self.assertAlmostEqual(report.metrics["brier_score"], 0.29)

    def test_report_rejects_label_only_observations(self):
        item = learning_case(estimated=False)
        with self.assertRaisesRegex(ValueError, "estimated"):
            calibration_report_from_observations(
                [item],
                report_id="calibration-unresolved",
                target="productive_infection",
                created_at=LATEST,
            )

    def test_report_rejects_mixed_model_provenance(self):
        first = learning_case(suffix="first")
        second = learning_case(suffix="second")
        changed_prediction = replace(
            second.prediction,
            producer=PredictionProducer(name="other-model", version="1"),
        )
        second = replace(second, prediction=changed_prediction)
        with self.assertRaisesRegex(ValueError, "producer provenance"):
            calibration_report_from_observations(
                [first, second],
                report_id="calibration-mixed",
                target="productive_infection",
                created_at=LATEST,
            )

    def test_report_round_trip_and_file_io(self):
        report = calibration_report_from_observations(
            [learning_case()],
            report_id="calibration-001",
            target="productive_infection",
            created_at=LATEST,
        )
        self.assertEqual(calibration_report_from_dict(report.to_dict()), report)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calibration.json"
            write_calibration_report(report, path)
            self.assertEqual(load_calibration_report(path), report)


if __name__ == "__main__":
    unittest.main()

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from phage_lab.__main__ import main
from phage_lab.experiment_spec import write_experiment_spec
from phage_lab.failure_attribution import (
    FailureAttribution, MechanismHypothesis, failure_attribution_from_results,
    failure_attribution_from_dict, load_failure_attribution, write_failure_attribution,
)
from phage_lab.phenotype import (
    phenotype_from_measurements, phenotype_comparison_from_phenotypes,
)
from test_material_measurement_phenotype import experiment_spec, physical_measurement, STAMP


class FailureAttributionTests(unittest.TestCase):
    def setUp(self):
        self.spec = experiment_spec()
        self.measurements = [physical_measurement(arm_id=arm_id, spec=self.spec)
                             for arm_id in ("host-control", "cocktail-treatment")]
        self.phenotypes = [phenotype_from_measurements(
            self.spec, [measurement], arm_id=measurement.experiment_arm_id,
            phenotype_id=f"phenotype-{measurement.experiment_arm_id}",
            phenotype_type="growth_response", outcome="negative",
            interpretation="Assessor-stated result, with no universal success polarity.",
            assessor_name="reviewer", assessor_version="1", assessed_at=STAMP,
        ) for measurement in self.measurements]
        self.comparison = phenotype_comparison_from_phenotypes(
            self.spec, *self.phenotypes, comparison_id="control-treatment",
            comparison_type="declared_comparison", outcome="no_declared_effect",
            interpretation="Explicit arm comparison for a test fixture.",
            assessor_name="reviewer", assessor_version="1", assessed_at=STAMP,
        )

    def review(self, **overrides):
        values = dict(
            spec=self.spec, measurements=self.measurements, phenotypes=self.phenotypes,
            comparisons=(self.comparison,), attribution_id="review-001",
            target_arm_id="cocktail-treatment", outcome="failure_observed",
            criterion="Caller-declared screening objective was not met in this context.",
            interpretation="Manual review of this arm comparison only.",
            assessor_name="reviewer", assessor_version="1", assessed_at=STAMP,
            limitations=("No causal mechanism established; no member-level conclusion.",),
        )
        values.update(overrides)
        return failure_attribution_from_results(**values)

    def hypothesis(self, **overrides):
        values = dict(
            category="other", rationale="Unconfirmed assessor hypothesis for review.",
            supporting_comparison_ids=(self.comparison.record_id,),
            limitations=("Outcome alone cannot establish mechanism.",),
        )
        values.update(overrides)
        return MechanismHypothesis(**values)

    def test_comparison_review_round_trip_preserves_source_hashes(self):
        review = self.review()
        rebuilt = failure_attribution_from_dict(review.to_dict())
        self.assertEqual(rebuilt.content_sha256, review.content_sha256)
        self.assertEqual(rebuilt.experiment_spec.content_sha256, self.spec.content_sha256)
        self.assertEqual(rebuilt.measurements[0].content_sha256, self.measurements[0].content_sha256)
        self.assertEqual(rebuilt.comparisons[0].content_sha256, self.comparison.content_sha256)
        self.assertEqual(rebuilt.mechanism_status, "unknown")

    def test_negative_phenotype_does_not_determine_failure_outcome(self):
        for outcome in ("failure_observed", "failure_not_observed", "inconclusive"):
            with self.subTest(outcome=outcome):
                review = self.review(outcome=outcome)
                self.assertEqual(review.outcome, outcome)
                self.assertEqual(review.mechanism_status, "unknown")

    def test_single_arm_without_comparison_is_valid(self):
        review = self.review(measurements=self.measurements[1:],
                             phenotypes=self.phenotypes[1:], comparisons=())
        self.assertEqual(len(review.phenotypes), 1)
        self.assertEqual(review.target_arm_id, "cocktail-treatment")
        # There is no allocation of an arm result to individual cocktail members.
        self.assertNotIn("per_phage_outcomes", review.to_dict())

    def test_hypotheses_are_explicit_and_never_confirmed(self):
        review = self.review(hypotheses=(self.hypothesis(),))
        self.assertEqual(review.mechanism_status, "hypothesized")
        self.assertEqual(failure_attribution_from_dict(review.to_dict()).hypotheses, review.hypotheses)
        with self.assertRaisesRegex(ValueError, "failure_observed"):
            self.review(outcome="failure_not_observed", hypotheses=(self.hypothesis(),))
        with self.assertRaisesRegex(ValueError, "unavailable"):
            self.review(hypotheses=(self.hypothesis(supporting_comparison_ids=("absent:v1",)),))
        with self.assertRaisesRegex(ValueError, "target-arm evidence"):
            self.review(hypotheses=(self.hypothesis(
                supporting_comparison_ids=(),
                supporting_phenotype_ids=(self.phenotypes[0].record_id,),
            ),))

    def test_virtual_invalid_and_pending_sources_are_rejected(self):
        for changes in (
            dict(origin="virtual_run", physical_execution=False),
            dict(qc_status="invalid", qc_evidence=("failed-qc",)),
            dict(qc_status="pending", qc_evidence=()),
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.review(measurements=[self.measurements[0], replace(self.measurements[1], **changes)])

    def test_missing_duplicate_and_unreferenced_measurements_are_rejected(self):
        for measurements in (
            self.measurements[:1],
            self.measurements + self.measurements[:1],
            self.measurements + [replace(self.measurements[1], measurement_id="unrelated")],
        ):
            with self.subTest(count=len(measurements)), self.assertRaises(ValueError):
                self.review(measurements=measurements)

    def test_phage_host_arm_material_and_spec_lineage_are_rechecked(self):
        for changes in (
            dict(phage_profile_ids=("different:v1",)),
            dict(target_host_profile_id="different:v1"),
            dict(experiment_arm_id="host-control"),
            dict(material_batch_ids=("different:v1",)),
            dict(experiment_spec_sha256="a" * 64),
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.review(phenotypes=[self.phenotypes[0], replace(self.phenotypes[1], **changes)])

    def test_comparison_requires_exact_supplied_phenotype_contents(self):
        for changes in (
            dict(baseline_phenotype_sha256="a" * 64),
            dict(comparator_phenotype_sha256="b" * 64),
            dict(baseline_phenotype_id="absent:v1"),
            dict(experiment_spec_sha256="c" * 64),
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.review(comparisons=(replace(self.comparison, **changes),))

    def test_control_target_and_missing_target_result_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "treatment arm"):
            self.review(target_arm_id="host-control")
        with self.assertRaisesRegex(ValueError, "target arm"):
            self.review(measurements=self.measurements[:1], phenotypes=self.phenotypes[:1], comparisons=())

    def test_uncompared_other_arm_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Other-arm"):
            self.review(comparisons=())

    def test_time_causality_is_checked_at_every_stage(self):
        earlier = "2026-10-16T19:29:59+00:00"
        later = "2026-10-16T19:30:01+00:00"
        with self.assertRaises(ValueError):
            self.review(assessed_at=earlier)
        with self.assertRaisesRegex(ValueError, "Measurement cannot postdate"):
            self.review(measurements=[self.measurements[0], replace(self.measurements[1], created_at=later)])
        with self.assertRaisesRegex(ValueError, "Comparison assessment"):
            self.review(comparisons=(replace(self.comparison, assessed_at=earlier),))
        with self.assertRaisesRegex(ValueError, "timezone"):
            self.review(assessed_at="2026-10-16T20:00:00")

    def test_review_requires_criterion_limitations_valid_revision_and_outcome(self):
        for changes in (dict(criterion=""), dict(limitations=()), dict(outcome="negative"),
                        dict(revision=True), dict(revision=0), dict(schema_version=True)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(self.review(), **changes)
        for changes in (dict(limitations="not an array"), dict(assessor_parameters=[]),
                        dict(assessed_at="")):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.review(**changes)

    def test_hash_tampering_unknown_fields_and_false_mechanism_status_are_rejected(self):
        review = self.review()
        for key, value in (("criterion", "Changed"), ("record_id", "changed:v1"),
                           ("mechanism_status", "confirmed"), ("probability", 0.8)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                failure_attribution_from_dict({**review.to_dict(), key: value})

    def test_nested_qc_cannot_be_bypassed_by_rehashing_outer_artifact(self):
        review = self.review()
        # Even an internally well-formed measurement with its own recomputed hash
        # must pass physical/QC admission when the attribution is loaded.
        bad = review.to_dict()
        bad["measurements"][1] = replace(self.measurements[1], qc_status="invalid").to_dict()
        with self.assertRaisesRegex(ValueError, "qc_status"):
            failure_attribution_from_dict(bad)

    def test_write_load_and_new_revision_do_not_overwrite_source_artifacts(self):
        review = self.review()
        original = self.spec.to_dict()
        newer = replace(review, revision=2, interpretation="Updated explicit review.")
        self.assertNotEqual(newer.content_sha256, review.content_sha256)
        self.assertNotEqual(newer.record_id, review.record_id)
        self.assertEqual(self.spec.to_dict(), original)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.json"
            write_failure_attribution(review, path)
            self.assertEqual(load_failure_attribution(path).to_dict(), review.to_dict())

    def cli_inputs(self, directory):
        root = Path(directory)
        write_experiment_spec(self.spec, root / "spec.json")
        (root / "measurements.json").write_text(json.dumps([m.to_dict() for m in self.measurements]))
        for index, phenotype in enumerate(self.phenotypes):
            (root / f"phenotype-{index}.json").write_text(json.dumps(phenotype.to_dict()))
        (root / "comparison.json").write_text(json.dumps(self.comparison.to_dict()))
        (root / "review.json").write_text(json.dumps({
            "outcome": "inconclusive", "criterion": "Explicit review criterion.",
            "interpretation": "Result does not resolve the declared objective.",
            "limitations": ["Mechanism remains unknown."], "assessed_at": STAMP,
        }))
        return ["failure-attribution", "--experiment-spec", str(root / "spec.json"),
                "--measurements", str(root / "measurements.json"),
                "--phenotypes", str(root / "phenotype-0.json"),
                "--phenotypes", str(root / "phenotype-1.json"),
                "--phenotype-comparison", str(root / "comparison.json"),
                "--attribution-id", "review-cli", "--arm-id", "cocktail-treatment",
                "--attribution-input", str(root / "review.json"), "--assessor", "reviewer",
                "--out", str(root / "out.json")]

    def test_cli_end_to_end_and_error_handling(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            args = self.cli_inputs(directory)
            self.assertEqual(main(args), 0)
            path = Path(directory) / "out.json"
            self.assertEqual(load_failure_attribution(path).outcome, "inconclusive")
            path.unlink()
            review_path = Path(directory) / "review.json"
            review_path.write_text('{"outcome": "failure_observed"}')
            self.assertEqual(main(args), 2)
            self.assertFalse(path.exists())

    def test_cli_rejects_virtual_sources_without_writing_output(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            args = self.cli_inputs(directory)
            virtual = replace(self.measurements[1], origin="virtual_run", physical_execution=False)
            (Path(directory) / "measurements.json").write_text(json.dumps([
                self.measurements[0].to_dict(), virtual.to_dict(),
            ]))
            self.assertEqual(main(args), 2)
            self.assertFalse((Path(directory) / "out.json").exists())


if __name__ == "__main__":
    unittest.main()

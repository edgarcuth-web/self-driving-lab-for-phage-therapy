"""Portable model inputs; tiny sequences below test software only."""

from dataclasses import replace
import copy
import json
from pathlib import Path
import tempfile
import unittest
import shutil

from phage_lab.artifacts import canonical_content_sha256
from phage_lab.model_input_bundle import export_model_input_bundle, load_model_input_bundle, load_pair_prediction
from phage_lab.model_contract import admit_model_result, model_result_from_dict, new_model_request
from phage_lab.interaction_prediction import interaction_prediction_from_dict
from phage_lab.natural_phage_recommender import recommend_natural_phages
from phage_lab.sequence_registry import create_sequence_registry
from phage_lab.phage_profile import SequenceRef, RetrievedProvenance
from fixtures_screening import T2, phage, state


def endpoint():
    return {
        "endpoint_id": "fixture-source-label:v1",
        "kind": "source_defined_binary",
        "definition": "Source label only; no assay mapping.",
        "positive_value": 1, "negative_value": 0,
        "assay_definition_status": "unverified",
        "source": {"dataset_id": "fixture", "version": "1", "sha256": "b" * 64,
                   "label_column": "interaction"},
        "evidence": ["https://example.org/software-fixture"],
        "limitations": ["Software fixture only."],
    }


class ModelInputBundleTests(unittest.TestCase):
    fixture = Path(__file__).parent / "fixtures/input_bundle"

    def test_shared_fixture_preserves_partial_annotation_and_payloads(self):
        bundle = load_model_input_bundle(self.fixture / "bundle.json", required_sequences=("host",))
        self.assertEqual(bundle["feature_artifacts"][0]["manifest"]["status"], "partial")
        self.assertEqual(
            bundle["feature_artifacts"][0]["manifest"]["analysis"]["tool"]["name"], "example-annotation-tool"
        )

    def test_resealed_manifest_cannot_hide_wrong_identity_or_missing_files(self):
        changes = (
            (lambda b: b["resources"][0].update(sequence_sha256="e" * 64), "identity"),
            (lambda b: b["resources"][0].update(path="../host.fna"), "relative"),
            (lambda b: b["resources"].append(copy.deepcopy(b["resources"][0])), "duplicate"),
            (lambda b: b["sequence_status"].update(host="not_provided"), "sequence_status"),
            (lambda b: b["assay_context"].update(conditions={"invented": True}), "unknown"),
        )
        for change, message in changes:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "input"
                shutil.copytree(self.fixture, root)
                path = root / "bundle.json"
                bundle = json.loads(path.read_text())
                change(bundle)
                bundle["content_sha256"] = canonical_content_sha256(bundle)
                path.write_text(json.dumps(bundle))
                with self.assertRaisesRegex(ValueError, message):
                    load_model_input_bundle(path)

    def test_feature_payload_and_symlink_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "input"
            shutil.copytree(self.fixture, root)
            path = root / "bundle.json"
            bundle = load_model_input_bundle(path)
            entry = bundle["feature_artifacts"][0]
            output = root / entry["directory"] / entry["manifest"]["outputs"][0]["path"]
            output.write_text("changed")
            with self.assertRaisesRegex(ValueError, "SHA-256|size"):
                load_model_input_bundle(path)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "input"
            shutil.copytree(self.fixture, root)
            path = root / "bundle.json"
            bundle = load_model_input_bundle(path)
            sequence = root / bundle["resources"][0]["path"]
            external = Path(directory) / "external.fna"
            external.write_bytes(sequence.read_bytes())
            sequence.unlink()
            sequence.symlink_to(external)
            with self.assertRaisesRegex(ValueError, "escapes"):
                load_model_input_bundle(path)

    def test_pair_result_cannot_be_mislabelled_as_probability(self):
        path = self.fixture / "bundle.json"
        bundle = load_model_input_bundle(path)
        result = {
            "schema_version": 1, "kind": "pair_prediction", "prediction_id": "fixture",
            "bundle_id": bundle["bundle_id"], "bundle_sha256": bundle["content_sha256"],
            "created_at": "2026-10-19T12:00:00Z",
            "estimate": {"status": "uncalibrated_score", "value": 0.7, "uncertainty": None, "reason": "fixture"},
            "producer": {"name": "fixture", "version": "1", "artifact_sha256": "a" * 64,
                         "preprocessing_sha256": "b" * 64, "calibration_sha256": None},
            "limitations": ["Software fixture only."],
        }
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "result.json"
            for change, error in (
                ({}, None),
                ({"estimate": {**result["estimate"], "status": "probability"}}, "probability requires"),
                ({"bundle_sha256": "c" * 64}, "exact bundle"),
                ({"created_at": "2020-01-01T00:00:00Z"}, "predate"),
                ({"estimate": {**result["estimate"], "status": "not_estimated"}}, "null"),
            ):
                altered = copy.deepcopy(result)
                altered.update(change)
                altered["content_sha256"] = canonical_content_sha256(altered)
                out.write_text(json.dumps(altered))
                if error:
                    with self.assertRaisesRegex(ValueError, error):
                        load_pair_prediction(out, path)
                else:
                    self.assertEqual(load_pair_prediction(out, path)["estimate"]["status"], "uncalibrated_score")

    def export(self, root, **kwargs):
        return export_model_input_bundle(
            state(), phage("bundle-phage"), endpoint=endpoint(),
            assay_context={"status": "unknown", "conditions": {}, "evidence": []},
            bundle_id="test-bundle", output_dir=root / "export", created_at=T2,
            **kwargs,
        )

    def test_admitted_source_outputs_cannot_enter_mechanistic_decisions(self):
        # Even a verified source probability is not a productive-infection label.
        # All verification/calibration claims here are synthetic software fixtures.
        host, profile = state(), phage("source-only")
        source_endpoint = {**endpoint(), "assay_definition_status": "verified"}
        request = new_model_request(host, profile, request_id="legacy", created_at=T2)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = export_model_input_bundle(
                host, profile, endpoint=source_endpoint,
                assay_context={"status": "unknown", "conditions": {}, "evidence": []},
                bundle_id="verified-source-fixture", output_dir=root / "bundle", created_at=T2,
            )
            bundle = load_model_input_bundle(path)
            for status in ("uncalibrated_score", "probability"):
                with self.subTest(status=status):
                    result = {
                        "schema_version": 1, "kind": "pair_prediction", "prediction_id": status,
                        "bundle_id": bundle["bundle_id"], "bundle_sha256": bundle["content_sha256"],
                        "created_at": T2,
                        "estimate": {"status": status, "value": 0.7, "reason": "Software fixture only.",
                                     "uncertainty": {"lower": 0.6, "upper": 0.8, "method": "fixture"}},
                        "producer": {"name": "fixture", "version": "1", "artifact_sha256": "a" * 64,
                                     "preprocessing_sha256": "b" * 64, "calibration_sha256": "c" * 64},
                        "limitations": ["Software fixture only; no biological verification."],
                    }
                    result["content_sha256"] = canonical_content_sha256(result)
                    out = root / "result.json"
                    out.write_text(json.dumps(result))
                    admitted = load_pair_prediction(out, path)
                    self.assertEqual(admitted["estimate"]["status"], status)
                    with self.assertRaisesRegex(ValueError, "ModelResult"):
                        model_result_from_dict(admitted)
                    with self.assertRaisesRegex(ValueError, "InteractionPrediction"):
                        interaction_prediction_from_dict(admitted)
                    with self.assertRaisesRegex(ValueError, "ModelResult"):
                        admit_model_result(request, admitted, host, profile, prediction_id="invalid")
                    with self.assertRaisesRegex(ValueError, "InteractionPrediction"):
                        recommend_natural_phages(
                            host, [profile], [admitted], candidate_set_id="invalid", created_at=T2,
                        )

    def test_resealed_endpoint_or_context_cannot_reuse_a_source_result(self):
        original_path = self.fixture / "bundle.json"
        original = load_model_input_bundle(original_path)
        result = {
            "schema_version": 1, "kind": "pair_prediction", "prediction_id": "unresolved",
            "bundle_id": original["bundle_id"], "bundle_sha256": original["content_sha256"],
            "created_at": "2026-10-19T12:00:00Z",
            "estimate": {"status": "not_estimated", "value": None, "uncertainty": None,
                         "reason": "Software fixture only."},
            "producer": {"name": "fixture", "version": "1", "artifact_sha256": None,
                         "preprocessing_sha256": None, "calibration_sha256": None},
            "limitations": ["Software fixture only."],
        }
        result["content_sha256"] = canonical_content_sha256(result)
        for field, value in (
            ("endpoint", {**original["endpoint"], "endpoint_id": "different-source:v2"}),
            ("assay_context", {"status": "declared", "conditions": {"fixture": True},
                               "evidence": ["software-fixture"]}),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                shutil.copytree(self.fixture, root / "bundle")
                path = root / "bundle/bundle.json"
                changed = copy.deepcopy(original)
                changed[field] = value
                changed["content_sha256"] = canonical_content_sha256(changed)
                path.write_text(json.dumps(changed))
                load_model_input_bundle(path)  # Valid changed input, not a corrupt manifest.
                out = root / "result.json"
                out.write_text(json.dumps(result))
                with self.assertRaisesRegex(ValueError, "exact bundle"):
                    load_pair_prediction(out, path)

    def test_freezes_values_and_unknowns_not_only_fingerprints(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.export(Path(directory))
            bundle = load_model_input_bundle(path)
            self.assertEqual(bundle["host_state"], state().to_dict())
            self.assertEqual(bundle["phage_profile"], phage("bundle-phage").to_dict())
            self.assertEqual(bundle["sequence_status"], {"host": "not_provided", "phage": "not_provided"})
            self.assertEqual(bundle["resources"], [])
            self.assertEqual(bundle["endpoint"]["assay_definition_status"], "unverified")

    def test_exports_real_readable_sequence_and_detects_modified_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fasta = root / "host.fna"
            fasta.write_bytes(b">fixture\nACGT\n")
            registry = root / "registry.json"
            registered = create_sequence_registry(fasta, registry, registry_id="fixture")
            host = replace(state(), host_genome_sha256=registered["asset"].sequence_sha256)
            path = export_model_input_bundle(
                host, phage("bundle-phage"), endpoint=endpoint(),
                assay_context={"status": "unknown", "conditions": {}, "evidence": []},
                bundle_id="sequence-bundle", output_dir=root / "export", created_at=T2,
                sequence_registry=registry, include_sequences=("host",),
            )
            bundle = load_model_input_bundle(path, required_sequences=("host",))
            resource = bundle["resources"][0]
            copied = path.parent / resource["path"]
            self.assertEqual(copied.read_bytes(), fasta.read_bytes())
            copied.write_bytes(b">changed\nACGT\n")
            with self.assertRaisesRegex(ValueError, "digest|SHA-256|size"):
                load_model_input_bundle(path)

    def test_sequence_requirement_and_overwrite_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.export(root)
            with self.assertRaisesRegex(ValueError, "required.*host|host.*required"):
                load_model_input_bundle(path, required_sequences=("host",))
            with self.assertRaisesRegex(ValueError, "exist|overwrite"):
                self.export(root)

    def test_changed_endpoint_and_future_snapshot_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.export(Path(directory))
            bundle = json.loads(path.read_text())
            bundle["endpoint"]["definition"] = "invented meaning"
            path.write_text(json.dumps(bundle))
            with self.assertRaisesRegex(ValueError, "hash|digest"):
                load_model_input_bundle(path)
            bundle["created_at"] = "2025-01-01T00:00:00Z"
            bundle["content_sha256"] = canonical_content_sha256(bundle)
            path.write_text(json.dumps(bundle))
            with self.assertRaisesRegex(ValueError, "predate|future"):
                load_model_input_bundle(path)

    def test_phage_accession_requires_the_exact_source_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fasta = root / "phage.fna"
            fasta.write_bytes(b">software-fixture\nACGT\n")
            registry = root / "registry.json"
            create_sequence_registry(fasta, registry, registry_id="phage-fixture", kind="phage_sequence",
                                     accession="FIXTURE_001", source_snapshot_sha256="c" * 64)
            profile = replace(phage("retrieved"), sequence=SequenceRef(accession="FIXTURE_001"),
                              provenance=RetrievedProvenance(source_db="fixture", accession="FIXTURE_001",
                                  retrieved_at=T2, source_uri="https://example.org/software-fixture",
                                  snapshot_version="1", snapshot_sha256="c" * 64))
            options = dict(endpoint=endpoint(), assay_context={"status": "unknown", "conditions": {}, "evidence": []},
                           created_at=T2, sequence_registry=registry, include_sequences=("phage",))
            path = export_model_input_bundle(
                state(), profile, bundle_id="phage-fixture", output_dir=root / "export", **options
            )
            self.assertEqual(
                load_model_input_bundle(path, required_sequences=("phage",))["resources"][0]["accession"],
                "FIXTURE_001",
            )
            wrong = replace(profile, provenance=replace(profile.provenance, snapshot_sha256="d" * 64))
            with self.assertRaisesRegex(ValueError, "matching|snapshot"):
                export_model_input_bundle(
                    state(), wrong, bundle_id="wrong-snapshot", output_dir=root / "wrong", **options
                )
            self.assertFalse((root / "wrong").exists())

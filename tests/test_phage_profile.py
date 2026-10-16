import json
from pathlib import Path
import tempfile
import unittest

from phage_lab.phage_profile import (
    EngineeredProvenance,
    NaturalProvenance,
    PhageProfile,
    RetrievedProvenance,
    SequenceRef,
    load_phage_profile,
    new_engineered_phage_profile,
    new_natural_phage_profile,
    phage_profile_from_dict,
    retrieved_candidate_to_phage_profile,
    write_phage_profile,
)


STAMP = "2026-10-16T17:00:00+00:00"
DIGEST = "a" * 64


def retrieved_candidate(**overrides):
    record = {
        "id": "NC_000866.4",
        "accession": "NC_000866.4",
        "source_db": "inphared",
        "retrieved_at": STAMP,
        "source_uri": "https://example.org/inphared.tsv",
        "snapshot_version": "1Oct2026",
        "snapshot_sha256": DIGEST,
        "description": "Escherichia phage T4",
        "recorded_host": "Escherichia coli",
        "host_annotation_source": "depositor_metadata",
        "classification": "Tevenvirinae",
        "genome_length": "168903",
        "host_query": "Escherichia coli",
        "ranking": {
            "tool": "phist",
            "reported": True,
            "rank": 1,
        },
    }
    record.update(overrides)
    return record


class RetrievedProfileTests(unittest.TestCase):
    def test_candidate_becomes_retrieved_profile_without_interaction_context(self):
        profile = retrieved_candidate_to_phage_profile(
            retrieved_candidate(), created_at=STAMP
        )
        payload = profile.to_dict()

        self.assertEqual(profile.profile_id, "NC_000866.4:v1")
        self.assertEqual(payload["provenance"]["kind"], "retrieved")
        self.assertEqual(payload["provenance"]["source_db"], "inphared")
        self.assertEqual(payload["sequence"]["accession"], "NC_000866.4")
        self.assertEqual(payload["sequence"]["length"], 168903)
        self.assertEqual(
            payload["source_annotations"]["recorded_host"], "Escherichia coli"
        )
        self.assertNotIn("host_query", payload["source_annotations"])
        self.assertNotIn("ranking", payload["source_annotations"])
        self.assertNotIn("ranking", json.dumps(payload).lower())

    def test_retrieved_does_not_claim_natural_origin(self):
        profile = retrieved_candidate_to_phage_profile(
            retrieved_candidate(), created_at=STAMP
        )
        self.assertIsInstance(profile.provenance, RetrievedProvenance)
        self.assertEqual(profile.provenance.kind, "retrieved")
        self.assertNotIn("natural", profile.provenance.to_dict())

    def test_snapshot_fields_are_paired(self):
        for missing in ("snapshot_version", "snapshot_sha256"):
            candidate = retrieved_candidate()
            candidate.pop(missing)
            with self.subTest(missing=missing), self.assertRaisesRegex(
                ValueError, "provided together"
            ):
                retrieved_candidate_to_phage_profile(candidate)

    def test_simulated_candidate_is_refused(self):
        with self.assertRaisesRegex(ValueError, "simulated"):
            retrieved_candidate_to_phage_profile(
                retrieved_candidate(simulated=True)
            )


class NaturalProfileTests(unittest.TestCase):
    def test_natural_profile_has_collection_lineage_without_fake_accession(self):
        profile = new_natural_phage_profile(
            "local-phage-01",
            collection_id="lab-collection",
            isolate_id="isolate-17",
            recorded_at=STAMP,
            source_description="Locally tracked natural isolate.",
            sequence=SequenceRef(sha256=DIGEST, length=42000),
            created_at=STAMP,
        )
        payload = profile.to_dict()

        self.assertIsInstance(profile.provenance, NaturalProvenance)
        self.assertEqual(payload["provenance"]["kind"], "natural")
        self.assertEqual(payload["provenance"]["isolate_id"], "isolate-17")
        self.assertNotIn("accession", payload["provenance"])
        self.assertEqual(payload["sequence"]["sha256"], DIGEST)


class EngineeredProfileTests(unittest.TestCase):
    def test_engineered_profile_preserves_parent_lineage(self):
        profile = new_engineered_phage_profile(
            "design-001",
            design_id="design-job-001",
            parent_profile_ids=("NC_000866.4:v1",),
            designed_at=STAMP,
            design_tool="design-system",
            design_version="0.1",
            created_at=STAMP,
        )
        payload = profile.to_dict()

        self.assertIsInstance(profile.provenance, EngineeredProvenance)
        self.assertEqual(payload["provenance"]["kind"], "engineered")
        self.assertEqual(
            payload["provenance"]["parent_profile_ids"],
            ["NC_000866.4:v1"],
        )
        self.assertNotIn("accession", payload["provenance"])

    def test_engineered_profile_requires_parent(self):
        with self.assertRaisesRegex(ValueError, "at least one parent"):
            new_engineered_phage_profile(
                "design-001",
                design_id="design-job-001",
                parent_profile_ids=(),
                designed_at=STAMP,
                created_at=STAMP,
            )

    def test_engineered_profile_cannot_parent_itself(self):
        with self.assertRaisesRegex(ValueError, "cannot name itself"):
            new_engineered_phage_profile(
                "design-001",
                design_id="design-job-001",
                parent_profile_ids=("design-001:v1",),
                designed_at=STAMP,
                created_at=STAMP,
            )

    def test_engineered_parent_ids_are_unique(self):
        with self.assertRaisesRegex(ValueError, "unique"):
            new_engineered_phage_profile(
                "design-001",
                design_id="design-job-001",
                parent_profile_ids=("parent:v1", "parent:v1"),
                designed_at=STAMP,
                created_at=STAMP,
            )


class SerializationTests(unittest.TestCase):
    def profiles(self):
        return (
            retrieved_candidate_to_phage_profile(
                retrieved_candidate(), created_at=STAMP
            ),
            new_natural_phage_profile(
                "local-phage-01",
                collection_id="lab-collection",
                isolate_id="isolate-17",
                recorded_at=STAMP,
                source_description="Natural isolate.",
                created_at=STAMP,
            ),
            new_engineered_phage_profile(
                "design-001",
                design_id="design-job-001",
                parent_profile_ids=("NC_000866.4:v1",),
                designed_at=STAMP,
                created_at=STAMP,
            ),
        )

    def test_all_provenance_variants_round_trip(self):
        for profile in self.profiles():
            with self.subTest(kind=profile.provenance.kind):
                rebuilt = phage_profile_from_dict(profile.to_dict())
                self.assertEqual(rebuilt.to_dict(), profile.to_dict())

    def test_file_round_trip(self):
        profile = self.profiles()[0]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "phage-profile.json"
            write_phage_profile(profile, path)
            loaded = load_phage_profile(path)
        self.assertEqual(loaded.to_dict(), profile.to_dict())

    def test_profile_id_is_checked(self):
        payload = self.profiles()[0].to_dict()
        payload["profile_id"] = "wrong:v1"
        with self.assertRaisesRegex(ValueError, "profile_id"):
            phage_profile_from_dict(payload)

    def test_sequence_requires_identity(self):
        with self.assertRaisesRegex(ValueError, "accession or sha256"):
            SequenceRef()


class CliTests(unittest.TestCase):
    def test_candidate_file_converts_to_retrieved_profiles(self):
        from phage_lab.__main__ import main

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidates = root / "candidates.json"
            output = root / "phage-profiles.json"
            candidates.write_text(
                json.dumps([retrieved_candidate()]),
                encoding="utf-8",
            )
            self.assertEqual(
                0,
                main([
                    "phage-profiles",
                    "--candidates", str(candidates),
                    "--out", str(output),
                ]),
            )
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(len(payload), 1)
            self.assertEqual(payload[0]["provenance"]["kind"], "retrieved")
            self.assertNotIn("ranking", json.dumps(payload).lower())


if __name__ == "__main__":
    unittest.main()

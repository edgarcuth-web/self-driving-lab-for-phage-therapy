import json
from pathlib import Path
import tempfile
import unittest

from phage_lab.biology import GenomeSummary
from phage_lab.host_profile import (
    AnalysisRun,
    FEATURE_GROUPS,
    FeatureGroup,
    FeatureItem,
    HostProfile,
    host_profile_from_dict,
    load_host_profile,
    new_host_profile,
    write_host_profile,
)


DIGEST = "a" * 64
CREATED_AT = "2026-10-16T12:00:00+00:00"


class HostProfileTests(unittest.TestCase):
    def setUp(self):
        self.genome = GenomeSummary(sha256=DIGEST, bases=5_000_000, contigs=1)

    def test_new_profile_starts_unknown_without_sequence_content(self):
        profile = new_host_profile(
            "isolate-001", self.genome, created_at=CREATED_AT
        )
        payload = profile.to_dict()

        self.assertEqual(profile.profile_id, "isolate-001:v1")
        self.assertEqual(set(payload["features"]), set(FEATURE_GROUPS))
        self.assertTrue(
            all(group["status"] == "unknown" for group in payload["features"].values())
        )
        self.assertTrue(
            all(group["items"] == [] for group in payload["features"].values())
        )
        self.assertEqual(
            set(payload["genome"]), {"sha256", "bases", "contigs"}
        )
        self.assertNotIn("sequence", json.dumps(payload).lower())

    def test_unknown_feature_group_cannot_report_items(self):
        item = FeatureItem(name="example", source="unit-test")
        with self.assertRaisesRegex(ValueError, "unknown feature group"):
            FeatureGroup(status="unknown", items=(item,))

    def test_assessed_empty_group_is_distinct_from_unknown(self):
        group = FeatureGroup(
            status="assessed",
            items=(),
            note="Analyzer ran and reported no admitted features.",
        )
        self.assertEqual(group.to_dict()["status"], "assessed")
        self.assertEqual(group.to_dict()["items"], [])

    def test_analysis_run_must_match_profile_genome(self):
        features = {name: FeatureGroup() for name in FEATURE_GROUPS}
        wrong = AnalysisRun(
            analyzer="example",
            version="1.0",
            analyzed_at=CREATED_AT,
            input_sha256="b" * 64,
        )
        with self.assertRaisesRegex(ValueError, "must match"):
            HostProfile(
                host_id="isolate-001",
                revision=1,
                genome=self.genome,
                taxonomy={},
                features=features,
                analysis_runs=(wrong,),
                created_at=CREATED_AT,
            )

    def test_round_trip_preserves_profile(self):
        profile = new_host_profile(
            "isolate-001",
            self.genome,
            taxonomy={"species": "Example species"},
            created_at=CREATED_AT,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            write_host_profile(profile, path)
            loaded = load_host_profile(path)
        self.assertEqual(loaded.to_dict(), profile.to_dict())

    def test_profile_id_is_checked_on_load(self):
        payload = new_host_profile(
            "isolate-001", self.genome, created_at=CREATED_AT
        ).to_dict()
        payload["profile_id"] = "other:v1"
        with self.assertRaisesRegex(ValueError, "profile_id"):
            host_profile_from_dict(payload)


if __name__ == "__main__":
    unittest.main()

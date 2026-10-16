import json
from pathlib import Path
import tempfile
import unittest

from phage_lab.biology import GenomeSummary
from phage_lab.cocktail_design import (
    CocktailDesign,
    CocktailMember,
    DesignObjective,
    cocktail_design_from_dict,
    load_cocktail_design,
    phist_screening_design,
    write_cocktail_design,
)
from phage_lab.host_profile import new_host_profile
from phage_lab.interaction_evidence import (
    EvidenceProducer,
    HostReference,
    InteractionEvidence,
)
from phage_lab.phage_profile import retrieved_candidate_to_phage_profile


STAMP = "2026-10-16T18:00:00+00:00"
HOST_SHA = "a" * 64
SNAPSHOT_SHA = "b" * 64


def host_profile():
    return new_host_profile(
        "isolate-001",
        GenomeSummary(sha256=HOST_SHA, bases=5_000_000, contigs=1),
        created_at=STAMP,
    )


def candidate(identifier: str, rank: int, *, reported: bool = True) -> dict:
    profile_id = f"{identifier}:v1"
    evidence = InteractionEvidence(
        host=HostReference(
            genome_sha256=HOST_SHA,
            profile_id="isolate-001:v1",
        ),
        phage_profile_id=profile_id,
        kind="computational",
        signal="shared_kmer_similarity",
        result={
            "status": "reported_signal" if reported else "no_signal",
            **({"value": 20 - rank} if reported else {}),
        },
        interpretation=(
            "Shared k-mer signal only; not a probability of successful infection."
        ),
        observed_at=STAMP,
        producer=EvidenceProducer(
            name="phist",
            version="1.2.1",
            parameters={"k": 25, "threads": 2},
        ),
        input_provenance={
            "sequence_snapshot_version": "1Oct2026",
            "sequence_snapshot_sha256": SNAPSHOT_SHA,
        },
    )
    return {
        "id": identifier,
        "accession": identifier,
        "source_db": "inphared",
        "retrieved_at": STAMP,
        "source_uri": "https://example.org/data.tsv",
        "snapshot_version": "1Oct2026",
        "snapshot_sha256": SNAPSHOT_SHA,
        "phage_profile_id": profile_id,
        "ranking": {
            "tool": "phist",
            "tool_version": "1.2.1",
            "parameters": {"k": 25, "threads": 2},
            "ranked_at": STAMP,
            "host_genome_sha256": HOST_SHA,
            "statistic": "shared_25mers",
            "interpretation": "not a probability of infection",
            "reported": reported,
            "rank": rank if reported else None,
        },
        "interaction_evidence": [evidence.to_dict()],
    }


def profiles(records: list[dict]):
    return [
        retrieved_candidate_to_phage_profile(record, created_at=STAMP)
        for record in records
    ]


class CocktailDesignTests(unittest.TestCase):
    def baseline(self):
        records = [
            candidate("PH-003", 3),
            candidate("PH-001", 1),
            candidate("PH-002", 2),
        ]
        return phist_screening_design(
            host_profile(),
            profiles(records),
            records,
            cocktail_id="cocktail-001",
            min_members=2,
            max_members=2,
            created_at=STAMP,
        )

    def test_baseline_selects_supported_members_in_cohort_rank_order(self):
        design = self.baseline()
        payload = design.to_dict()

        self.assertEqual(design.design_id, "cocktail-001:v1")
        self.assertEqual(
            [member.phage_profile_id for member in design.members],
            ["PH-001:v1", "PH-002:v1"],
        )
        self.assertEqual(
            [member.selection_context["phist_rank"] for member in design.members],
            [1, 2],
        )
        self.assertEqual(
            payload["target_host"]["profile_id"], "isolate-001:v1"
        )
        self.assertEqual(
            payload["objectives"][0]["name"], "experimental_screening"
        )
        self.assertEqual(
            payload["designer"]["name"], "phist-screening-baseline"
        )

    def test_rank_is_design_context_not_pairwise_evidence(self):
        design = self.baseline()
        for evidence in design.supporting_evidence:
            self.assertNotIn("rank", evidence.result)
        self.assertTrue(
            all("phist_rank" in member.selection_context for member in design.members)
        )

    def test_design_keeps_uncertainty_explicit(self):
        design = self.baseline()
        gaps = " ".join(design.unresolved_gaps).lower()
        self.assertIn("physical susceptibility", gaps)
        self.assertIn("receptor/rbp", gaps)
        self.assertIn("cross-resistance", gaps)
        self.assertIn("antagonism", gaps)
        self.assertIn("does not claim", design.rationale.lower())

    def test_design_content_hash_detects_tampering(self):
        payload = self.baseline().to_dict()
        rebuilt = cocktail_design_from_dict(payload)
        self.assertEqual(rebuilt.content_sha256, payload["content_sha256"])

        tampered = json.loads(json.dumps(payload))
        tampered["rationale"] = "Changed after design creation."
        with self.assertRaisesRegex(ValueError, "content_sha256"):
            cocktail_design_from_dict(tampered)

    def test_file_round_trip(self):
        design = self.baseline()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "cocktail.json"
            write_cocktail_design(design, path)
            loaded = load_cocktail_design(path)
        self.assertEqual(loaded.to_dict(), design.to_dict())

    def test_baseline_refuses_to_top_up_with_no_signal(self):
        records = [
            candidate("PH-001", 1),
            candidate("PH-002", 2, reported=False),
        ]
        with self.assertRaisesRegex(ValueError, "Only 1 candidate"):
            phist_screening_design(
                host_profile(),
                profiles(records),
                records,
                cocktail_id="cocktail-001",
                created_at=STAMP,
            )

    def test_baseline_requires_matching_phage_profiles(self):
        records = [candidate("PH-001", 1), candidate("PH-002", 2)]
        with self.assertRaisesRegex(ValueError, "no matching PhageProfile"):
            phist_screening_design(
                host_profile(),
                profiles(records[:1]),
                records,
                cocktail_id="cocktail-001",
                created_at=STAMP,
            )

    def test_member_cannot_use_evidence_for_another_phage(self):
        records = [candidate("PH-001", 1), candidate("PH-002", 2)]
        design = phist_screening_design(
            host_profile(),
            profiles(records),
            records,
            cocktail_id="cocktail-001",
            created_at=STAMP,
        )
        with self.assertRaisesRegex(ValueError, "different phage"):
            CocktailDesign(
                cocktail_id="bad",
                revision=1,
                target_host=design.target_host,
                members=(
                    CocktailMember(
                        phage_profile_id="PH-001:v1",
                        evidence_ids=(
                            design.supporting_evidence[1].evidence_id,
                        ),
                    ),
                    design.members[1],
                ),
                supporting_evidence=design.supporting_evidence,
                objectives=(DesignObjective("screen", "Test evidence lineage."),),
                assumptions=(),
                unresolved_gaps=(),
                rationale="Invalid test design.",
                designer=EvidenceProducer(name="test", version="1"),
                created_at=STAMP,
            )

    def test_supporting_evidence_must_match_target_host(self):
        records = [candidate("PH-001", 1), candidate("PH-002", 2)]
        design = phist_screening_design(
            host_profile(),
            profiles(records),
            records,
            cocktail_id="cocktail-001",
            created_at=STAMP,
        )
        with self.assertRaisesRegex(ValueError, "different host genome"):
            CocktailDesign(
                cocktail_id="bad",
                revision=1,
                target_host=HostReference(
                    genome_sha256="c" * 64,
                    profile_id="isolate-other:v1",
                ),
                members=design.members,
                supporting_evidence=design.supporting_evidence,
                objectives=design.objectives,
                assumptions=design.assumptions,
                unresolved_gaps=design.unresolved_gaps,
                rationale=design.rationale,
                designer=design.designer,
                created_at=STAMP,
            )


if __name__ == "__main__":
    unittest.main()

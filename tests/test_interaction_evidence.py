import json
from pathlib import Path
import tempfile
import unittest

from phage_lab.interaction_evidence import (
    EvidenceProducer,
    HostReference,
    InteractionEvidence,
    interaction_evidence_from_dict,
    load_interaction_evidence,
    phist_ranking_to_evidence,
    write_interaction_evidence,
)


STAMP = "2026-10-16T17:30:00+00:00"
HOST_SHA = "c" * 64
SNAPSHOT_SHA = "d" * 64


def ranked_candidate(*, reported=True):
    ranking = {
        "tool": "phist",
        "tool_version": "1.2.1",
        "parameters": {"k": 25, "threads": 2},
        "ranked_at": STAMP,
        "host_genome_sha256": HOST_SHA,
        "sequence_snapshot_version": "1Oct2026",
        "sequence_snapshot_sha256": SNAPSHOT_SHA,
        "statistic": "shared_25mers",
        "interpretation": (
            "Shared k-mers between phage and host genomes. "
            "It is not a probability of successful infection."
        ),
        "reported": reported,
        "rank": 1 if reported else None,
    }
    if reported:
        ranking.update({"value": 17, "pvalue": 1e-8, "adj_pvalue": 1e-7})
    else:
        ranking["note"] = (
            "No significant k-mer sharing was reported; this is not evidence "
            "that infection cannot occur."
        )
    return {"id": "PH-001", "ranking": ranking}


class InteractionEvidenceTests(unittest.TestCase):
    def test_evidence_id_is_content_addressed(self):
        evidence = InteractionEvidence(
            host=HostReference(genome_sha256=HOST_SHA),
            phage_profile_id="PH-001:v1",
            kind="computational",
            signal="example_signal",
            result={"status": "reported_signal", "value": 3},
            interpretation="Example source statistic only.",
            observed_at=STAMP,
            producer=EvidenceProducer(
                name="example-tool",
                version="1.0",
                parameters={"threshold": 2},
            ),
        )
        first = evidence.to_dict()
        rebuilt = interaction_evidence_from_dict(first)
        self.assertEqual(rebuilt.evidence_id, evidence.evidence_id)

        tampered = json.loads(json.dumps(first))
        tampered["result"]["value"] = 4
        with self.assertRaisesRegex(ValueError, "evidence_id"):
            interaction_evidence_from_dict(tampered)

    def test_probability_shaped_result_is_refused(self):
        with self.assertRaisesRegex(ValueError, "probability-shaped"):
            InteractionEvidence(
                host=HostReference(genome_sha256=HOST_SHA),
                phage_profile_id="PH-001:v1",
                kind="computational",
                signal="example_signal",
                result={"infection_probability": 0.9},
                interpretation="Not admitted.",
                observed_at=STAMP,
                producer=EvidenceProducer(name="example", version="1"),
            )

    def test_file_round_trip(self):
        evidence = phist_ranking_to_evidence(ranked_candidate())
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "evidence.json"
            write_interaction_evidence(evidence, path)
            loaded = load_interaction_evidence(path)
        self.assertEqual(loaded.to_dict(), evidence.to_dict())


class PhistEvidenceTests(unittest.TestCase):
    def test_reported_phist_result_becomes_computational_evidence(self):
        evidence = phist_ranking_to_evidence(
            ranked_candidate(), host_profile_id="isolate-001:v1"
        )
        payload = evidence.to_dict()

        self.assertEqual(payload["kind"], "computational")
        self.assertEqual(payload["signal"], "shared_kmer_similarity")
        self.assertEqual(payload["host"]["profile_id"], "isolate-001:v1")
        self.assertEqual(payload["host"]["genome_sha256"], HOST_SHA)
        self.assertEqual(payload["phage_profile_id"], "PH-001:v1")
        self.assertEqual(payload["producer"]["name"], "phist")
        self.assertEqual(payload["producer"]["version"], "1.2.1")
        self.assertEqual(payload["result"]["status"], "reported_signal")
        self.assertEqual(payload["result"]["value"], 17)
        self.assertEqual(payload["result"]["rank"], 1)
        self.assertNotIn("probability", payload["result"])
        self.assertEqual(
            payload["input_provenance"]["sequence_snapshot_sha256"],
            SNAPSHOT_SHA,
        )

    def test_unreported_phist_result_is_no_signal_not_negative_phenotype(self):
        evidence = phist_ranking_to_evidence(ranked_candidate(reported=False))
        payload = evidence.to_dict()

        self.assertEqual(payload["result"]["status"], "no_signal")
        self.assertIsNone(payload["result"]["rank"])
        self.assertNotIn("value", payload["result"])
        self.assertIn(
            "not evidence that infection cannot occur",
            payload["interpretation"],
        )
        serialized = json.dumps(payload).lower()
        self.assertNotIn("resistant", serialized)
        self.assertNotIn("susceptible", serialized)

    def test_phist_adapter_rejects_other_tools(self):
        candidate = ranked_candidate()
        candidate["ranking"]["tool"] = "other"
        with self.assertRaisesRegex(ValueError, "only PHIST"):
            phist_ranking_to_evidence(candidate)


if __name__ == "__main__":
    unittest.main()

import json
import os
from pathlib import Path
import tempfile
import textwrap
import unittest
import unittest.mock

from phage_lab.interaction_evidence import phist_ranking_to_evidence
from phage_lab.ranking import (
    PhistRanker,
    RankingError,
    assert_no_invented_probability,
    phist_from_environment,
)
from phage_lab.sequences import SequenceError, SequenceStore, build_index
from phage_lab.snapshots import create_snapshot, load_snapshot
from phage_lab.workflow import WorkflowError, validate_experiment_inputs

from support import RealDeviceDouble

GENOMES = "".join(
    f">{accession} Phage {accession}\n" + ("ACGTTGCA" * 8) + "\n"
    for accession in ("PH-001", "PH-002", "PH-003"))

PROVENANCE = {"source_db": "inphared", "retrieved_at": "2026-10-15T00:00:00+00:00",
              "source_uri": "https://example.org/data.tsv",
              "snapshot_version": "1Oct2026", "snapshot_sha256": "b" * 64}
CANDIDATES = [{"id": accession, "accession": accession, **PROVENANCE}
              for accession in ("PH-001", "PH-002", "PH-003")]


def sequence_store(root: Path, content: str = GENOMES) -> SequenceStore:
    root.mkdir(parents=True, exist_ok=True)
    upstream = root / "genomes.fa"
    upstream.write_text(content, encoding="utf-8")
    directory = root / "seqs"
    create_snapshot(directory, source="inphared", version="1Oct2026",
                    source_uri="https://example.org/genomes.fa", from_file=upstream)
    return SequenceStore(load_snapshot(directory))


def fake_phist(root: Path, body: str) -> Path:
    """A stand-in phist.py, so the adapter's invocation and parsing are testable."""
    script = root / "phist.py"
    script.write_text(textwrap.dedent(body), encoding="utf-8")
    return script


WORKING_PHIST = '''
    import sys
    from pathlib import Path
    if "--version" in sys.argv:
        print("9.9.9-test")
        raise SystemExit(0)
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    numeric = {"-k", "-t"}
    positional = []
    skip = False
    for index, value in enumerate(sys.argv[1:]):
        if skip:
            skip = False
            continue
        if value in numeric:
            skip = True
            continue
        positional.append(value)
    virus_dir, host_dir, out_dir = (Path(p) for p in positional[:3])
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = ["phage,host,#common-kmers,pvalue,adj-pvalue"]
    for index, path in enumerate(sorted(virus_dir.glob("*.fna"))):
        if path.stem == "PH-002":
            rows.append(path.name)          # reported with no match, one field only
        else:
            rows.append(f"{path.name},host.fna,{100 - index * 10},1e-10,1e-9")
    (out_dir / "predictions.csv").write_text("\\n".join(rows) + "\\n")
'''


class SequenceStoreTests(unittest.TestCase):
    def test_sequences_are_indexed_and_retrieved_by_accession(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = sequence_store(Path(temporary))
            self.assertEqual(store.describe()["sequences"], 3)
            record = store.get("PH-002")
            self.assertEqual(record.accession, "PH-002")
            self.assertEqual(len(record.sequence), 64)
            self.assertTrue(record.to_fasta().startswith(">PH-002 Phage PH-002\n"))

    def test_index_is_cached_and_rebuilt_when_the_snapshot_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = sequence_store(root)
            index_path = store.snapshot.directory / "accession_index.json"
            self.assertTrue(index_path.is_file())
            cached = json.loads(index_path.read_text())
            self.assertEqual(cached["snapshot_sha256"], store.snapshot.sha256)
            # A cache recorded against a different snapshot is not reused.
            index_path.write_text(json.dumps({**cached, "snapshot_sha256": "a" * 64}))
            self.assertEqual(set(build_index(store.snapshot)), {"PH-001", "PH-002", "PH-003"})

    def test_missing_and_duplicate_accessions_are_reported(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = sequence_store(root)
            self.assertEqual(store.missing(["PH-001", "PH-404"]), ["PH-404"])
            with self.assertRaisesRegex(SequenceError, "not in sequence snapshot"):
                store.get("PH-404")
            with self.assertRaisesRegex(SequenceError, "duplicate accessions"):
                sequence_store(root / "dup", GENOMES + ">PH-001 again\nACGT\n")

    def test_write_fasta_dir_names_files_recoverably(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = sequence_store(root)
            written = store.write_fasta_dir(["PH-001", "PH-003"], root / "virus")
            self.assertEqual({path.name for path in written.values()},
                             {"PH-001.fna", "PH-003.fna"})


class PhistAdapterTests(unittest.TestCase):
    def test_ranking_orders_reported_candidates_and_labels_the_rest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = sequence_store(root)
            host = root / "host.fna"
            host.write_text(">host\nACGTACGT\n")
            ranker = PhistRanker(fake_phist(root, WORKING_PHIST))
            self.assertEqual(ranker.version(), "9.9.9-test")
            ranked = ranker.rank(host, CANDIDATES, store)

            self.assertEqual([record["id"] for record in ranked],
                             ["PH-001", "PH-003", "PH-002"])
            self.assertEqual([record["ranking"]["rank"] for record in ranked], [1, 2, None])
            self.assertEqual([record["ranking"]["reported"] for record in ranked],
                             [True, True, False])
            self.assertIn("not a probability", ranked[0]["ranking"]["interpretation"])
            self.assertIn("not evidence that infection cannot occur",
                          ranked[-1]["ranking"]["note"])
            for record in ranked:
                self.assertEqual(record["ranking"]["tool"], "phist")
                self.assertEqual(len(record["ranking"]["host_genome_sha256"]), 64)
                self.assertEqual(record["ranking"]["sequence_snapshot_version"], "1Oct2026")
                self.assertEqual(len(record["interaction_evidence"]), 1)
                evidence = record["interaction_evidence"][0]
                self.assertEqual(evidence["producer"]["name"], "phist")
                self.assertEqual(
                    evidence["host"]["genome_sha256"],
                    record["ranking"]["host_genome_sha256"],
                )
                self.assertEqual(
                    evidence["phage_profile_id"], f"{record['id']}:v1"
                )
                expected = (
                    "reported_signal"
                    if record["ranking"]["reported"]
                    else "no_signal"
                )
                self.assertEqual(evidence["result"]["status"], expected)

    def test_a_value_less_row_is_no_match_rather_than_a_parse_error(self):
        # Real PHIST writes the phage name alone when nothing matched; that is an
        # answer, and a crash here would turn "no signal" into a failed run.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = sequence_store(root)
            host = root / "host.fna"
            host.write_text(">host\nACGTACGT\n")
            ranked = PhistRanker(fake_phist(root, WORKING_PHIST)).rank(host, CANDIDATES, store)
            unreported = [r for r in ranked if not r["ranking"]["reported"]]
            self.assertEqual([record["id"] for record in unreported], ["PH-002"])
            self.assertNotIn("value", unreported[0]["ranking"])

    def test_a_missing_tool_is_an_error_not_a_fallback_ordering(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(RankingError, "never falls back"):
                PhistRanker(root / "nowhere" / "phist.py")
            with self.assertRaisesRegex(RankingError, "no built-in fallback"):
                with unittest.mock.patch.dict(os.environ, {"PHIST_PATH": ""}, clear=False):
                    with unittest.mock.patch("shutil.which", return_value=None):
                        phist_from_environment(None)

    def test_a_failing_tool_does_not_produce_a_ranking(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = sequence_store(root)
            host = root / "host.fna"
            host.write_text(">host\nACGTACGT\n")
            broken = fake_phist(root, '''
                import sys
                if "--version" in sys.argv:
                    print("9.9.9-test")
                    raise SystemExit(0)
                sys.stderr.write("kmer-db exploded\\n")
                raise SystemExit(3)
            ''')
            with self.assertRaisesRegex(RankingError, "not ordered"):
                PhistRanker(broken).rank(host, CANDIDATES, store)

    def test_unexpected_columns_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = sequence_store(root)
            host = root / "host.fna"
            host.write_text(">host\nACGTACGT\n")
            odd = fake_phist(root, '''
                import sys
                from pathlib import Path
                if "--version" in sys.argv:
                    print("9.9.9-test")
                    raise SystemExit(0)
                out = Path([a for a in sys.argv[1:] if not a.startswith("-")][-1])
                out.mkdir(parents=True, exist_ok=True)
                (out / "predictions.csv").write_text("phage,host,score\\nPH-001.fna,h,5\\n")
            ''')
            with self.assertRaisesRegex(RankingError, "expected columns"):
                PhistRanker(odd).rank(host, CANDIDATES, store)

    def test_candidates_without_sequences_are_refused_before_running(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = sequence_store(root)
            host = root / "host.fna"
            host.write_text(">host\nACGTACGT\n")
            extra = [*CANDIDATES, {"id": "PH-404", "accession": "PH-404", **PROVENANCE}]
            with self.assertRaisesRegex(RankingError, "no genome for PH-404"):
                PhistRanker(fake_phist(root, WORKING_PHIST)).rank(host, extra, store)

    def test_guard_rejects_a_probability_shaped_field(self):
        assert_no_invented_probability({"ranking": {"value": 10}})
        for field in ("infection_probability", "success_likelihood", "efficacy"):
            with self.subTest(field=field), self.assertRaises(RankingError):
                assert_no_invented_probability({"ranking": {field: 0.9}})


class RankingProvenanceTests(unittest.TestCase):
    """The experiment path checks a ranking block before planning on it."""

    def setUp(self):
        self.devices = {"prepare-1": RealDeviceDouble("prepare-1", "prepare")}
        self.block = {"tool": "phist", "tool_version": "1.2.1",
                      "parameters": {"k": 25, "threads": 2},
                      "ranked_at": "2026-10-15T00:00:00+00:00",
                      "host_genome_sha256": "c" * 64, "statistic": "shared_25mers",
                      "interpretation": "not a probability of infection",
                      "reported": True, "rank": 1}

    def ranked(self, **overrides):
        return [{**CANDIDATES[0], "ranking": {**self.block, **overrides}}]

    def check(self, candidates):
        validate_experiment_inputs(candidates, self.devices, "real_hardware")

    def test_a_complete_ranking_block_is_accepted(self):
        self.check(self.ranked())

    def test_every_required_ranking_field_is_checked(self):
        for field in ("tool", "tool_version", "ranked_at", "host_genome_sha256",
                      "statistic", "interpretation", "reported"):
            block = {key: value for key, value in self.block.items() if key != field}
            with self.subTest(missing=field), self.assertRaises(WorkflowError):
                self.check([{**CANDIDATES[0], "ranking": block}])

    def test_reported_requires_a_rank_and_unreported_forbids_one(self):
        with self.assertRaisesRegex(WorkflowError, "no positive rank"):
            self.check(self.ranked(rank=None))
        with self.assertRaisesRegex(WorkflowError, "carries a rank"):
            self.check(self.ranked(reported=False, rank=2))
        self.check(self.ranked(reported=False, rank=None))

    def test_a_probability_field_in_a_ranking_block_is_refused(self):
        with self.assertRaisesRegex(WorkflowError, "probability of infection"):
            self.check(self.ranked(infection_probability=0.8))

    def test_rankings_from_different_tools_or_hosts_cannot_be_mixed(self):
        mixed = [{**CANDIDATES[0], "ranking": dict(self.block)},
                 {**CANDIDATES[1], "ranking": {**self.block, "host_genome_sha256": "d" * 64}}]
        with self.assertRaisesRegex(WorkflowError, "separate comparisons"):
            self.check(mixed)

    def test_tampered_interaction_evidence_is_refused(self):
        candidate = self.ranked()[0]
        evidence = phist_ranking_to_evidence(candidate).to_dict()
        evidence["result"]["status"] = "tampered"
        candidate["interaction_evidence"] = [evidence]
        with self.assertRaisesRegex(WorkflowError, "evidence_id"):
            self.check([candidate])

    def test_interaction_evidence_must_target_candidate_profile(self):
        candidate = self.ranked()[0]
        other = {**candidate, "id": "PH-OTHER"}
        candidate["interaction_evidence"] = [
            phist_ranking_to_evidence(other).to_dict()
        ]
        with self.assertRaisesRegex(WorkflowError, "not 'PH-001:v1'"):
            self.check([candidate])

    def test_a_partly_ranked_set_is_refused(self):
        partial = [{**CANDIDATES[0], "ranking": dict(self.block)}, CANDIDATES[1]]
        with self.assertRaisesRegex(WorkflowError, "partial ordering"):
            self.check(partial)


@unittest.skipUnless(os.environ.get("PHIST_PATH"),
                     "Set PHIST_PATH to phist.py to run against the real tool.")
class RealPhistTests(unittest.TestCase):
    """Opt-in: exercises the adapter against an installed PHIST."""

    def test_real_phist_produces_a_ranking(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = sequence_store(root)
            host = root / "host.fna"
            host.write_text(">host\n" + ("ACGTTGCA" * 500) + "\n")
            ranker = phist_from_environment(os.environ["PHIST_PATH"])
            ranked = ranker.rank(host, CANDIDATES, store)
            self.assertEqual(len(ranked), 3)
            self.assertTrue(all("ranking" in record for record in ranked))
            self.assertTrue(all(record["ranking"]["tool"] == "phist" for record in ranked))
            positions = [r["ranking"]["rank"] for r in ranked if r["ranking"]["reported"]]
            self.assertEqual(positions, list(range(1, len(positions) + 1)))


if __name__ == "__main__":
    unittest.main()

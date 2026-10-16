import json
from pathlib import Path
import tempfile
import unittest

from phage_lab.candidates import InpharedProvider, ProviderError, load_snapshot_dir, open_provider
from phage_lab.snapshots import MANIFEST_NAME, SnapshotError, create_snapshot, load_snapshot
from phage_lab.workflow import WorkflowError, validate_experiment_inputs

from support import RealDeviceDouble

# Shaped like an INPHARED metadata export. The column spellings here are one
# release's; the provider resolves columns by alias, so a release that renames
# them should still load, and one that drops a required column fails loudly.
FIXTURE = "\t".join([
    "Accession", "Description", "Classification", "Genome Length (bp)", "molGC (%)",
    "Molecule", "Number CDS", "Coding Capacity", "Jumbophage", "Host"]) + "\n" + "\n".join([
    "\t".join(["NC_000866.4", "Escherichia phage T4", "Tevenvirinae", "168903", "35.3",
               "DNA", "278", "94.2", "False", "Escherichia coli"]),
    "\t".join(["NC_001895.1", "Escherichia phage P2", "Peduoviridae", "33593", "50.2",
               "DNA", "42", "91.0", "False", "Escherichia coli"]),
    "\t".join(["NC_004166.2", "Pseudomonas phage PaP3", "Autographiviridae", "45503", "55.1",
               "DNA", "71", "92.4", "False", "Pseudomonas aeruginosa"]),
    "\t".join(["NC_005856.1", "Salmonella phage P22", "Lederbergvirus", "41724", "47.1",
               "DNA", "69", "90.3", "False", "Salmonella enterica"]),
    "\t".join(["", "Malformed row with no accession", "", "", "", "", "", "", "", "Escherichia coli"]),
]) + "\n"


def write_snapshot(root: Path, *, content: str = FIXTURE, source: str = "inphared",
                   version: str = "1Oct2026") -> Path:
    upstream = root / "upstream.tsv"
    upstream.write_text(content, encoding="utf-8")
    directory = root / "snapshot"
    create_snapshot(directory, source=source, version=version,
                    source_uri="https://millardlab-inphared.s3.climb.ac.uk/1Oct2026_data.tsv",
                    from_file=upstream)
    return directory


class SnapshotTests(unittest.TestCase):
    def test_snapshot_records_identity_and_reloads(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = write_snapshot(Path(temporary))
            snapshot = load_snapshot(directory)
            self.assertEqual(snapshot.source, "inphared")
            self.assertEqual(snapshot.version, "1Oct2026")
            self.assertEqual(len(snapshot.sha256), 64)
            self.assertEqual(snapshot.bytes, len(FIXTURE.encode()))
            self.assertTrue(snapshot.path().is_file())

    def test_a_modified_snapshot_fails_verification(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = write_snapshot(Path(temporary))
            snapshot = load_snapshot(directory)
            snapshot.path().write_text(FIXTURE + "\t".join(["NC_999999.9"] + [""] * 9) + "\n")
            with self.assertRaisesRegex(SnapshotError, "checksum"):
                load_snapshot(directory)
            # Skipping verification is possible but never silent.
            self.assertEqual(load_snapshot(directory, verify=False).version, "1Oct2026")

    def test_snapshot_directory_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = write_snapshot(root)
            with self.assertRaisesRegex(SnapshotError, "already holds a snapshot"):
                create_snapshot(directory, source="inphared", version="1Nov2026",
                                source_uri="https://example.org/x.tsv",
                                from_file=root / "upstream.tsv")

    def test_download_requires_https_and_one_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "local.tsv").write_text(FIXTURE)
            with self.assertRaisesRegex(SnapshotError, "https"):
                create_snapshot(root / "a", source="inphared", version="v",
                                source_uri="http://example.org/x", url="http://example.org/x")
            with self.assertRaisesRegex(SnapshotError, "exactly one"):
                create_snapshot(root / "b", source="inphared", version="v",
                                source_uri="https://example.org/x",
                                url="https://example.org/x", from_file=root / "local.tsv")

    def test_broken_manifest_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = write_snapshot(Path(temporary))
            (directory / MANIFEST_NAME).write_text('{"source": "inphared"}')
            with self.assertRaises(SnapshotError):
                load_snapshot(directory)


class ProviderTests(unittest.TestCase):
    def provider(self, root: Path, **kwargs) -> InpharedProvider:
        return load_snapshot_dir(write_snapshot(root, **kwargs))

    def test_search_stamps_every_record_with_snapshot_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            provider = self.provider(Path(temporary))
            records = provider.search("Escherichia coli")
            self.assertEqual([record["id"] for record in records],
                             ["NC_000866.4", "NC_001895.1"])
            for record in records:
                self.assertEqual(record["source_db"], "inphared")
                self.assertEqual(record["snapshot_version"], "1Oct2026")
                self.assertEqual(len(record["snapshot_sha256"]), 64)
                self.assertTrue(record["source_uri"].startswith("https://"))
                self.assertEqual(record["host_annotation_source"], "depositor_metadata")

    def test_records_are_accepted_by_the_experiment_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            records = self.provider(Path(temporary)).search("Escherichia coli")
            devices = {"prepare-1": RealDeviceDouble("prepare-1", "prepare")}
            validate_experiment_inputs(records, devices, "real_hardware", require_snapshot=True)

    def test_provider_reports_no_infection_probability(self):
        with tempfile.TemporaryDirectory() as temporary:
            provider = self.provider(Path(temporary))
            records = provider.search("Escherichia coli")
            for record in records:
                for field in record:
                    self.assertNotIn("probab", field.lower())
                    self.assertNotIn("score", field.lower())
            self.assertIn("not an experimental", provider.describe()["notes"])

    def test_host_match_is_term_wise_and_case_insensitive(self):
        with tempfile.TemporaryDirectory() as temporary:
            provider = self.provider(Path(temporary))
            self.assertEqual(len(provider.search("escherichia")), 2)
            self.assertEqual(len(provider.search("PSEUDOMONAS aeruginosa")), 1)
            self.assertEqual(len(provider.search("coli Escherichia")), 2)

    def test_limit_is_respected(self):
        with tempfile.TemporaryDirectory() as temporary:
            provider = self.provider(Path(temporary))
            self.assertEqual(len(provider.search("Escherichia coli", limit=1)), 1)
            with self.assertRaises(ProviderError):
                provider.search("Escherichia coli", limit=0)

    def test_rows_without_an_accession_are_skipped(self):
        with tempfile.TemporaryDirectory() as temporary:
            records = self.provider(Path(temporary)).search("Escherichia coli")
            self.assertTrue(all(record["id"] for record in records))
            self.assertEqual(len(records), 2)

    def test_no_match_is_an_error_rather_than_an_empty_plan(self):
        with tempfile.TemporaryDirectory() as temporary:
            provider = self.provider(Path(temporary))
            with self.assertRaisesRegex(ProviderError, "No genome in snapshot"):
                provider.search("Klebsiella pneumoniae")

    def test_renamed_columns_still_resolve(self):
        renamed = FIXTURE.replace("Accession\t", "Genbank Accession\t").replace(
            "\tHost\n", "\tIsolation Host\n")
        with tempfile.TemporaryDirectory() as temporary:
            provider = self.provider(Path(temporary), content=renamed)
            self.assertEqual(len(provider.search("Escherichia coli")), 2)

    def test_a_missing_required_column_fails_with_the_headers_it_saw(self):
        without_host = "\n".join(
            "\t".join(line.split("\t")[:-1]) for line in FIXTURE.strip().splitlines()) + "\n"
        with tempfile.TemporaryDirectory() as temporary:
            provider = self.provider(Path(temporary), content=without_host)
            with self.assertRaises(ProviderError) as caught:
                provider.search("Escherichia coli")
            self.assertIn("host", str(caught.exception))
            self.assertIn("Headers present", str(caught.exception))

    def test_provider_refuses_a_snapshot_from_another_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = write_snapshot(Path(temporary), source="phagescope")
            with self.assertRaisesRegex(ProviderError, "No provider"):
                open_provider(load_snapshot(directory))


class SnapshotProvenanceTests(unittest.TestCase):
    """Snapshot fields are paired and checked, and can be made mandatory."""

    def setUp(self):
        self.devices = {"prepare-1": RealDeviceDouble("prepare-1", "prepare")}
        self.sourced = {"id": "NC_000866.4", "source_db": "inphared",
                        "accession": "NC_000866.4",
                        "retrieved_at": "2026-10-15T00:00:00+00:00",
                        "source_uri": "https://example.org/1Oct2026_data.tsv"}
        self.snapshotted = {**self.sourced, "snapshot_version": "1Oct2026",
                            "snapshot_sha256": "a" * 64}

    def check(self, candidate, **kwargs):
        validate_experiment_inputs([candidate], self.devices, "real_hardware", **kwargs)

    def test_a_record_without_a_snapshot_is_allowed_by_default(self):
        # A lab's own isolate has a legitimate source and no snapshot.
        self.check(self.sourced)

    def test_require_snapshot_rejects_a_record_without_one(self):
        with self.assertRaisesRegex(WorkflowError, "pinned snapshot"):
            self.check(self.sourced, require_snapshot=True)
        self.check(self.snapshotted, require_snapshot=True)

    def test_half_a_snapshot_reference_is_refused(self):
        for field in ("snapshot_version", "snapshot_sha256"):
            partial = {key: value for key, value in self.snapshotted.items() if key != field}
            with self.subTest(missing=field), self.assertRaisesRegex(WorkflowError, "both fields"):
                self.check(partial)

    def test_snapshot_sha256_must_look_like_a_digest(self):
        for value in ("not-a-digest", "A" * 64, "a" * 63, "a" * 65):
            with self.subTest(value=value), self.assertRaisesRegex(WorkflowError, "SHA-256"):
                self.check({**self.snapshotted, "snapshot_sha256": value})


class CliTests(unittest.TestCase):
    def run_cli(self, argv) -> int:
        from phage_lab.__main__ import main
        return main(argv)

    def test_snapshot_then_candidates_then_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            upstream = root / "upstream.tsv"
            upstream.write_text(FIXTURE, encoding="utf-8")
            snapshot_dir = root / "snap"
            self.assertEqual(0, self.run_cli([
                "fetch-snapshot", "--snapshot", str(snapshot_dir), "--source", "inphared",
                "--version", "1Oct2026", "--from-file", str(upstream),
                "--source-uri", "https://example.org/1Oct2026_data.tsv"]))

            out = root / "candidates.json"
            self.assertEqual(0, self.run_cli([
                "candidates", "--snapshot", str(snapshot_dir),
                "--host", "Escherichia coli", "--out", str(out)]))
            records = json.loads(out.read_text())
            self.assertEqual(len(records), 2)
            self.assertTrue(all(record["snapshot_version"] == "1Oct2026" for record in records))

            genome = root / "host.fasta"
            genome.write_text(">host\nACGTACGT\n")
            self.assertEqual(0, self.run_cli([
                "run", "--genome", str(genome), "--candidates", str(out),
                "--sample-id", "sample-001", "--execution-mode", "virtual_hardware",
                "--require-snapshot", "--output-dir", str(root / "runs"),
                "--timeout-seconds", "5", "--quiet"]))
            report = json.loads(next((root / "runs").glob("*/report.json")).read_text())
            self.assertEqual(report["status"], "succeeded")
            self.assertEqual(report["candidate_sources"], ["inphared"])
            self.assertEqual(len(report["candidate_snapshots"]), 1)
            self.assertIn("1Oct2026", report["candidate_snapshots"][0])

    def test_run_straight_from_a_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot_dir = write_snapshot(root)
            genome = root / "host.fasta"
            genome.write_text(">host\nACGTACGT\n")
            self.assertEqual(0, self.run_cli([
                "run", "--genome", str(genome), "--snapshot", str(snapshot_dir),
                "--host", "Escherichia coli", "--sample-id", "sample-002",
                "--execution-mode", "virtual_hardware", "--require-snapshot",
                "--output-dir", str(root / "runs"), "--timeout-seconds", "5", "--quiet"]))

    def test_run_rejects_both_or_neither_candidate_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot_dir = write_snapshot(root)
            for extra in ([], ["--candidates", str(root / "x.json"),
                               "--snapshot", str(snapshot_dir)]):
                with self.subTest(extra=extra), self.assertRaises(SystemExit):
                    self.run_cli(["run", "--sample-id", "s", "--execution-mode",
                                  "virtual_hardware", *extra])

    def test_run_from_snapshot_requires_a_host(self):
        with tempfile.TemporaryDirectory() as temporary:
            snapshot_dir = write_snapshot(Path(temporary))
            with self.assertRaises(SystemExit):
                self.run_cli(["run", "--snapshot", str(snapshot_dir), "--sample-id", "s",
                              "--execution-mode", "virtual_hardware"])


if __name__ == "__main__":
    unittest.main()

"""Content-addressed local FASTA registry tests; all fixtures are synthetic."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from phage_lab.sequence_registry import (
    create_sequence_registry,
    fingerprint_fasta,
    load_sequence_registry,
    resolve_registered_host_genome,
)


def write_json(path, document):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def make_registry(root, fasta_path, *, status="available", registry_path_value=None):
    root = Path(root)
    asset = fingerprint_fasta(fasta_path, kind="host_genome")
    relative = (
        registry_path_value
        if registry_path_value is not None
        else Path(fasta_path).resolve().relative_to(root.resolve()).as_posix()
    )
    registry_path = root / "sequence-registry.v1.json"
    write_json(registry_path, {
        "schema_version": 1,
        "registry_id": "synthetic-sequence-registry-v1",
        "entries": [{
            "kind": "host_genome",
            "sequence_sha256": asset.sequence_sha256,
            "file_sha256": asset.file_sha256,
            "path": relative,
            "status": status,
        }],
    })
    return asset, registry_path


class SequenceRegistryTests(unittest.TestCase):
    def test_create_registry_writes_a_valid_manifest_without_mutating_fasta(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fasta = root / "host.fna"
            raw = b">contig1\\nACGT\\n"
            fasta.write_bytes(raw)
            result = create_sequence_registry(
                fasta,
                root / "sequence-registry.v1.json",
                registry_id="host-fixture-registry-v1",
            )
            loaded = load_sequence_registry(result["path"])
            self.assertEqual(loaded.registry_id, "host-fixture-registry-v1")
            self.assertEqual(result["asset"].file_sha256, hashlib.sha256(raw).hexdigest())
            self.assertEqual(fasta.read_bytes(), raw)
            self.assertEqual(len(loaded.entries), 1)

    def test_create_registry_refuses_to_overwrite_existing_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fasta = root / "host.fna"
            fasta.write_text(">contig1\\nACGT\\n", encoding="utf-8")
            manifest = root / "sequence-registry.v1.json"
            manifest.write_text("preserve me", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
                create_sequence_registry(
                    fasta, manifest, registry_id="host-fixture-registry-v1"
                )
            self.assertEqual(manifest.read_text(encoding="utf-8"), "preserve me")

    def test_fingerprint_separates_raw_file_and_normalized_sequence_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            fasta = Path(directory) / "host.fna"
            raw = b">contig1 description\nacgt\n"
            fasta.write_bytes(raw)
            asset = fingerprint_fasta(fasta, kind="host_genome")
            self.assertEqual(asset.file_sha256, hashlib.sha256(raw).hexdigest())
            self.assertEqual(asset.sequence_sha256, hashlib.sha256(b"\0ACGT").hexdigest())
            self.assertEqual(asset.bases, 4)
            self.assertEqual(asset.contigs, 1)

    def test_resolves_exact_host_genome_and_registry_lineage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fasta = root / "sequences" / "host.fna"
            fasta.parent.mkdir()
            fasta.write_text(">contig1\nACGTACGT\n", encoding="utf-8")
            asset, registry_path = make_registry(root, fasta)
            resolved = resolve_registered_host_genome(registry_path, asset.sequence_sha256)
            self.assertEqual(resolved.sequence_registry_id, "synthetic-sequence-registry-v1")
            self.assertEqual(resolved.asset.file_sha256, asset.file_sha256)
            self.assertEqual(resolved.asset.sequence_sha256, asset.sequence_sha256)
            self.assertEqual(resolved.asset.bases, 8)

    def test_header_wrapping_case_and_line_endings_do_not_change_normalized_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.fna"
            second = root / "second.fna"
            first.write_bytes(b">contig1 description\nacgtacgt\n")
            second.write_bytes(b">renamed\r\nACGT\r\nACGT\r\n")
            self.assertEqual(
                fingerprint_fasta(first, kind="host_genome").sequence_sha256,
                fingerprint_fasta(second, kind="host_genome").sequence_sha256,
            )
            self.assertNotEqual(
                fingerprint_fasta(first, kind="host_genome").file_sha256,
                fingerprint_fasta(second, kind="host_genome").file_sha256,
            )

    def test_raw_file_tampering_is_rejected_even_when_normalized_sequence_is_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fasta = root / "host.fna"
            fasta.write_text(">contig1\nACGT\n", encoding="utf-8")
            asset, registry_path = make_registry(root, fasta)
            fasta.write_text(">different header\nACGT\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "file SHA-256 mismatch"):
                resolve_registered_host_genome(registry_path, asset.sequence_sha256)

    def test_unregistered_sequence_fingerprint_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fasta = root / "host.fna"
            fasta.write_text(">contig1\nACGT\n", encoding="utf-8")
            asset, registry_path = make_registry(root, fasta)
            with self.assertRaisesRegex(ValueError, "no registered host_genome sequence"):
                resolve_registered_host_genome(registry_path, "a" * 64)

    def test_withdrawn_sequence_is_not_resolved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fasta = root / "host.fna"
            fasta.write_text(">contig1\nACGT\n", encoding="utf-8")
            asset, registry_path = make_registry(root, fasta, status="withdrawn")
            with self.assertRaisesRegex(ValueError, "not available"):
                resolve_registered_host_genome(registry_path, asset.sequence_sha256)

    def test_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fasta = root / "host.fna"
            fasta.write_text(">contig1\nACGT\n", encoding="utf-8")
            _, registry_path = make_registry(root, fasta, registry_path_value="../host.fna")
            with self.assertRaisesRegex(ValueError, "must not contain"):
                load_sequence_registry(registry_path)

    def test_invalid_fasta_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            fasta = Path(directory) / "host.fna"
            fasta.write_text(">contig1\nACGTZ\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid DNA characters"):
                fingerprint_fasta(fasta, kind="host_genome")


if __name__ == "__main__":
    unittest.main()

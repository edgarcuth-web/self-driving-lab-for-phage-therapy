"""Shared primitive validators and record mechanics used by domain modules."""

from dataclasses import dataclass
import math
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from phage_lab.artifacts import (
    ContentAddressed,
    atomic_write_json,
    content_hash,
    is_sha256,
    require_text_tuple,
    validate_scalar,
    validate_scalar_mapping,
)
from phage_lab.experiment_spec import arm_by_id
from phage_lab.records import RunRecords
from phage_lab.interaction_evidence import HostReference
from phage_lab.phenotype import PhenotypeAssessor


class Sha256Tests(unittest.TestCase):
    def test_only_lowercase_64_hex_strings_are_digests(self):
        self.assertTrue(is_sha256("a" * 64))
        for value in ("A" * 64, "a" * 63, "a" * 64 + "\n", "g" * 64, None, 1):
            with self.subTest(value=value):
                self.assertFalse(is_sha256(value))


class RequireTextTupleTests(unittest.TestCase):
    def test_accepts_unique_nonempty_text_and_optional_empty(self):
        require_text_tuple(("a", "b"), "ids")
        require_text_tuple((), "ids")

    def test_rejects_wrong_container_blank_duplicate_and_required_empty(self):
        for values, kwargs, message in (
            (["a"], {}, "ids must be a tuple"),
            (("a", " "), {}, "ids must be a nonempty string"),
            (("a", "a"), {}, "ids values must be unique"),
            ((), {"nonempty": True}, "ids must not be empty"),
        ):
            with self.subTest(values=values), self.assertRaisesRegex(ValueError, message):
                require_text_tuple(values, "ids", **kwargs)


class ScalarTests(unittest.TestCase):
    def test_default_accepts_finite_json_scalars_and_null(self):
        for value in ("x", 0, 1.5, True, None):
            validate_scalar(value, "v")

    def test_rejects_non_finite_and_containers(self):
        for value in (math.nan, math.inf, [1], {"a": 1}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_scalar(value, "v")

    def test_null_and_bool_can_be_disallowed_explicitly(self):
        with self.assertRaisesRegex(ValueError, "omit unknown values"):
            validate_scalar(None, "v", allow_none=False)
        with self.assertRaisesRegex(ValueError, "must not be a boolean"):
            validate_scalar(True, "v", allow_bool=False)

    def test_mapping_requires_text_keys_and_scalar_values(self):
        validate_scalar_mapping({"a": 1, "b": None, "c": False}, "m")
        for value, kwargs in (
            ([], {}),
            ({"": 1}, {}),
            ({"a": math.nan}, {}),
            ({"a": [1]}, {}),
            ({"a": True}, {"allow_bool": False}),
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_scalar_mapping(value, "m", **kwargs)


@dataclass(frozen=True)
class _Record(ContentAddressed):
    name: str

    def _content_dict(self):
        return {"name": self.name}


class ContentAddressedTests(unittest.TestCase):
    def test_hash_covers_content_and_is_exported_first(self):
        record = _Record("x")
        self.assertEqual(record.content_sha256, content_hash({"name": "x"}))
        self.assertEqual(record.to_dict(), {"content_sha256": record.content_sha256, "name": "x"})
        self.assertEqual(list(record.to_dict()), ["content_sha256", "name"])


class AtomicWriteJsonTests(unittest.TestCase):
    def test_output_format_and_umask_permissions_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "record.json"
            atomic_write_json({"b": "\u00e9", "a": [1]}, path)
            self.assertEqual(path.read_bytes(), '{\n  "b": "\u00e9",\n  "a": [\n    1\n  ]\n}\n'.encode())
            umask = os.umask(0)
            os.umask(umask)
            if os.name == "posix":
                self.assertEqual(path.stat().st_mode & 0o777, 0o666 & ~umask)
            self.assertEqual(os.listdir(path.parent), ["record.json"])

    def test_failed_replace_keeps_original_and_leaves_no_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "record.json"
            atomic_write_json({"version": 1}, path)
            with mock.patch.object(Path, "replace", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    atomic_write_json({"version": 2}, path)
            self.assertEqual(os.listdir(directory), ["record.json"])
            self.assertIn('"version": 1', path.read_text())

    def test_stale_fixed_temporary_name_does_not_block_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "record.json"
            (Path(directory) / "record.json.tmp").mkdir()
            atomic_write_json({"ok": True}, path)
            self.assertIn('"ok": true', path.read_text())

    def test_data_is_flushed_to_disk_before_replace(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch("phage_lab.artifacts.os.fsync", wraps=os.fsync) as fsync:
                atomic_write_json({"ok": True}, Path(directory) / "record.json")
            fsync.assert_called()


class RunReportWriteTests(unittest.TestCase):
    def test_final_reports_ignore_stale_fixed_temporary_names(self):
        with tempfile.TemporaryDirectory() as directory:
            records = RunRecords(Path(directory), echo=False)
            self.addCleanup(records.close)
            for name in ("report.json.tmp", "report.md.tmp"):
                (records.directory / name).mkdir()
            with mock.patch("phage_lab.records.render_report", return_value="# report\n"):
                records.finish({"status": "succeeded"})
            self.assertEqual(
                sorted(p.name for p in records.directory.iterdir() if p.is_file()),
                ["events.jsonl", "report.json", "report.md"],
            )


class SharedFromDictTests(unittest.TestCase):
    def test_host_reference_round_trip_and_unknown_fields(self):
        data = {"genome_sha256": "a" * 64, "profile_id": "host-1"}
        self.assertEqual(HostReference.from_dict(data), HostReference("a" * 64, "host-1"))
        for data in ([], {"genome_sha256": "a" * 64, "extra": 1}, {"profile_id": "host-1"}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                HostReference.from_dict(data)

    def test_assessor_requires_exact_fields(self):
        data = {"name": "rule", "version": "1", "parameters": {}}
        self.assertEqual(PhenotypeAssessor.from_dict(data), PhenotypeAssessor("rule", "1", {}))
        with self.assertRaisesRegex(ValueError, "assessor has missing or unknown fields"):
            PhenotypeAssessor.from_dict({"name": "rule"})

    def test_arm_by_id_finds_the_arm_or_fails(self):
        arm = SimpleNamespace(arm_id="treatment")
        spec = SimpleNamespace(arms=(SimpleNamespace(arm_id="control"), arm))
        self.assertIs(arm_by_id(spec, "treatment"), arm)
        with self.assertRaisesRegex(ValueError, "no arm 'missing'"):
            arm_by_id(spec, "missing")


if __name__ == "__main__":
    unittest.main()

"""CLI boundaries: scoped options, entry compatibility and usable local defaults."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from phage_lab.__main__ import main
from support import CANDIDATES


class CliBoundaryTests(unittest.TestCase):
    def test_unrelated_or_abbreviated_options_are_rejected(self):
        for argv in (["version", "--qc-status", "invalid"],
                     ["host-profile", "--decision-id", "ignored"],
                     ["run", "--execution-m", "virtual_hardware"]):
            with self.subTest(argv=argv), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    main(argv)
                self.assertEqual(raised.exception.code, 2)

    def test_subcommand_help_only_lists_its_own_options(self):
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            main(["measurement", "--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--qc-status", output.getvalue())
        self.assertNotIn("--decision-id", output.getvalue())
        self.assertNotIn("--phist", output.getvalue())

    def test_top_level_help_lists_commands(self):
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("host-profile", output.getvalue())
        self.assertNotIn("--qc-status", output.getvalue())

    def test_default_genome_still_supports_a_local_profile_check(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(main(["host-profile", "--sample-id", "local-check",
                                       "--out", str(path)]), 0)
            profile = json.loads(path.read_text())
            self.assertEqual(profile["host_id"], "local-check")

    def test_flag_only_legacy_run_remains_usable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "candidates.json"
            path.write_text(json.dumps(CANDIDATES))
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(main([
                    "--candidates", str(path), "--sample-id", "compatibility-check",
                    "--execution-mode", "virtual_hardware", "--output-dir", str(root / "runs"),
                    "--quiet",
                ]), 0)
            report = json.loads(next((root / "runs").glob("*/report.json")).read_text())
            self.assertEqual(report["status"], "succeeded")
            self.assertFalse(report["physical_execution"])
            self.assertFalse(report["scientific_membership_locked"])

import tempfile
from pathlib import Path
import unittest

from phage_lab.workflow import (
    CANDIDATE_PROVENANCE_FIELDS,
    WorkflowError,
    run_experiment,
    validate_experiment_inputs,
    validate_plan,
)

from support import CANDIDATES, WORKFLOW, RealDeviceDouble as RealDevice


class StaticAgent:
    name = "static-test-agent"

    async def plan(self, context):
        assignments = {}
        for operation in context["workflow"]:
            assignments[operation] = next(
                device["device_id"] for device in context["devices"]
                if operation in device["operations"])
        return {"candidate_ids": [item["id"] for item in context["candidates"][:2]],
                "device_assignments": assignments,
                "reason": "Use only the explicitly supplied candidate records and available devices."}

    async def recover(self, context):
        return {"action": "abort", "replacement_device_id": None,
                "reason": "The test backend does not exercise recovery."}


def genome_at(root: Path) -> Path:
    path = root / "host.fasta"
    path.write_text(">host\nACGTACGT\n")
    return path


class ExperimentRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_hardware_run_uses_only_supplied_candidates_and_devices(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            devices = {"prepare-1": RealDevice("prepare-1", "prepare"),
                       "measure-1": RealDevice("measure-1", "measure")}
            report, directory = await run_experiment(
                genome_at(root), root / "runs", sample_id="sample-001",
                candidates=CANDIDATES, devices=devices,
                workflow={"prepare": (), "measure": ("prepare",)},
                agent=StaticAgent(), execution_mode="real_hardware",
                timeout_seconds=1, echo=False)
            self.assertEqual(report["status"], "succeeded")
            self.assertTrue(report["physical_execution"])
            self.assertEqual(report["execution_mode"], "real_hardware")
            self.assertEqual(list(report["results"]), ["prepare", "measure"])
            self.assertEqual(report["candidate_sources"], ["RefSeq"])
            self.assertNotIn("虚拟硬件运行报告", (directory / "report.md").read_text())

    async def test_virtual_hardware_run_can_create_twins_for_real_candidate_ids(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report, directory = await run_experiment(
                genome_at(root), root / "runs", sample_id="sample-virtual-001",
                candidates=CANDIDATES, devices=None, workflow=WORKFLOW,
                agent=StaticAgent(), execution_mode="virtual_hardware",
                timeout_seconds=1, echo=False)
            self.assertEqual(report["status"], "succeeded")
            self.assertFalse(report["physical_execution"])
            self.assertEqual(report["execution_mode"], "virtual_hardware")
            self.assertTrue(report["results"]["measure"]["simulated"])
            self.assertEqual(report["results"]["measure"]["evidence"], "none")
            self.assertEqual(report["evaluation"]["quality"], "virtual_readout_complete")
            rendered = (directory / "report.md").read_text()
            self.assertIn("虚拟硬件运行报告", rendered)
            self.assertIn("没有执行物理湿实验", rendered)

    async def test_execution_mode_has_no_default(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(TypeError):
                await run_experiment(
                    genome_at(root), root / "runs", sample_id="sample-001",
                    candidates=CANDIDATES, devices=None, workflow=WORKFLOW,
                    agent=StaticAgent(), echo=False)

    async def test_virtual_hardware_is_never_an_implicit_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(WorkflowError):
                await run_experiment(
                    genome_at(root), root / "runs", sample_id="sample-001",
                    candidates=CANDIDATES, devices=None, workflow=WORKFLOW,
                    agent=StaticAgent(), execution_mode="real_hardware", echo=False)

    async def test_execution_mode_must_match_device_kind(self):
        real = {"prepare-1": RealDevice("prepare-1", "prepare")}
        validate_experiment_inputs(CANDIDATES, real, "real_hardware")
        with self.assertRaises(WorkflowError):
            validate_experiment_inputs(CANDIDATES, real, "virtual_hardware")

        virtual = RealDevice("prepare-1", "prepare")
        original = virtual.describe
        virtual.describe = lambda: {**original(), "simulated": True}
        validate_experiment_inputs(CANDIDATES, {"prepare-1": virtual}, "virtual_hardware")
        with self.assertRaises(WorkflowError):
            validate_experiment_inputs(CANDIDATES, {"prepare-1": virtual}, "real_hardware")


class CandidateProvenanceTests(unittest.IsolatedAsyncioTestCase):
    """Candidates are admitted by positive provenance, not by failing a name check."""

    def setUp(self):
        self.devices = {"prepare-1": RealDevice("prepare-1", "prepare")}

    def test_every_provenance_field_is_required(self):
        for field in CANDIDATE_PROVENANCE_FIELDS:
            incomplete = {key: value for key, value in CANDIDATES[0].items() if key != field}
            with self.subTest(missing=field), self.assertRaises(WorkflowError) as caught:
                validate_experiment_inputs([incomplete], self.devices, "real_hardware")
            self.assertIn(field, str(caught.exception))

    def test_blank_or_non_string_provenance_is_rejected(self):
        for value in ("", "   ", None, 42, {"db": "RefSeq"}):
            with self.subTest(value=value), self.assertRaises(WorkflowError):
                validate_experiment_inputs([{**CANDIDATES[0], "source_db": value}],
                                           self.devices, "real_hardware")

    def test_retrieved_at_must_be_a_real_timestamp(self):
        with self.assertRaises(WorkflowError):
            validate_experiment_inputs([{**CANDIDATES[0], "retrieved_at": "last tuesday"}],
                                       self.devices, "real_hardware")

    def test_renaming_a_fixture_does_not_get_it_past_validation(self):
        # The old denylist admitted anything that avoided the SIM- prefix and the
        # synthetic_fixture label. A record with no source cannot pass now.
        for fixture in ({"id": "PHAGE-A"},
                        {"id": "PHAGE-A", "source": "registry"},
                        {"id": "PHAGE-A", "source_db": "RefSeq"}):
            with self.subTest(fixture=fixture), self.assertRaises(WorkflowError):
                validate_experiment_inputs([fixture], self.devices, "real_hardware")

    def test_explicitly_simulated_candidates_are_still_refused(self):
        with self.assertRaises(WorkflowError):
            validate_experiment_inputs([{**CANDIDATES[0], "simulated": True}],
                                       self.devices, "real_hardware")

    def test_duplicate_candidate_ids_are_refused(self):
        with self.assertRaises(WorkflowError):
            validate_experiment_inputs([CANDIDATES[0], CANDIDATES[0]],
                                       self.devices, "real_hardware")

    def test_a_well_sourced_candidate_is_accepted(self):
        validate_experiment_inputs([CANDIDATES[0]], self.devices, "real_hardware")


class SelectionSizeTests(unittest.TestCase):
    """A single phage and a large cocktail are both legitimate experiments."""

    def setUp(self):
        self.devices = {"prepare-1": RealDevice("prepare-1", "prepare")}

    def plan(self, ids):
        return {"candidate_ids": list(ids), "device_assignments": {"prepare": "prepare-1"},
                "reason": "test plan"}

    def test_single_candidate_is_allowed_by_default(self):
        validate_plan(self.plan([CANDIDATES[0]["id"]]), CANDIDATES, self.devices,
                      operations=("prepare",))

    def test_selection_size_bounds_are_enforced(self):
        ids = [item["id"] for item in CANDIDATES]
        validate_plan(self.plan(ids), CANDIDATES, self.devices,
                      operations=("prepare",), selection_size=(3, 6))
        with self.assertRaises(WorkflowError):
            validate_plan(self.plan(ids[:1]), CANDIDATES, self.devices,
                          operations=("prepare",), selection_size=(2, 6))
        with self.assertRaises(WorkflowError):
            validate_plan(self.plan(ids), CANDIDATES, self.devices,
                          operations=("prepare",), selection_size=(1, 2))

    def test_duplicate_or_unoffered_ids_are_refused(self):
        for ids in ([CANDIDATES[0]["id"], CANDIDATES[0]["id"]], ["not-offered"]):
            with self.subTest(ids=ids), self.assertRaises(WorkflowError):
                validate_plan(self.plan(ids), CANDIDATES, self.devices, operations=("prepare",))


if __name__ == "__main__":
    unittest.main()

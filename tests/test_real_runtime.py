import tempfile
from pathlib import Path
import unittest

from phage_lab.workflow import (
    WorkflowError,
    run_experiment,
    validate_experiment_inputs,
    validate_real_inputs,
)


class RealDevice:
    def __init__(self, device_id, operation):
        self.device_id = device_id
        self.operation = operation
        self.jobs = {}

    def describe(self):
        return {"device_id": self.device_id, "operations": [self.operation],
                "simulated": False, "state": "available"}

    async def read(self, job_id=None):
        if job_id is None:
            return {**self.describe(), "busy": False}
        return {"device_id": self.device_id, "job_id": job_id,
                "state": "succeeded", "result": self.jobs[job_id]}

    async def write(self, command):
        job_id = f"{self.device_id}:{command.command_id}"
        self.jobs[job_id] = {"sample_id": command.payload["sample_id"],
                             "operation": command.operation, "source": "test-double"}
        return job_id

    async def wait(self, job_id):
        return self.jobs[job_id]

    async def cancel(self, job_id):
        return False

    async def close(self):
        pass


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


CANDIDATES = [
    {"id": "PHAGE-A", "source": "registry"},
    {"id": "PHAGE-B", "source": "registry"},
]


class ExperimentRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_hardware_run_uses_only_supplied_candidates_and_devices(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            genome = root / "host.fasta"
            genome.write_text(">host\nACGTACGT\n")
            devices = {"prepare-1": RealDevice("prepare-1", "prepare"),
                       "measure-1": RealDevice("measure-1", "measure")}
            report, directory = await run_experiment(
                genome, root / "runs", sample_id="sample-001",
                candidates=CANDIDATES, devices=devices,
                workflow={"prepare": (), "measure": ("prepare",)},
                agent=StaticAgent(), execution_mode="real_hardware",
                timeout_seconds=1, echo=False)
            self.assertEqual(report["status"], "succeeded")
            self.assertTrue(report["physical_execution"])
            self.assertEqual(report["execution_mode"], "real_hardware")
            self.assertEqual(list(report["results"]), ["prepare", "measure"])
            self.assertNotIn("虚拟硬件运行报告", (directory / "report.md").read_text())

    async def test_virtual_hardware_run_can_create_twins_for_real_candidate_ids(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            genome = root / "host.fasta"
            genome.write_text(">host\nACGTACGT\n")
            report, directory = await run_experiment(
                genome, root / "runs", sample_id="sample-virtual-001",
                candidates=CANDIDATES, devices=None,
                workflow={"prepare": (), "measure": ("prepare",)},
                agent=StaticAgent(), execution_mode="virtual_hardware",
                timeout_seconds=1, echo=False)
            self.assertEqual(report["status"], "succeeded")
            self.assertFalse(report["physical_execution"])
            self.assertEqual(report["execution_mode"], "virtual_hardware")
            self.assertTrue(report["results"]["measure"]["simulated"])
            self.assertEqual(report["results"]["measure"]["evidence"], "none")
            rendered = (directory / "report.md").read_text()
            self.assertIn("虚拟硬件运行报告", rendered)
            self.assertIn("没有执行物理湿实验", rendered)

    async def test_candidate_fixtures_stay_out_of_both_experiment_modes(self):
        real = {"prepare-1": RealDevice("prepare-1", "prepare")}
        for candidate in (
            {"id": "SIM-PHAGE-A", "source": "registry"},
            {"id": "PHAGE-A", "source": "synthetic_fixture"},
            {"id": "PHAGE-A", "source": "registry", "simulated": True},
        ):
            with self.subTest(candidate=candidate), self.assertRaises(WorkflowError):
                validate_real_inputs([candidate], real)

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


if __name__ == "__main__":
    unittest.main()

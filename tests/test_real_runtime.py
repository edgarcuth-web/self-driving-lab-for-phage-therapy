import tempfile
from pathlib import Path
import unittest

from phage_lab.workflow import WorkflowError, run_experiment, validate_real_inputs


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
                "reason": "Use the explicitly supplied test records and drivers."}

    async def recover(self, context):
        return {"action": "abort", "replacement_device_id": None,
                "reason": "The test backend does not exercise recovery."}


class RealRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_run_uses_only_supplied_candidates_and_devices(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            genome = root / "host.fasta"
            genome.write_text(">host\nACGTACGT\n")
            devices = {"prepare-1": RealDevice("prepare-1", "prepare"),
                       "measure-1": RealDevice("measure-1", "measure")}
            report, directory = await run_experiment(
                genome, root / "runs", sample_id="sample-001",
                candidates=[{"id": "PHAGE-A", "source": "registry"},
                            {"id": "PHAGE-B", "source": "registry"}],
                devices=devices, workflow={"prepare": (), "measure": ("prepare",)},
                agent=StaticAgent(), timeout_seconds=1, echo=False)
            self.assertEqual(report["status"], "succeeded")
            self.assertFalse(report["simulated"])
            self.assertEqual(list(report["results"]), ["prepare", "measure"])
            self.assertNotIn("fault", report)
            self.assertNotIn("simulation/test harness", (directory / "report.md").read_text().lower())

    async def test_real_run_rejects_simulation_markers_before_creating_a_run(self):
        real = {"prepare-1": RealDevice("prepare-1", "prepare")}
        with self.assertRaises(WorkflowError):
            validate_real_inputs([{"id": "SIM-PHAGE-A", "source": "registry"}], real)
        with self.assertRaises(WorkflowError):
            validate_real_inputs([{"id": "PHAGE-A", "source": "synthetic_fixture"}], real)

        fake = RealDevice("prepare-1", "prepare")
        original = fake.describe
        fake.describe = lambda: {**original(), "simulated": True}
        with self.assertRaises(WorkflowError):
            validate_real_inputs([{"id": "PHAGE-A", "source": "registry"}], {"prepare-1": fake})


if __name__ == "__main__":
    unittest.main()

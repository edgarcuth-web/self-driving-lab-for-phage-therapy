"""Test doubles.

Fault injection lives here rather than in ``phage_lab`` so that production code
carries no notion of deliberately breaking itself, while the reconciliation and
failover invariants in :class:`phage_lab.workflow.Scheduler` stay covered.
"""

import random

from phage_lab.virtual_hardware import VirtualDevice, make_virtual_devices

FAULT_MODES = ("none", "hang", "response-lost", "unreachable", "random")

CANDIDATES = [
    {"id": "NC_000866.4", "source_db": "RefSeq", "accession": "NC_000866.4",
     "retrieved_at": "2026-10-15T00:00:00+00:00",
     "source_uri": "https://www.ncbi.nlm.nih.gov/nuccore/NC_000866.4"},
    {"id": "NC_001895.1", "source_db": "RefSeq", "accession": "NC_001895.1",
     "retrieved_at": "2026-10-15T00:00:00+00:00",
     "source_uri": "https://www.ncbi.nlm.nih.gov/nuccore/NC_001895.1"},
    {"id": "NC_004166.2", "source_db": "RefSeq", "accession": "NC_004166.2",
     "retrieved_at": "2026-10-15T00:00:00+00:00",
     "source_uri": "https://www.ncbi.nlm.nih.gov/nuccore/NC_004166.2"},
]

WORKFLOW = {"prepare": (), "infect": ("prepare",), "measure": ("infect",)}


class FaultInjector:
    """Inject at most one fault into a fleet of virtual devices."""

    def __init__(self, seed: int, mode: str, step: str | None = None,
                 operations: tuple[str, ...] = tuple(WORKFLOW)):
        if mode not in FAULT_MODES or (step is not None and step not in operations):
            raise ValueError("Unknown fault mode or step.")
        rng = random.Random(f"fault:{seed}")
        self.step = step or rng.choice(operations)
        self.mode = rng.choice(FAULT_MODES[1:4]) if mode == "random" else mode
        self.injected = False

    def take(self, operation: str) -> str:
        if operation == self.step and self.mode != "none" and not self.injected:
            self.injected = True
            return self.mode
        return "none"


class AlwaysHang:
    """Every job hangs, so retry and attempt limits can be exercised."""

    def take(self, operation: str) -> str:
        return "hang"


def make_test_fleet(emit, injector=None, *, operations=tuple(WORKFLOW), seed: int = 1,
                    time_scale: float = 0.01, replicas: int = 2) -> dict[str, VirtualDevice]:
    """Virtual devices with a compatible peer per operation, so failover has somewhere to go."""
    return make_virtual_devices(operations, emit, replicas=replicas, seed=seed,
                                time_scale=time_scale, injector=injector)


class RealDeviceDouble:
    """A driver that declares itself non-simulated, for real_hardware paths.

    It declares a safe state like any real driver must; pass
    ``safe_state=None`` to model a driver that refuses to declare one, or
    ``safe_state_entered=False`` to model hardware that cannot confirm it.
    """

    def __init__(self, device_id, operation, *, safe_state="default",
                 safe_state_entered=True):
        self.device_id = device_id
        self.operation = operation
        self.jobs = {}
        self.safe_state_requests = []
        self.safe_state_entered = safe_state_entered
        if safe_state == "default":
            safe_state = {"policy": "park_and_release", "retains_hazard": False,
                          "description": "Test double: parks axes and ejects the tip to waste."}
        self.safe_state = safe_state

    def describe(self):
        manifest = {"device_id": self.device_id, "operations": [self.operation],
                    "simulated": False, "state": "available"}
        if self.safe_state is not None:
            manifest["safe_state"] = self.safe_state
        return manifest

    async def enter_safe_state(self, reason):
        self.safe_state_requests.append(reason)
        policy = (self.safe_state or {}).get("policy", "park_and_release")
        retains = (self.safe_state or {}).get("retains_hazard", False)
        return {"entered": self.safe_state_entered, "policy": policy,
                "retains_hazard": retains,
                "detail": ("Test double confirmed its safe state." if self.safe_state_entered
                           else "Test double could not confirm its safe state.")}

    async def read(self, job_id=None):
        if job_id is None:
            return {**self.describe(), "busy": False}
        return {"device_id": self.device_id, "job_id": job_id,
                "state": "succeeded", "result": self.jobs[job_id]}

    async def write(self, command):
        job_id = f"{self.device_id}:{command.command_id}"
        result = {"sample_id": command.payload["sample_id"],
                  "operation": command.operation, "source": "test-double"}
        arms = command.payload.get("experiment_arms")
        if arms:
            result["arms"] = {}
            for index, arm in enumerate(arms, start=1):
                arm_result = {
                    "arm_id": arm["arm_id"],
                    "operation": command.operation,
                    "source": "test-double",
                }
                if command.operation == "measure":
                    arm_result["signal"] = [float(index), float(index) + 0.5]
                    arm_result["unit"] = "instrument_units"
                result["arms"][arm["arm_id"]] = arm_result
        self.jobs[job_id] = result
        return job_id

    async def wait(self, job_id):
        return self.jobs[job_id]

    async def cancel(self, job_id):
        return False

    async def close(self):
        pass

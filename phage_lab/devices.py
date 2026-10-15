"""Device contracts shared by real instrument drivers and test doubles."""

from dataclasses import dataclass
from typing import Protocol

INTERFACE = "phage-lab-device-v1"


class DeviceError(RuntimeError):
    pass


class DeviceUnavailable(DeviceError):
    pass


@dataclass(frozen=True)
class Command:
    command_id: str
    operation: str
    payload: dict
    attempt: int = 1


class DeviceDriver(Protocol):
    """Contract implemented by concrete instrument adapters.

    Drivers must report whether they are simulated. Real execution refuses a
    driver unless ``describe()["simulated"] is False``.
    """

    def describe(self) -> dict: ...
    async def read(self, job_id: str | None = None) -> dict: ...
    async def write(self, command: Command) -> str: ...
    async def wait(self, job_id: str) -> dict: ...
    async def cancel(self, job_id: str) -> bool: ...
    async def close(self) -> None: ...


# Temporary compatibility bridge for the original hackathon tests and dashboard.
# Simulation code itself lives in phage_lab.simulation and is never selected by
# the real execution entry point.
def __getattr__(name: str):
    if name in {"FAULT_MODES", "OPERATIONS", "FaultInjector", "SimulatedDevice", "make_devices"}:
        from . import simulation
        return getattr(simulation, name)
    raise AttributeError(name)

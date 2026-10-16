"""Device contracts shared by real instrument drivers and test doubles.

Two things make this contract unusual, and both exist because the point of the
system is to run hazardous wet-lab steps without a person in the room.

A timeout is not a failure. It means the controller does not know what the
instrument did. Every method below is specified so that an unknown outcome can
be told apart from a known one, because the difference decides whether it is
safe to repeat a physical action.

Stopping the software is not the same as the apparatus being safe. A run that
halts mid-step can leave a tip full of toxic liquid, a gripper holding an open
plate, or a heater on. So a driver must declare, up front, what its hardware
does when a step is abandoned, and the controller asks it to get there and
records whether it confirmed. See `SAFE_STATE_POLICIES` and
`validate_safe_state`.
"""

from dataclasses import dataclass
from typing import Protocol

INTERFACE = "phage-lab-device-v1"

# What an instrument does when the controller abandons a step. This is a
# property of the hardware, not a preference: a driver states which one it is
# and the controller plans around it.
#
#   park_and_release  The device can reach a defined safe state on its own:
#                     contents dispensed or returned to a sealed vessel, tip
#                     ejected to waste, axes parked clear. No person needed.
#   contained_hold    The device freezes where it is and keeps holding whatever
#                     it holds. That is safe only because an enclosure contains
#                     it. A person entering the enclosure meets the hazard.
#   operator_required The device cannot make itself safe. A person must
#                     intervene, wearing whatever the reagent demands.
SAFE_STATE_POLICIES = ("park_and_release", "contained_hold", "operator_required")

# Policies under which an abandoned step leaves hazardous material held by the
# apparatus rather than disposed of or sealed.
HAZARD_RETAINING_POLICIES = ("contained_hold", "operator_required")


class DeviceError(RuntimeError):
    pass


class DeviceUnavailable(DeviceError):
    """The device could not be reached, so its job outcome is unknown.

    This is distinct from a failure: a failure is an observed outcome, while
    this means nothing was observed. The controller must not repeat an
    irreversible action on this basis.
    """


class SafeStateError(DeviceError):
    """The device could not confirm that it reached its declared safe state."""




REQUIRED_EXECUTION_PAYLOAD_FIELDS = {"sample_id", "candidate_ids"}
SPEC_LINEAGE_PAYLOAD_FIELDS = {
    "experiment_spec_id",
    "experiment_spec_sha256",
    "phage_profile_ids",
    "experiment_arms",
}
OPTIONAL_SOURCE_LINEAGE_PAYLOAD_FIELDS = {"cocktail_design_id"}
MATERIAL_LINEAGE_PAYLOAD_FIELDS = {"material_batch_ids"}
ALLOWED_EXECUTION_PAYLOAD_FIELDS = (
    REQUIRED_EXECUTION_PAYLOAD_FIELDS
    | SPEC_LINEAGE_PAYLOAD_FIELDS
    | OPTIONAL_SOURCE_LINEAGE_PAYLOAD_FIELDS
    | MATERIAL_LINEAGE_PAYLOAD_FIELDS
)


def validate_execution_payload(payload: dict) -> dict:
    """Validate the controller-to-device execution payload.

    Legacy runs carry only sample_id and candidate_ids. ExperimentSpec-bound
    runs add the complete lineage block. Unknown fields and partial lineage are
    rejected so scientific membership cannot be smuggled through driver data.
    """

    if not isinstance(payload, dict):
        raise DeviceError("Command payload must be an object.")
    missing = REQUIRED_EXECUTION_PAYLOAD_FIELDS - set(payload)
    unknown = set(payload) - ALLOWED_EXECUTION_PAYLOAD_FIELDS
    if missing:
        raise DeviceError(
            "Command payload is missing required field(s): "
            + ", ".join(sorted(missing))
            + "."
        )
    if unknown:
        raise DeviceError(
            "Command payload contains unknown field(s): "
            + ", ".join(sorted(unknown))
            + "."
        )

    sample_id = payload["sample_id"]
    candidate_ids = payload["candidate_ids"]
    if not isinstance(sample_id, str) or not sample_id.strip():
        raise DeviceError("Command payload sample_id must be a nonempty string.")
    if (
        not isinstance(candidate_ids, list)
        or not candidate_ids
        or any(not isinstance(item, str) or not item.strip() for item in candidate_ids)
        or len(set(candidate_ids)) != len(candidate_ids)
    ):
        raise DeviceError(
            "Command payload candidate_ids must be a nonempty array of unique strings."
        )

    present_lineage = SPEC_LINEAGE_PAYLOAD_FIELDS & set(payload)
    if present_lineage and present_lineage != SPEC_LINEAGE_PAYLOAD_FIELDS:
        missing_lineage = SPEC_LINEAGE_PAYLOAD_FIELDS - present_lineage
        raise DeviceError(
            "ExperimentSpec lineage payload is incomplete; missing "
            + ", ".join(sorted(missing_lineage))
            + "."
        )
    if (
        OPTIONAL_SOURCE_LINEAGE_PAYLOAD_FIELDS & set(payload)
        and present_lineage != SPEC_LINEAGE_PAYLOAD_FIELDS
    ):
        raise DeviceError(
            "source lineage is allowed only with complete ExperimentSpec lineage."
        )
    if "material_batch_ids" in payload and present_lineage != SPEC_LINEAGE_PAYLOAD_FIELDS:
        raise DeviceError(
            "material_batch_ids are allowed only with complete ExperimentSpec lineage."
        )
    if present_lineage:
        if (
            not isinstance(payload["experiment_spec_id"], str)
            or not payload["experiment_spec_id"].strip()
        ):
            raise DeviceError(
                "Command payload experiment_spec_id must be a nonempty string."
            )
        if "cocktail_design_id" in payload and (
            not isinstance(payload["cocktail_design_id"], str)
            or not payload["cocktail_design_id"].strip()
        ):
            raise DeviceError(
                "Command payload cocktail_design_id must be a nonempty string."
            )
        digest = payload["experiment_spec_sha256"]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise DeviceError(
                "Command payload experiment_spec_sha256 must be a SHA-256 digest."
            )
        profile_ids = payload["phage_profile_ids"]
        if (
            not isinstance(profile_ids, list)
            or not profile_ids
            or any(not isinstance(item, str) or not item.strip() for item in profile_ids)
            or len(set(profile_ids)) != len(profile_ids)
            or len(profile_ids) != len(candidate_ids)
        ):
            raise DeviceError(
                "Command payload phage_profile_ids must be unique strings aligned "
                "one-to-one with candidate_ids."
            )
        arms = payload["experiment_arms"]
        if not isinstance(arms, list) or not arms:
            raise DeviceError(
                "Command payload experiment_arms must be a nonempty array."
            )
        arm_ids = []
        arm_profiles = set()
        required_arm_fields = {
            "arm_id",
            "role",
            "target_host",
            "phage_profile_ids",
            "conditions",
            "expected_readouts",
        }
        for arm in arms:
            if not isinstance(arm, dict) or set(arm) != required_arm_fields:
                raise DeviceError(
                    "Command payload experiment_arms contain an invalid arm shape."
                )
            if not isinstance(arm["arm_id"], str) or not arm["arm_id"].strip():
                raise DeviceError("Experiment arm_id must be a nonempty string.")
            arm_ids.append(arm["arm_id"])
            if arm["role"] not in {"control", "treatment"}:
                raise DeviceError("Experiment arm role must be control or treatment.")
            arm_phages = arm["phage_profile_ids"]
            if (
                not isinstance(arm_phages, list)
                or any(
                    not isinstance(item, str) or not item.strip()
                    for item in arm_phages
                )
                or len(set(arm_phages)) != len(arm_phages)
            ):
                raise DeviceError(
                    "Experiment arm phage_profile_ids must be unique strings."
                )
            arm_profiles.update(arm_phages)
            if not isinstance(arm["conditions"], dict):
                raise DeviceError("Experiment arm conditions must be an object.")
            if (
                not isinstance(arm["expected_readouts"], list)
                or not arm["expected_readouts"]
                or any(
                    not isinstance(item, str) or not item.strip()
                    for item in arm["expected_readouts"]
                )
            ):
                raise DeviceError(
                    "Experiment arm expected_readouts must be nonempty strings."
                )
            if not isinstance(arm["target_host"], dict):
                raise DeviceError("Experiment arm target_host must be an object.")
        if len(set(arm_ids)) != len(arm_ids):
            raise DeviceError("Experiment arm IDs must be unique.")
        if arm_profiles != set(profile_ids):
            raise DeviceError(
                "Experiment arm phage membership must match phage_profile_ids."
            )

        if "material_batch_ids" in payload:
            batch_ids = payload["material_batch_ids"]
            if (
                not isinstance(batch_ids, list)
                or not batch_ids
                or any(
                    not isinstance(item, str) or not item.strip()
                    for item in batch_ids
                )
                or len(set(batch_ids)) != len(batch_ids)
            ):
                raise DeviceError(
                    "Command payload material_batch_ids must be a nonempty array "
                    "of unique strings."
                )
    return payload


@dataclass(frozen=True)
class Command:
    command_id: str
    operation: str
    payload: dict
    attempt: int = 1


def validate_safe_state(manifest: dict, device_id: str) -> dict:
    """Check the `safe_state` block of a driver manifest and return it.

    A driver that will move real liquid has to answer two questions before it
    is allowed to run: what does your hardware do when we abandon a step, and
    does that leave the hazard held by the machine. Guessing either on a
    driver's behalf would be guessing about someone's exposure.
    """
    block = manifest.get("safe_state")
    if not isinstance(block, dict):
        raise DeviceError(
            f"Device {device_id!r} does not declare safe_state. A real-hardware driver must "
            f"state what its apparatus does when a step is abandoned (one of "
            f"{', '.join(SAFE_STATE_POLICIES)}).")
    policy = block.get("policy")
    if policy not in SAFE_STATE_POLICIES:
        raise DeviceError(
            f"Device {device_id!r} declares unknown safe_state policy {policy!r}; "
            f"expected one of {', '.join(SAFE_STATE_POLICIES)}.")
    retains = block.get("retains_hazard")
    if not isinstance(retains, bool):
        raise DeviceError(
            f"Device {device_id!r} must state safe_state.retains_hazard as a boolean: "
            "whether an abandoned step leaves hazardous material held by the apparatus.")
    if policy in HAZARD_RETAINING_POLICIES and not retains:
        raise DeviceError(
            f"Device {device_id!r} declares policy {policy!r} with retains_hazard=False. "
            "Holding position or waiting for an operator means the apparatus is still "
            "holding whatever it held.")
    description = block.get("description")
    if not isinstance(description, str) or not description.strip():
        raise DeviceError(
            f"Device {device_id!r} must describe its safe state in words, so an operator "
            "reading a run report knows what they are walking up to.")
    return block


class DeviceDriver(Protocol):
    """Contract implemented by concrete instrument adapters.

    See `docs/hardware.md` for what each method must mean on real hardware.
    """

    def describe(self) -> dict:
        """Identity and capabilities.

        Required: `device_id`, `operations`, `simulated`. A driver with
        `simulated=False` must also carry a `safe_state` block
        (`validate_safe_state` defines it) because real execution refuses a
        driver that will not say what its hardware does when a step is
        abandoned.
        """
        ...

    async def read(self, job_id: str | None = None) -> dict:
        """Authoritative state, queried from the instrument rather than cached.

        With no `job_id`, describe the device. With one, report that job's
        state. Raise `DeviceUnavailable` rather than guessing: a fabricated
        "probably finished" is what makes a controller repeat a physical step.
        """
        ...

    async def write(self, command: Command) -> str:
        """Submit one command and return the instrument's job identifier.

        Must be idempotent on `command_id`: a resubmitted command returns the
        existing job rather than starting a second physical action.
        """
        ...

    async def wait(self, job_id: str) -> dict:
        """Wait for completion. A timeout here must not cancel the job.

        The controller imposes its own deadline and then reconciles. A driver
        that cancels on timeout turns "we don't know yet" into a real abort.
        """
        ...

    async def cancel(self, job_id: str) -> bool:
        """Request cancellation; return True only on instrument acknowledgement.

        Returning True without confirmation lets the controller start a second
        attempt while the first is still physically moving.
        """
        ...

    async def enter_safe_state(self, reason: str) -> dict:
        """Bring the apparatus to the safe state this driver declared.

        Called when a step is abandoned, including when the run is stopping.
        Return at least `{"entered": bool, "policy": str, "retains_hazard":
        bool, "detail": str}`. Report `entered=False`, or raise
        `SafeStateError`, when the instrument did not confirm; the run report
        then tells the operator the physical state is unknown instead of
        implying the bench is clear.
        """
        ...

    async def close(self) -> None:
        """Release local driver resources. Not a safe-state request."""
        ...

    def quarantine(self) -> None:
        """Optional: stop routing new work to this driver after a failover.

        Drivers that cannot be taken out of service may leave this
        unimplemented; the scheduler treats it as advisory.
        """

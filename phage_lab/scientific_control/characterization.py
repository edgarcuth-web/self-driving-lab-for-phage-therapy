"""Bounded execution of trusted host-characterization modules."""

from ..feature_artifact import validate_feature_artifact
from ..padloc_adapter import PADLOC_VERSION
from .contracts import ArtifactReference, ModuleInvocation, ScientificTask
from .registry import PADLOC_HOST_DEFENSE_ID, TRUSTED_MODULES


def execute_host_defense_characterization(
    task: ScientificTask,
    *,
    host_state_path,
    sequence_registry_path,
    padloc_data_dir,
    output_dir,
    padloc_executable="padloc",
    cpu: int = 1,
    timeout_seconds: int = 7200,
):
    """Run only a ready PADLOC task and record exact FeatureArtifact lineage."""

    if (
        not isinstance(task, ScientificTask)
        or task.kind != "characterize_host_defense"
        or task.state != "ready"
        or task.module_id != PADLOC_HOST_DEFENSE_ID
    ):
        raise ValueError("executor requires a ready PADLOC host-characterization task.")

    module = TRUSTED_MODULES[PADLOC_HOST_DEFENSE_ID]
    if task.module_version != module.version:
        raise ValueError("PADLOC task module version does not match the trusted registry.")

    result = module.call(
        host_state_path=host_state_path,
        sequence_registry_path=sequence_registry_path,
        padloc_data_dir=padloc_data_dir,
        output_dir=output_dir,
        padloc_executable=padloc_executable,
        cpu=cpu,
        timeout_seconds=timeout_seconds,
    )
    if not isinstance(result, dict) or not isinstance(result.get("artifact"), dict):
        raise ValueError("trusted PADLOC module returned no FeatureArtifact.")
    artifact = validate_feature_artifact(result["artifact"])
    if (
        artifact["feature_set"] != "host_defense_systems"
        or artifact["status"] != "complete"
        or artifact["analysis"]["tool"]["name"] != "PADLOC"
        or artifact["analysis"]["tool"]["version"] != PADLOC_VERSION
    ):
        raise ValueError("trusted PADLOC output is not a complete host-defense FeatureArtifact.")

    host_refs = [item for item in task.inputs if item.artifact_type == "HostState"]
    if len(host_refs) != 1:
        raise ValueError("PADLOC task must bind exactly one HostState input.")
    if artifact["subject"].get("source_record_sha256") != host_refs[0].content_sha256:
        raise ValueError("PADLOC FeatureArtifact does not bind the task HostState.")

    output = ArtifactReference(
        artifact_type="FeatureArtifact",
        artifact_id=artifact["artifact_id"],
        content_sha256=artifact["content_sha256"],
    )
    invocation = ModuleInvocation(
        module_id=module.module_id,
        module_version=module.version,
        inputs=task.inputs,
        output=output,
    )
    return result, invocation

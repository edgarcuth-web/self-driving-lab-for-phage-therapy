"""Frozen pairwise model inputs and source-endpoint result admission.

Exports are local directories. No model execution, registry lookup by consumers,
automatic label mapping, or laboratory scheduling happens here.
"""

from functools import lru_cache
from pathlib import Path
import shutil
import tempfile

from jsonschema import Draft202012Validator, FormatChecker

from .artifacts import (atomic_write_json, canonical_content_sha256, content_hash,
                        parse_timestamp, read_json_object, sha256_file, utc_now)
from .feature_artifact import load_feature_artifact, validate_feature_artifact
from .host_state import host_state_from_dict
from .phage_profile import phage_profile_from_dict
from .sequence_registry import (load_sequence_registry, resolve_registered_phage_sequence,
                                resolve_registered_host_genome, fingerprint_fasta)

SCHEMAS = Path(__file__).resolve().parent.parent / "schemas"


@lru_cache(maxsize=2)
def _validator(name):
    schema = read_json_object(SCHEMAS / f"{name}-v1.schema.json")
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _validate(document, name):
    errors = list(_validator(name).iter_errors(document))
    if errors:
        raise ValueError(f"invalid {name}: {errors[0].message}")
    if type(document["schema_version"]) is not int:
        raise ValueError("schema_version must be an integer")
    if document["content_sha256"] != canonical_content_sha256(document):
        raise ValueError(f"{name} content hash mismatch")


def _local_path(root, relative):
    if (not isinstance(relative, str) or not relative or "\\" in relative
            or ":" in relative or any(p in {"", ".", ".."} for p in relative.split("/"))):
        raise ValueError("resource path must be a confined relative path")
    target = (root / relative).resolve(strict=True)
    if not target.is_relative_to(root.resolve()) or not target.is_file():
        raise ValueError("resource path escapes bundle or is not a file")
    return target


def _verify_file(root, resource):
    path = _local_path(root, resource["path"])
    if path.stat().st_size != resource["size_bytes"] or sha256_file(path) != resource["sha256"]:
        raise ValueError(f"resource size or SHA-256 mismatch: {resource['path']}")
    return path


def _sequence_identity(bundle, subject, resource):
    if subject == "host":
        expected = bundle["host_state"]["host_genome_sha256"]
        if resource["sequence_sha256"] != expected:
            raise ValueError("host sequence identity mismatch")
        return
    profile = bundle["phage_profile"]
    sequence = profile["sequence"] or {}
    if sequence.get("sha256"):
        if resource["sequence_sha256"] != sequence["sha256"]:
            raise ValueError("phage sequence identity mismatch")
    elif not (sequence.get("accession") and profile["provenance"].get("snapshot_sha256")):
        raise ValueError("phage sequence requires exact digest or accession/snapshot")
    if sequence.get("accession") and resource["accession"] != sequence["accession"]:
        raise ValueError("phage accession mismatch")
    snapshot = profile["provenance"].get("snapshot_sha256")
    if snapshot and resource["source_snapshot_sha256"] != snapshot:
        raise ValueError("phage source snapshot mismatch")


def load_model_input_bundle(path, *, required_sequences=()):
    """Re-admit snapshots, provenance, chronology and every packaged file."""
    path = Path(path)
    bundle = read_json_object(path)
    _validate(bundle, "model-input-bundle")
    host = host_state_from_dict(bundle["host_state"])
    phage = phage_profile_from_dict(bundle["phage_profile"])
    if content_hash(phage.to_dict()) != bundle["phage_profile_sha256"]:
        raise ValueError("PhageProfile hash mismatch")
    created = parse_timestamp(bundle["created_at"])
    if any(parse_timestamp(t) > created for t in (host.as_of, host.created_at, phage.created_at)):
        raise ValueError("bundle cannot predate its input snapshots")
    context = bundle["assay_context"]
    if context["status"] == "unknown" and (context["conditions"] or context["evidence"]):
        raise ValueError("unknown assay_context must not contain declared conditions/evidence")
    if context["status"] == "declared" and (not context["conditions"] or not context["evidence"]):
        raise ValueError("declared assay_context requires conditions and evidence")
    seen_subjects, seen_paths = set(), set()
    for resource in bundle["resources"]:
        subject = resource["subject"]
        if subject in seen_subjects or resource["path"] in seen_paths:
            raise ValueError("duplicate sequence subject or resource path")
        seen_subjects.add(subject)
        seen_paths.add(resource["path"])
        _sequence_identity(bundle, subject, resource)
        source = _verify_file(path.parent, resource)
        actual = fingerprint_fasta(source, kind="host_genome" if subject == "host" else "phage_sequence")
        if actual.sequence_sha256 != resource["sequence_sha256"]:
            raise ValueError("sequence payload does not match normalized identity")
    for subject in ("host", "phage"):
        expected = "available" if subject in seen_subjects else "not_provided"
        if bundle["sequence_status"][subject] != expected:
            raise ValueError("sequence_status does not match packaged resources")
    if set(required_sequences) - {"host", "phage"}:
        raise ValueError("required sequences must be host or phage")
    for subject in required_sequences:
        if subject not in seen_subjects:
            raise ValueError(f"required {subject} sequence not provided")
    feature_ids = set()
    for entry in bundle["feature_artifacts"]:
        artifact = validate_feature_artifact(entry["manifest"])
        if artifact["artifact_id"] in feature_ids:
            raise ValueError("duplicate FeatureArtifact ID")
        feature_ids.add(artifact["artifact_id"])
        if parse_timestamp(artifact["created_at"]) > created:
            raise ValueError("bundle cannot predate FeatureArtifact")
        subject = artifact["subject"]
        if subject["kind"] == "host_genome":
            matches = subject["id"] in {host.record_id, host.host_profile_id}
            digest = host.host_genome_sha256
        else:
            matches = subject["id"] == phage.profile_id
            digest = (phage.to_dict()["sequence"] or {}).get("sha256")
            if digest is None:
                digest = next((r["sequence_sha256"] for r in bundle["resources"] if r["subject"] == "phage"), None)
        if not matches or subject["sequence_sha256"] != digest:
            raise ValueError("FeatureArtifact subject does not match exact pair")
        for output in artifact["outputs"]:
            relative = f"{entry['directory']}/{output['path']}"
            if relative in seen_paths:
                raise ValueError("duplicate feature resource path")
            seen_paths.add(relative)
            _verify_file(path.parent, {**output, "path": relative})
    return bundle


def export_model_input_bundle(host_state, phage_profile, *, endpoint, assay_context,
                              bundle_id, output_dir, created_at=None,
                              sequence_registry=None, include_sequences=(), feature_artifacts=()):
    """Copy verified inputs into a new portable directory; never overwrite exports."""
    destination = Path(output_dir)
    if destination.exists():
        raise ValueError("bundle directory already exists; refusing to overwrite")
    if len(set(include_sequences)) != len(include_sequences) or set(include_sequences) - {"host", "phage"}:
        raise ValueError("include_sequences must contain unique host/phage subjects")
    if include_sequences and sequence_registry is None:
        raise ValueError("sequence export requires a sequence_registry")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".bundle-", dir=destination.parent))
    try:
        document = {
            "schema_version": 1, "kind": "model_input_bundle", "bundle_id": bundle_id,
            "created_at": created_at or utc_now(), "endpoint": endpoint,
            "assay_context": assay_context, "host_state": host_state.to_dict(),
            "phage_profile": phage_profile.to_dict(),
            "phage_profile_sha256": content_hash(phage_profile.to_dict()),
            "sequence_status": {"host": "not_provided", "phage": "not_provided"},
            "resources": [], "feature_artifacts": [],
        }
        registry = load_sequence_registry(sequence_registry) if include_sequences else None
        for subject in include_sequences:
            if subject == "host":
                asset = resolve_registered_host_genome(sequence_registry, host_state.host_genome_sha256).asset
            else:
                asset = resolve_registered_phage_sequence(sequence_registry, phage_profile)
            relative = f"sequences/{subject}.fasta"
            target = staging / relative
            target.parent.mkdir(exist_ok=True)
            shutil.copyfile(asset.path, target)
            document["resources"].append({
                "subject": subject, "path": relative, "sha256": asset.file_sha256,
                "size_bytes": target.stat().st_size, "sequence_sha256": asset.sequence_sha256,
                "registry": {"registry_id": registry.registry_id, "file_sha256": registry.file_sha256},
                "accession": asset.accession, "source_snapshot_sha256": asset.source_snapshot_sha256,
            })
            document["sequence_status"][subject] = "available"
        for index, manifest_path in enumerate(feature_artifacts):
            manifest_path = Path(manifest_path)
            artifact = load_feature_artifact(manifest_path)
            directory = f"features/{index}"
            for output in artifact["outputs"]:
                source = _verify_file(manifest_path.parent, output)
                target = staging / directory / output["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            document["feature_artifacts"].append({"directory": directory, "manifest": artifact})
        document["content_sha256"] = canonical_content_sha256(document)
        manifest = staging / "bundle.json"
        atomic_write_json(document, manifest)
        load_model_input_bundle(manifest)
        staging.rename(destination)
        return destination / "bundle.json"
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def load_pair_prediction(path, bundle_path):
    """Admit a source-endpoint output, never a mechanistic InteractionPrediction."""
    bundle = load_model_input_bundle(bundle_path)
    result = read_json_object(path)
    _validate(result, "pair-prediction")
    if (result["bundle_id"], result["bundle_sha256"]) != (bundle["bundle_id"], bundle["content_sha256"]):
        raise ValueError("prediction does not bind the exact bundle")
    if parse_timestamp(result["created_at"]) < parse_timestamp(bundle["created_at"]):
        raise ValueError("prediction cannot predate bundle")
    estimate, producer = result["estimate"], result["producer"]
    if estimate["status"] == "not_estimated":
        if estimate["value"] is not None or estimate["uncertainty"] is not None:
            raise ValueError("not_estimated must have null values and uncertainty")
    else:
        if estimate["value"] is None or not producer["artifact_sha256"] or not producer["preprocessing_sha256"]:
            raise ValueError("estimated output requires value, model and preprocessing digests")
        interval = estimate["uncertainty"]
        if interval and not interval["lower"] <= estimate["value"] <= interval["upper"]:
            raise ValueError("uncertainty interval must contain value")
        if estimate["status"] == "probability" and (
                not interval or not producer["calibration_sha256"]
                or bundle["endpoint"]["assay_definition_status"] != "verified"):
            raise ValueError("probability requires verified assay definition, calibration digest and uncertainty")
    return result

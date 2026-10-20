"""Cross-repository CLI round trip with synthetic fixtures; no model/hardware run."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from phage_lab.artifacts import atomic_write_json
from phage_lab.host_state import host_state_from_dict
from phage_lab.phage_profile import phage_profile_from_dict
from phage_lab.model_input_bundle import export_model_input_bundle, load_model_input_bundle, load_pair_prediction
from phage_lab.sequence_registry import create_sequence_registry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-repo", type=Path, required=True)
    args = parser.parse_args()
    model = args.model_repo.resolve(strict=True)
    for name in ("model-input-bundle-v1.schema.json", "pair-prediction-v1.schema.json",
                 "model-request-v1.schema.json", "model-result-v1.schema.json"):
        if (ROOT / "schemas" / name).read_bytes() != (model / "schemas" / name).read_bytes():
            raise ValueError(f"schema drift: {name}")
    fixture = ROOT / "tests/fixtures/input_bundle"
    model_fixture = model / "tests/fixtures/input_bundle"
    files = {p.relative_to(fixture) for p in fixture.rglob("*") if p.is_file()}
    if files != {p.relative_to(model_fixture) for p in model_fixture.rglob("*") if p.is_file()}:
        raise ValueError("fixture file lists differ")
    for relative in files:
        if (fixture / relative).read_bytes() != (model_fixture / relative).read_bytes():
            raise ValueError(f"fixture drift: {relative}")
    original = load_model_input_bundle(fixture / "bundle.json")
    env = {**os.environ, "PYTHONPATH": str(model / "src")}

    def call_model(*arguments, success=True):
        proc = subprocess.run([sys.executable, "-m", "phage_cocktail.model_interface", *map(str, arguments)],
                              cwd=model, env=env, capture_output=True, text=True)
        if (proc.returncode == 0) != success:
            raise ValueError(proc.stdout + proc.stderr)

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        fasta = root / "host.fna"
        shutil.copyfile(fixture / original["resources"][0]["path"], fasta)
        registry = root / "registry.json"
        create_sequence_registry(fasta, registry, registry_id="round-trip-registry")
        entry = original["feature_artifacts"][0]
        annotation = root / "annotation"
        shutil.copytree(fixture / entry["directory"], annotation)
        artifact = annotation / "artifact.json"
        atomic_write_json(entry["manifest"], artifact)
        bundle = export_model_input_bundle(
            host_state_from_dict(original["host_state"]), phage_profile_from_dict(original["phage_profile"]),
            endpoint=original["endpoint"], assay_context=original["assay_context"],
            bundle_id="fresh-round-trip", output_dir=root / "export",
            created_at=original["created_at"], sequence_registry=registry,
            include_sequences=("host",), feature_artifacts=(artifact,),
        )
        # A model sees only this relocated export, never the original registry.
        relocated = root / "relocated"
        shutil.copytree(bundle.parent, relocated)
        shutil.rmtree(bundle.parent)
        fasta.unlink()
        registry.unlink()
        shutil.rmtree(annotation)
        bundle = relocated / "bundle.json"
        call_model("validate-bundle", bundle, "--require-sequence", "host")
        call_model("validate-bundle", bundle, "--require-sequence", "phage", success=False)
        result = root / "result.json"
        call_model("create-unresolved-pair-prediction", bundle, result, "--prediction-id", "round-trip-result")
        call_model("validate-pair-prediction", result, "--bundle", bundle)
        admitted = load_pair_prediction(result, bundle)
        if admitted["estimate"]["status"] != "not_estimated":
            raise ValueError("unexpected inference")
        call_model("create-unresolved-pair-prediction", bundle, result, "--prediction-id", "overwrite", success=False)
        changed = json.loads(bundle.read_text())
        (relocated / changed["resources"][0]["path"]).write_text("tampered")
        call_model("validate-bundle", bundle, success=False)
    print("Schemas and fixtures match; fresh export, relocation, model CLI and SDL result admission passed.")


if __name__ == "__main__":
    main()

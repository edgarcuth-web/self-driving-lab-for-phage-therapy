"""File-based model exchange commands; no inference or physical execution."""

import sys

from ..artifacts import read_json_object
from ..host_state import load_host_state
from ..phage_profile import load_phage_profile
from ..model_input_bundle import export_model_input_bundle, load_model_input_bundle, load_pair_prediction


def _export_bundle(args, parser):
    try:
        path = export_model_input_bundle(
            load_host_state(args.host_state), load_phage_profile(args.phage_profile),
            endpoint=read_json_object(args.endpoint), assay_context=read_json_object(args.assay_context),
            bundle_id=args.bundle_id, output_dir=args.outdir, created_at=args.created_at,
            sequence_registry=args.sequence_registry, include_sequences=tuple(args.include_sequence),
            feature_artifacts=args.feature_artifact,
        )
        print(f"Exported ModelInputBundle: {path}")
        return 0
    except (OSError, ValueError) as exc:
        print(f"ModelInputBundle export failed: {exc}", file=sys.stderr)
        return 2


def _validate_bundle(args, parser):
    try:
        bundle = load_model_input_bundle(args.bundle, required_sequences=args.require_sequence)
        print(f"Valid ModelInputBundle: {bundle['bundle_id']} sha256={bundle['content_sha256']}")
        return 0
    except (OSError, ValueError) as exc:
        print(f"ModelInputBundle validation failed: {exc}", file=sys.stderr)
        return 2


def _validate_pair_prediction(args, parser):
    try:
        result = load_pair_prediction(args.result, args.bundle)
        print(f"Valid source-endpoint PairPrediction: {result['prediction_id']}; {result['estimate']['status']}")
        return 0
    except (OSError, ValueError) as exc:
        print(f"PairPrediction admission failed: {exc}", file=sys.stderr)
        return 2

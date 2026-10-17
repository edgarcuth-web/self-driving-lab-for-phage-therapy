"""CLI handlers for the research-only InteractionModel v0."""

import json
import sys

from .io import _load_json


def _interaction_feature_vector(args, parser) -> int:
    required = (
        ("--host-state", args.host_state),
        ("--phage-profile", args.phage_profile),
        ("--feature-input", args.feature_input),
        ("--vector-id", args.vector_id),
        ("--out", args.out),
    )
    missing = [name for name, value in required if not value]
    if missing:
        parser.error("interaction-feature-vector requires " + ", ".join(missing))
    if args.vector_revision < 1:
        parser.error("--vector-revision must be a positive integer")

    from ..host_state import load_host_state
    from ..interaction_model import (
        feature_producer_from_dict,
        feature_source_from_dict,
        new_interaction_feature_vector,
        write_interaction_feature_vector,
    )
    from ..phage_profile import load_phage_profile

    try:
        state = load_host_state(args.host_state)
        profile = load_phage_profile(args.phage_profile)
        payload = _load_json(args.feature_input, "Feature input")
        if not isinstance(payload, dict) or set(payload) != {
            "features", "feature_sources", "producer"
        }:
            raise ValueError(
                "Feature input must contain exactly features, feature_sources and producer."
            )
        if not isinstance(payload["feature_sources"], dict):
            raise ValueError("feature_sources must be an object.")
        vector = new_interaction_feature_vector(
            state,
            profile,
            payload["features"],
            {
                name: feature_source_from_dict(source)
                for name, source in payload["feature_sources"].items()
            },
            feature_producer_from_dict(payload["producer"]),
            vector_id=args.vector_id,
            revision=args.vector_revision,
            created_at=args.created_at,
        )
        write_interaction_feature_vector(vector, args.out)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"InteractionFeatureVector 创建失败：{exc}", file=sys.stderr)
        return 2

    print(f"InteractionFeatureVector {vector.record_id} → {args.out}", flush=True)
    print(
        "该向量只包装上游特征及其来源；本命令不运行生物学 feature extractor。",
        file=sys.stderr,
    )
    return 0


def _interaction_model_train(args, parser) -> int:
    required = (
        ("--dataset", args.dataset),
        ("--model-id", args.model_id),
        ("--out", args.out),
    )
    missing = [name for name, value in required if not value]
    if missing:
        parser.error("interaction-model-train requires " + ", ".join(missing))

    from ..interaction_model import (
        model_training_example_from_dict,
        train_interaction_model,
        write_interaction_model,
    )

    try:
        payload = _load_json(args.dataset, "InteractionModel training dataset")
        if not isinstance(payload, list):
            raise ValueError("training dataset must be a JSON array.")
        examples = [model_training_example_from_dict(item) for item in payload]
        model = train_interaction_model(
            examples,
            model_id=args.model_id,
            revision=args.model_revision,
            test_fraction=args.test_fraction,
            seed=args.seed,
            epochs=args.epochs,
            learning_rate=args.learning_rate,
            l2=args.l2,
            created_at=args.created_at,
        )
        write_interaction_model(model, args.out)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"InteractionModel training failed: {exc}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "model_id": model.record_id,
                "model_status": model.model_status,
                "calibration_status": model.calibration_status,
                "dataset_sha256": model.training_dataset_sha256,
                "metrics": model.metrics,
                "output": str(args.out),
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    print(
        "研究基线已训练；raw score 未校准，不能作为 InteractionPrediction 或临床证据。",
        file=sys.stderr,
    )
    return 0


def _interaction_model_score(args, parser) -> int:
    required = (
        ("--model", args.model),
        ("--feature-vector", args.feature_vector),
        ("--prediction-id", args.prediction_id),
        ("--out", args.out),
    )
    missing = [name for name, value in required if not value]
    if missing:
        parser.error("interaction-model-score requires " + ", ".join(missing))

    from ..interaction_model import (
        load_interaction_feature_vector,
        load_interaction_model,
        predict_research_score,
        write_research_prediction,
    )

    try:
        model = load_interaction_model(args.model)
        vector = load_interaction_feature_vector(args.feature_vector)
        prediction = predict_research_score(
            model,
            vector,
            prediction_id=args.prediction_id,
            predicted_at=args.predicted_at,
        )
        write_research_prediction(prediction, args.out)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"InteractionModel scoring failed: {exc}", file=sys.stderr)
        return 2

    print(f"ResearchPrediction {prediction.record_id} → {args.out}", flush=True)
    print(
        f"uncalibrated research score: {prediction.uncalibrated_probability:.6f}; "
        "not an InteractionPrediction",
        file=sys.stderr,
    )
    return 0

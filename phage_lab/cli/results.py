"""Results command handlers."""

import json
import sys

from .io import _load_json, _load_measurements


def _material_batch(args, parser) -> int:
    """Register one versioned physical MaterialBatch."""

    missing = [
        name
        for name, value in (
            ("--batch-id", args.batch_id),
            ("--material-type", args.material_type),
            ("--profile-id", args.profile_id),
            ("--material-source-kind", args.material_source_kind),
            ("--material-source-reference", args.material_source_reference),
            ("--out", args.out),
        )
        if not value
    ]
    if missing:
        parser.error("material-batch requires " + ", ".join(missing))

    from ..material_batch import new_material_batch, write_material_batch

    try:
        batch = new_material_batch(
            args.batch_id,
            material_type=args.material_type,
            profile_id=args.profile_id,
            source_kind=args.material_source_kind,
            source_reference=args.material_source_reference,
            quality_status=args.quality_status,
            availability_status=args.availability_status,
            quality_evidence=tuple(args.quality_evidence),
        )
        write_material_batch(batch, args.out)
    except (OSError, ValueError) as exc:
        print(f"MaterialBatch 创建失败：{exc}", file=sys.stderr)
        return 2

    print(
        f"MaterialBatch {batch.record_id}：{batch.material_type} / "
        f"{batch.quality_status} / {batch.availability_status} → {args.out}",
        flush=True,
    )
    return 0


def _measurement(args, parser) -> int:
    """Ingest one run result as a first-class Measurement."""

    missing = [
        name
        for name, value in (
            ("--run-report", args.run_report),
            ("--measurement-id", args.measurement_id),
            ("--out", args.out),
        )
        if not value
    ]
    if missing:
        parser.error("measurement requires " + ", ".join(missing))

    from ..measurement import measurement_from_run_report, write_measurement

    try:
        report = _load_json(args.run_report, "Run report")
        measurement = measurement_from_run_report(
            report,
            measurement_id=args.measurement_id,
            arm_id=args.arm_id,
            source_step=args.step,
            measurement_type=args.measurement_type,
            qc_status=args.qc_status,
            qc_evidence=tuple(args.qc_evidence),
        )
        write_measurement(measurement, args.out)
    except (OSError, ValueError) as exc:
        print(f"Measurement ingestion 失败：{exc}", file=sys.stderr)
        return 2

    print(
        f"Measurement {measurement.record_id}：{measurement.origin} / "
        f"QC={measurement.qc_status} / evidence={measurement.evidence_class} → {args.out}",
        flush=True,
    )
    if measurement.evidence_class == "none":
        print(
            "该 Measurement 来自非物理执行，只能用于控制链路/fixture 分析，不能支持 Phenotype。",
            file=sys.stderr,
        )
    return 0


def _phenotype(args, parser) -> int:
    """Create an explicit Phenotype from admitted physical Measurements."""

    missing = [
        name
        for name, value in (
            ("--experiment-spec", args.experiment_spec),
            ("--measurements", args.measurements),
            ("--phenotype-id", args.phenotype_id),
            ("--phenotype-type", args.phenotype_type),
            ("--phenotype-outcome", args.phenotype_outcome),
            ("--interpretation", args.interpretation),
            ("--assessor", args.assessor),
            ("--out", args.out),
        )
        if not value
    ]
    if missing:
        parser.error("phenotype requires " + ", ".join(missing))

    from ..experiment_spec import load_experiment_spec
    from ..phenotype import phenotype_from_measurements, write_phenotype

    value = args.phenotype_value
    if value is not None:
        try:
            parsed = json.loads(value)
        except ValueError:
            parsed = value
        if isinstance(parsed, (dict, list, bool)):
            parser.error("--phenotype-value must be a scalar JSON value or string")
        value = parsed

    try:
        spec = load_experiment_spec(args.experiment_spec)
        measurements = _load_measurements(args.measurements)
        phenotype = phenotype_from_measurements(
            spec,
            measurements,
            arm_id=args.arm_id,
            phenotype_id=args.phenotype_id,
            phenotype_type=args.phenotype_type,
            outcome=args.phenotype_outcome,
            value=value,
            unit=args.unit,
            interpretation=args.interpretation,
            assessor_name=args.assessor,
            assessor_version=args.assessor_version,
        )
        write_phenotype(phenotype, args.out)
    except (OSError, ValueError) as exc:
        print(f"Phenotype ingestion 失败：{exc}", file=sys.stderr)
        return 2

    print(
        f"Phenotype {phenotype.record_id}：{phenotype.phenotype_type} / "
        f"{phenotype.outcome} → {args.out}",
        flush=True,
    )
    return 0


def _phenotype_comparison(args, parser) -> int:
    """Record an explicit comparison between two arm-scoped Phenotypes."""

    required = (
        ("--experiment-spec", args.experiment_spec),
        ("--baseline-phenotype", args.baseline_phenotype),
        ("--comparator-phenotype", args.comparator_phenotype),
        ("--comparison-id", args.comparison_id),
        ("--comparison-type", args.comparison_type),
        ("--comparison-outcome", args.comparison_outcome),
        ("--interpretation", args.interpretation),
        ("--assessor", args.assessor),
        ("--out", args.out),
    )
    missing = [name for name, value in required if not value]
    if missing:
        parser.error("phenotype-comparison requires " + ", ".join(missing))

    from ..experiment_spec import load_experiment_spec
    from ..phenotype import (
        load_phenotype,
        phenotype_comparison_from_phenotypes,
        write_phenotype_comparison,
    )

    value = args.comparison_value
    if value is not None:
        try:
            parsed = json.loads(value)
        except ValueError:
            parsed = value
        if isinstance(parsed, (dict, list, bool)):
            parser.error("--comparison-value must be a scalar JSON value or string")
        value = parsed

    try:
        spec = load_experiment_spec(args.experiment_spec)
        baseline = load_phenotype(args.baseline_phenotype)
        comparator = load_phenotype(args.comparator_phenotype)
        comparison = phenotype_comparison_from_phenotypes(
            spec,
            baseline,
            comparator,
            comparison_id=args.comparison_id,
            comparison_type=args.comparison_type,
            outcome=args.comparison_outcome,
            value=value,
            unit=args.unit,
            interpretation=args.interpretation,
            assessor_name=args.assessor,
            assessor_version=args.assessor_version,
        )
        write_phenotype_comparison(comparison, args.out)
    except (OSError, ValueError) as exc:
        print(f"PhenotypeComparison 创建失败：{exc}", file=sys.stderr)
        return 2

    print(
        f"PhenotypeComparison {comparison.record_id}："
        f"{comparison.baseline_arm_id} → {comparison.comparator_arm_id} → {args.out}",
        flush=True,
    )
    return 0


def _failure_attribution(args, parser) -> int:
    missing = [name for name, value in (
        ("--experiment-spec", args.experiment_spec), ("--arm-id", args.arm_id),
        ("--measurements", args.measurements), ("--phenotypes", args.phenotypes),
        ("--attribution-id", args.attribution_id), ("--attribution-input", args.attribution_input),
        ("--assessor", args.assessor), ("--out", args.out),
    ) if not value]
    if missing:
        parser.error("failure-attribution requires " + ", ".join(missing))

    from ..experiment_spec import load_experiment_spec
    from ..phenotype import phenotype_from_dict, phenotype_comparison_from_dict
    from ..failure_attribution import (
        failure_attribution_from_results, mechanism_hypothesis_from_dict,
        write_failure_attribution,
    )
    try:
        review = _load_json(args.attribution_input, "FailureAttribution review")
        required = {"outcome", "criterion", "interpretation", "limitations"}
        optional = {"hypotheses", "assessed_at", "assessor_parameters"}
        if not isinstance(review, dict) or not required <= set(review) or set(review) - required - optional:
            raise ValueError("Review has missing or unknown fields.")
        if not isinstance(review["limitations"], list) or not isinstance(review.get("hypotheses", []), list):
            raise ValueError("Review limitations and hypotheses must be arrays.")
        attribution = failure_attribution_from_results(
            load_experiment_spec(args.experiment_spec),
            _load_measurements(args.measurements),
            [phenotype_from_dict(_load_json(path, "Phenotype")) for path in args.phenotypes],
            comparisons=[phenotype_comparison_from_dict(_load_json(path, "PhenotypeComparison"))
                         for path in args.phenotype_comparison],
            attribution_id=args.attribution_id, revision=args.attribution_revision,
            target_arm_id=args.arm_id, outcome=review["outcome"], criterion=review["criterion"],
            interpretation=review["interpretation"], limitations=review["limitations"],
            hypotheses=[mechanism_hypothesis_from_dict(item) for item in review.get("hypotheses", [])],
            assessor_name=args.assessor, assessor_version=args.assessor_version,
            assessor_parameters=review.get("assessor_parameters"),
            assessed_at=review.get("assessed_at"),
        )
        write_failure_attribution(attribution, args.out)
    except (OSError, ValueError) as exc:
        print(f"FailureAttribution 创建失败：{exc}", file=sys.stderr)
        return 2
    print(f"FailureAttribution {attribution.record_id}: {attribution.outcome}; "
          f"mechanism={attribution.mechanism_status} → {args.out}", flush=True)
    return 0


def _learning_observation(args, parser) -> int:
    """Record an explicit prediction-target label from physical Phenotype evidence."""

    required = (
        ("--interaction-prediction", args.interaction_prediction),
        ("--experiment-spec", args.experiment_spec),
        ("--phenotype", args.phenotype),
        ("--observation-id", args.observation_id),
        ("--target", args.target),
        ("--observed", args.observed),
        ("--interpretation", args.interpretation),
        ("--assessor", args.assessor),
        ("--limitation", args.limitation),
        ("--out", args.out),
    )
    missing = [name for name, value in required if not value]
    if missing:
        parser.error("learning-observation requires " + ", ".join(missing))

    from ..experiment_spec import load_experiment_spec
    from ..interaction_prediction import load_interaction_prediction
    from ..learning import new_learning_observation, write_learning_observation
    from ..phenotype import load_phenotype

    try:
        observation = new_learning_observation(
            load_interaction_prediction(args.interaction_prediction),
            load_experiment_spec(args.experiment_spec),
            load_phenotype(args.phenotype),
            observation_id=args.observation_id,
            target=args.target,
            observed=args.observed == "true",
            interpretation=args.interpretation,
            assessor_name=args.assessor,
            assessor_version=args.assessor_version,
            limitations=tuple(args.limitation),
            assessed_at=args.assessed_at,
        )
        write_learning_observation(observation, args.out)
    except (OSError, ValueError) as exc:
        print(f"LearningObservation 创建失败：{exc}", file=sys.stderr)
        return 2

    print(
        f"LearningObservation {observation.record_id}: {observation.target} / "
        f"{observation.learning_status} → {args.out}",
        flush=True,
    )
    if observation.learning_status == "label_only":
        print(
            "该 prediction 未估计此 target；标签可保留用于后续学习，但不能进入 calibration report。",
            file=sys.stderr,
        )
    return 0


def _calibration_report(args, parser) -> int:
    """Score one exact comparable prediction cohort without fitting a model."""

    missing = [name for name, value in (
        ("--learning-observation", args.learning_observation),
        ("--report-id", args.report_id),
        ("--target", args.target),
        ("--out", args.out),
    ) if not value]
    if missing:
        parser.error("calibration-report requires " + ", ".join(missing))

    from ..learning import (
        calibration_report_from_observations,
        load_learning_observation,
        write_calibration_report,
    )

    try:
        report = calibration_report_from_observations(
            [load_learning_observation(path) for path in args.learning_observation],
            report_id=args.report_id,
            target=args.target,
            created_at=args.created_at,
        )
        write_calibration_report(report, args.out)
    except (OSError, ValueError) as exc:
        print(f"CalibrationReport 创建失败：{exc}", file=sys.stderr)
        return 2

    metrics = report.metrics
    print(
        f"CalibrationReport {report.record_id}: n={metrics['sample_count']} / "
        f"Brier={metrics['brier_score']:.6g} / log-loss={metrics['log_loss']:.6g} → {args.out}",
        flush=True,
    )
    print("这是描述性评估，不会自动拟合、校准或替换模型。", file=sys.stderr)
    return 0

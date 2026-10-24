"""Experiments command handlers."""

import sys

from .io import _load_json, _load_workflow


def _experiment_spec(args, parser) -> int:
    """Create an arm-aware, execution-neutral ExperimentSpec v2."""

    missing = [
        name
        for name, value in (
            ("--experiment-id", args.experiment_id),
            ("--out", args.out),
        )
        if not value
    ]
    if missing:
        parser.error("experiment-spec requires " + ", ".join(missing))
    if sum(bool(source) for source in (args.cocktail_design, args.arms, args.candidate_set,
                                       args.active_learning_decision)) != 1:
        parser.error(
            "experiment-spec requires exactly one of --cocktail-design, --arms, --candidate-set or "
            "--active-learning-decision"
        )
    if args.active_learning_decision and any((args.objective, args.workflow, args.conditions,
                                              args.expected_readout, args.scientific_question,
                                              args.execution_constraint)):
        parser.error("Active-learning experiments preserve the recorded context; omit context overrides")
    if (args.arms or args.candidate_set) and not args.objective:
        parser.error("experiment-spec with --arms or --candidate-set requires --objective")
    if args.candidate_set and not args.expected_readout:
        parser.error("experiment-spec with --candidate-set requires --expected-readout")

    from ..experiment_spec import (
        experiment_arm_from_dict,
        experiment_spec_from_arms,
        experiment_spec_from_cocktail,
        write_experiment_spec,
    )

    try:
        workflow = _load_workflow(args.workflow)
        if args.active_learning_decision:
            from ..active_learning import (
                experiment_spec_from_active_learning, load_active_learning_decision,
            )
            spec = experiment_spec_from_active_learning(
                load_active_learning_decision(args.active_learning_decision),
                experiment_id=args.experiment_id,
            )
        elif args.cocktail_design:
            from ..cocktail_design import load_cocktail_design

            design = load_cocktail_design(args.cocktail_design)
            spec = experiment_spec_from_cocktail(
                design,
                experiment_id=args.experiment_id,
                workflow=workflow,
                purpose=args.objective,
            )
        elif args.candidate_set:
            from ..natural_phage_recommender import (
                experiment_spec_from_candidate_set, load_candidate_set,
            )

            spec = experiment_spec_from_candidate_set(
                load_candidate_set(args.candidate_set),
                experiment_id=args.experiment_id,
                workflow=workflow,
                objective=args.objective,
                expected_readouts=tuple(args.expected_readout),
                conditions=_load_json(args.conditions, "Conditions") if args.conditions else None,
            )
        else:
            arm_payload = _load_json(args.arms, "ExperimentArm")
            if not isinstance(arm_payload, list) or not arm_payload:
                raise ValueError("ExperimentArm file must contain a nonempty JSON array.")
            arms = tuple(experiment_arm_from_dict(item) for item in arm_payload)
            questions = tuple(args.scientific_question) or (args.objective,)
            constraints = tuple(args.execution_constraint) or None
            spec = experiment_spec_from_arms(
                arms,
                experiment_id=args.experiment_id,
                workflow=workflow,
                objective=args.objective,
                scientific_questions=questions,
                execution_constraints=constraints,
            )
        write_experiment_spec(spec, args.out)
    except (OSError, ValueError) as exc:
        print(f"ExperimentSpec 创建失败：{exc}", file=sys.stderr)
        return 2

    print(
        f"ExperimentSpec {spec.spec_id}：{len(spec.arms)} 个 arm / "
        f"{len(spec.member_phage_profile_ids)} 个唯一 phage → {args.out}",
        flush=True,
    )
    print(
        "ExperimentSpec v2 锁定 arm、条件与 expected readouts；"
        "设备分配仍由 orchestration 层处理。",
        file=sys.stderr,
    )
    return 0


def _active_learn(args, parser) -> int:
    missing = [name for name, value in (
        ("--candidate-set", args.candidate_set), ("--experiment-spec", args.experiment_spec),
        ("--screening-criterion", args.screening_criterion), ("--decision-id", args.decision_id),
        ("--out", args.out),
    ) if not value]
    if missing:
        parser.error("active-learn requires " + ", ".join(missing))
    from ..active_learning import (
        plan_next_screen, load_active_learning_decision, write_active_learning_decision,
    )
    from ..experiment_spec import load_experiment_spec
    from ..failure_attribution import load_failure_attribution
    from ..natural_phage_recommender import load_candidate_set
    try:
        decision = plan_next_screen(
            load_candidate_set(args.candidate_set), load_experiment_spec(args.experiment_spec),
            [load_failure_attribution(path) for path in args.failure_attribution],
            decision_id=args.decision_id, criterion=args.screening_criterion,
            previous_decision=(load_active_learning_decision(args.previous_decision)
                               if args.previous_decision else None),
            revision=args.decision_revision, created_at=args.decision_at,
        )
        write_active_learning_decision(decision, args.out)
    except (OSError, ValueError) as exc:
        print(f"ActiveLearningDecision 创建失败：{exc}", file=sys.stderr)
        return 2
    print(f"ActiveLearningDecision {decision.record_id}: {decision.status}; "
          f"{len(decision.selected_phage_profile_ids)} 个后续筛选候选 → {args.out}", flush=True)
    return 0

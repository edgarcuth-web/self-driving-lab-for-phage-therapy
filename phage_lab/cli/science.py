"""Science command handlers."""

import json
import sys

from .io import _load_json, _load_candidates


def _host_profile(args, parser) -> int:
    """Create the first version of a host record without inventing annotations."""

    missing = [name for name, value in (("--sample-id", args.sample_id), ("--out", args.out))
               if not value]
    if missing:
        parser.error("host-profile requires " + ", ".join(missing))
    from ..biology import read_fasta
    from ..host_profile import new_host_profile, write_host_profile
    try:
        genome = read_fasta(args.genome)
        profile = new_host_profile(args.sample_id, genome)
        write_host_profile(profile, args.out)
    except (OSError, ValueError) as exc:
        print(f"HostProfile 创建失败：{exc}", file=sys.stderr)
        return 2
    print(f"HostProfile {profile.profile_id} → {args.out}", flush=True)
    print("所有 biological feature class 初始为 unknown；尚未运行表征 analyzer。",
          file=sys.stderr)
    return 0


def _host_state(args, parser) -> int:
    """Create one immutable, evidence-backed HostState H(t) snapshot."""

    required = (
        ("--host-profile", args.host_profile),
        ("--host-state-id", args.host_state_id),
        ("--as-of", args.as_of),
        ("--out", args.out),
    )
    missing = [name for name, value in required if not value]
    if missing:
        parser.error("host-state requires " + ", ".join(missing))
    if args.host_state_revision < 1:
        parser.error("--host-state-revision must be a positive integer")

    from ..host_profile import load_host_profile
    from ..host_state import (
        host_state_component_from_dict,
        host_state_evidence_from_dict,
        load_host_state,
        new_host_state,
        write_host_state,
    )

    try:
        profile = load_host_profile(args.host_profile)
        components = ()
        evidence = ()
        limitations = ()
        if args.state_input is not None:
            payload = _load_json(args.state_input, "HostState input")
            if not isinstance(payload, dict) or set(payload) != {
                "components",
                "evidence",
                "limitations",
            }:
                raise ValueError(
                    "HostState input must contain exactly components, evidence and limitations."
                )
            if not all(
                isinstance(payload[name], list)
                for name in ("components", "evidence", "limitations")
            ):
                raise ValueError(
                    "HostState input components/evidence/limitations must be arrays."
                )
            components = tuple(
                host_state_component_from_dict(item)
                for item in payload["components"]
            )
            evidence = tuple(
                host_state_evidence_from_dict(item)
                for item in payload["evidence"]
            )
            limitations = tuple(payload["limitations"])

        previous = (
            load_host_state(args.previous_host_state)
            if args.previous_host_state is not None
            else None
        )
        state = new_host_state(
            profile,
            host_state_id=args.host_state_id,
            revision=args.host_state_revision,
            as_of=args.as_of,
            components=components,
            evidence=evidence,
            limitations=limitations,
            previous_state=previous,
        )
        write_host_state(state, args.out)
    except (OSError, ValueError) as exc:
        print(f"HostState 创建失败：{exc}", file=sys.stderr)
        return 2

    print(
        f"HostState {state.record_id} @ {state.as_of}："
        f"{len(state.components)} components / {len(state.evidence)} evidence → {args.out}",
        flush=True,
    )
    print(
        "HostState 只包含显式提交的动态状态；未出现的 component 仍是 unknown，"
        "不会从旧快照自动继承。",
        file=sys.stderr,
    )
    return 0


def _interaction_prediction(args, parser) -> int:
    """Create one exact HostState-phage InteractionPrediction."""

    required = (
        ("--host-state", args.host_state),
        ("--phage-profile", args.phage_profile),
        ("--prediction-id", args.prediction_id),
        ("--out", args.out),
    )
    missing = [name for name, value in required if not value]
    if missing:
        parser.error("interaction-prediction requires " + ", ".join(missing))
    if args.prediction_revision < 1:
        parser.error("--prediction-revision must be a positive integer")
    if bool(args.prediction_input) == bool(args.evidence_only_unresolved):
        parser.error(
            "interaction-prediction requires exactly one of "
            "--prediction-input or --evidence-only-unresolved"
        )

    from ..host_state import load_host_state
    from ..interaction_evidence import load_interaction_evidence
    from ..interaction_prediction import (
        evidence_only_unresolved_prediction,
        new_interaction_prediction,
        prediction_producer_from_dict,
        probability_estimate_from_dict,
        write_interaction_prediction,
    )
    from ..phage_profile import load_phage_profile

    try:
        state = load_host_state(args.host_state)
        profile = load_phage_profile(args.phage_profile)
        evidence = [
            load_interaction_evidence(path)
            for path in args.interaction_evidence
        ]

        if args.evidence_only_unresolved:
            prediction = evidence_only_unresolved_prediction(
                state,
                profile,
                evidence,
                prediction_id=args.prediction_id,
                revision=args.prediction_revision,
                predicted_at=args.predicted_at,
            )
        else:
            payload = _load_json(args.prediction_input, "Prediction input")
            if not isinstance(payload, dict) or set(payload) != {
                "probabilities",
                "mechanistic_explanation",
                "limitations",
                "producer",
            }:
                raise ValueError(
                    "Prediction input must contain exactly probabilities, "
                    "mechanistic_explanation, limitations and producer."
                )
            probabilities = payload["probabilities"]
            if not isinstance(probabilities, dict) or set(probabilities) != {
                "adsorption",
                "productive_infection",
                "resistance_emergence",
            }:
                raise ValueError(
                    "Prediction input probabilities must contain exactly "
                    "adsorption, productive_infection and resistance_emergence."
                )
            if not isinstance(payload["limitations"], list):
                raise ValueError("Prediction input limitations must be an array.")
            prediction = new_interaction_prediction(
                state,
                profile,
                evidence,
                prediction_id=args.prediction_id,
                revision=args.prediction_revision,
                adsorption=probability_estimate_from_dict(
                    probabilities["adsorption"]
                ),
                productive_infection=probability_estimate_from_dict(
                    probabilities["productive_infection"]
                ),
                resistance_emergence=probability_estimate_from_dict(
                    probabilities["resistance_emergence"]
                ),
                mechanistic_explanation=payload["mechanistic_explanation"],
                limitations=tuple(payload["limitations"]),
                producer=prediction_producer_from_dict(payload["producer"]),
                predicted_at=args.predicted_at,
            )
        write_interaction_prediction(prediction, args.out)
    except (OSError, ValueError) as exc:
        print(f"InteractionPrediction 创建失败：{exc}", file=sys.stderr)
        return 2

    estimated = [
        name
        for name, estimate in (
            ("adsorption", prediction.adsorption),
            ("productive_infection", prediction.productive_infection),
            ("resistance_emergence", prediction.resistance_emergence),
        )
        if estimate.status == "estimated"
    ]
    print(
        f"InteractionPrediction {prediction.record_id}："
        f"{prediction.host_state.record_id} × {prediction.phage_profile_id} → {args.out}",
        flush=True,
    )
    print(
        "estimated targets: "
        + (", ".join(estimated) if estimated else "none"),
        file=sys.stderr,
    )
    return 0


def _recommend_phages(args, parser) -> int:
    """Select screening candidates from exact HostState-bound predictions."""
    required = (
        ("--host-state", args.host_state),
        ("--phage-profiles", args.phage_profiles),
        ("--candidate-set-id", args.candidate_set_id),
        ("--out", args.out),
    )
    missing = [name for name, value in required if not value]
    if missing:
        parser.error("recommend-phages requires " + ", ".join(missing))
    from ..host_state import load_host_state
    from ..interaction_prediction import load_interaction_prediction
    from ..natural_phage_recommender import (
        RecommendationPolicy, recommend_natural_phages, write_candidate_set,
    )
    from ..phage_profile import phage_profile_from_dict

    try:
        payload = _load_json(args.phage_profiles, "PhageProfile")
        if not isinstance(payload, list):
            raise ValueError("PhageProfile file must contain a JSON array.")
        candidate_set = recommend_natural_phages(
            load_host_state(args.host_state),
            [phage_profile_from_dict(item) for item in payload],
            [load_interaction_prediction(path) for path in args.interaction_prediction],
            candidate_set_id=args.candidate_set_id,
            policy=RecommendationPolicy(args.max_candidates, args.exploration_slots),
            revision=args.candidate_set_revision,
            created_at=args.recommended_at,
        )
        write_candidate_set(candidate_set, args.out)
    except (OSError, ValueError) as exc:
        print(f"CandidateSet 创建失败：{exc}", file=sys.stderr)
        return 2
    selected = [e for e in candidate_set.evaluations if e.disposition == "selected"]
    exploration = sum(e.basis == "exploration" for e in selected)
    print(
        f"CandidateSet {candidate_set.record_id}：{len(selected)} 个入选 "
        f"({exploration} 个 exploration) / {len(candidate_set.evaluations)} 个输入 → {args.out}",
        flush=True,
    )
    print("这是待测试候选集合；选择原因与未解决限制保留在 artifact 中。", file=sys.stderr)
    return 0


def _phage_profiles(args, parser) -> int:
    """Convert sourced candidate records into retrieved PhageProfile records."""

    missing = [name for name, value in (("--candidates", args.candidates), ("--out", args.out))
               if not value]
    if missing:
        parser.error("phage-profiles requires " + ", ".join(missing))
    from ..phage_profile import retrieved_candidate_to_phage_profile
    try:
        candidates = _load_candidates(args.candidates)
        profiles = [
            retrieved_candidate_to_phage_profile(candidate).to_dict()
            for candidate in candidates
        ]
        args.out.write_text(
            json.dumps(profiles, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError) as exc:
        print(f"PhageProfile 转换失败：{exc}", file=sys.stderr)
        return 2
    print(f"{len(profiles)} 个 PhageProfile → {args.out}", flush=True)
    print(
        "retrieved provenance 只表示外部记录来源；不会自动声明 biological origin。",
        file=sys.stderr,
    )
    return 0


def _cocktail_design(args, parser) -> int:
    """Create a conservative, evidence-linked CocktailDesign."""

    required = (
        ("--host-profile", args.host_profile),
        ("--phage-profiles", args.phage_profiles),
        ("--candidates", args.candidates),
        ("--cocktail-id", args.cocktail_id),
        ("--out", args.out),
    )
    missing = [name for name, value in required if not value]
    if missing:
        parser.error("cocktail-design requires " + ", ".join(missing))
    if not 2 <= args.cocktail_min <= args.cocktail_max:
        parser.error("cocktail-design requires 2 <= --cocktail-min <= --cocktail-max")

    from ..cocktail_design import phist_screening_design, write_cocktail_design
    from ..host_profile import load_host_profile
    from ..phage_profile import phage_profile_from_dict

    try:
        host = load_host_profile(args.host_profile)
        profile_payload = _load_json(args.phage_profiles, "PhageProfile")
        if not isinstance(profile_payload, list):
            raise ValueError("PhageProfile file must contain a JSON array.")
        profiles = [phage_profile_from_dict(item) for item in profile_payload]
        candidates = _load_candidates(args.candidates)
        design = phist_screening_design(
            host,
            profiles,
            candidates,
            cocktail_id=args.cocktail_id,
            min_members=args.cocktail_min,
            max_members=args.cocktail_max,
        )
        write_cocktail_design(design, args.out)
    except (OSError, ValueError) as exc:
        print(f"CocktailDesign 创建失败：{exc}", file=sys.stderr)
        return 2

    print(
        f"CocktailDesign {design.design_id}：{len(design.members)} 个成员 → {args.out}",
        flush=True,
    )
    print(
        "这是 PHIST-supported screening baseline，不是疗效或机制优化结论；"
        "未解决证据缺口已写入 design。",
        file=sys.stderr,
    )
    return 0

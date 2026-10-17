"""Command-line entry point for snapshots, candidate retrieval and orchestration."""

import argparse
import asyncio
import json
from pathlib import Path
import sys

from .workflow import (
    DEFAULT_SELECTION_SIZE,
    EXECUTION_MODES,
    STANDARD_WORKFLOW,
    WorkflowError,
    run_experiment,
)

MAX_INPUT_BYTES = 4_000_000
COMMANDS = (
    "run",
    "host-profile",
    "host-state",
    "interaction-prediction",
    "recommend-phages",
    "active-learn",
    "phage-profiles",
    "cocktail-design",
    "experiment-spec",
    "material-batch",
    "measurement",
    "phenotype",
    "phenotype-comparison",
    "failure-attribution",
    "fetch-snapshot",
    "candidates",
    "rank",
    "version",
)


def _load_json(path: Path, label: str):
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError(f"{label} file exceeds the {MAX_INPUT_BYTES // 1_000_000} MB limit.")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError(f"{label} file is not valid JSON: {exc}") from None


def _load_candidates(path: Path) -> list[dict]:
    """Load candidate records someone already retrieved.

    Provenance in such a file is only as honest as its author. Records produced
    by `candidates` carry snapshot fields, and `run --require-snapshot` insists
    on them.
    """
    data = _load_json(path, "Candidate")
    if not isinstance(data, list):
        raise ValueError("Candidate file must contain a JSON array of candidate records.")
    return data


def _load_material_batches(path: Path) -> list:
    from .material_batch import material_batch_from_dict

    data = _load_json(path, "MaterialBatch")
    if not isinstance(data, list):
        raise ValueError("MaterialBatch file must contain a JSON array.")
    return [material_batch_from_dict(item) for item in data]


def _load_measurements(path: Path) -> list:
    from .measurement import measurement_from_dict

    data = _load_json(path, "Measurement")
    records = data if isinstance(data, list) else [data]
    return [measurement_from_dict(item) for item in records]


def _load_workflow(path: Path | None) -> dict:
    if path is None:
        return dict(STANDARD_WORKFLOW)
    data = _load_json(path, "Workflow")
    if not isinstance(data, dict):
        raise ValueError("Workflow file must contain a JSON object of operation -> dependencies.")
    return {key: tuple(value) if isinstance(value, list) else value for key, value in data.items()}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Closed-loop phage R&D tools and laboratory orchestration.")
    parser.add_argument("command", nargs="?", default="run", choices=COMMANDS)

    parser.add_argument("--genome", type=Path,
                        default=Path(__file__).resolve().parent.parent / "examples" / "toy_genome.fasta",
                        help="Host bacterial FASTA; only a hash and summary are retained.")
    parser.add_argument("--candidates", type=Path,
                        help="JSON array of candidate records retrieved earlier.")
    parser.add_argument("--snapshot", type=Path,
                        help="Snapshot directory to retrieve candidates from.")
    parser.add_argument("--host", help="Host organism to search the snapshot for.")
    parser.add_argument("--limit", type=int, default=20, help="Maximum candidates to retrieve.")
    parser.add_argument("--out", type=Path, help="Write the command output artifact here.")
    parser.add_argument("--execution-mode", choices=EXECUTION_MODES,
                        help="Required for a run. No default: state which hardware you expect.")
    parser.add_argument("--require-snapshot", action="store_true",
                        help="Refuse candidates that do not name a pinned snapshot.")
    parser.add_argument("--sample-id", help="Caller-owned sample identifier.")
    parser.add_argument("--workflow", type=Path,
                        help="JSON object of operation -> dependency list. Defaults to the standard pipeline.")
    parser.add_argument("--agent", choices=["rule", "openrouter"], default="rule")
    parser.add_argument("--select-min", type=int, default=DEFAULT_SELECTION_SIZE[0],
                        help="Fewest candidates a plan may select.")
    parser.add_argument("--select-max", type=int, default=DEFAULT_SELECTION_SIZE[1],
                        help="Most candidates a plan may select.")
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--output-dir", type=Path, default=Path("runs"))
    parser.add_argument("--quiet", action="store_true",
                        help="Do not echo the event stream; it is still written to events.jsonl.")

    parser.add_argument("--sequences", type=Path,
                        help="Genome FASTA snapshot directory, for tools that need sequences.")
    parser.add_argument("--host-genome", type=Path,
                        help="Host bacterial FASTA to rank candidates against.")
    parser.add_argument("--host-profile", type=Path,
                        help="HostProfile JSON used to bind scientific artifacts.")
    parser.add_argument("--host-state-id",
                        help="Caller-owned identifier for a HostState H(t) series.")
    parser.add_argument("--host-state-revision", type=int, default=1,
                        help="Positive HostState revision; defaults to 1.")
    parser.add_argument("--as-of",
                        help="ISO-8601 time represented by HostState H(t).")
    parser.add_argument("--state-input", type=Path,
                        help="Optional JSON object with components/evidence/limitations.")
    parser.add_argument("--previous-host-state", type=Path,
                        help="Optional previous HostState snapshot for temporal lineage.")
    parser.add_argument("--host-state", type=Path,
                        help="Exact HostState H(t) JSON used for InteractionPrediction.")
    parser.add_argument("--phage-profile", type=Path,
                        help="Exact PhageProfile JSON used for InteractionPrediction.")
    parser.add_argument("--interaction-evidence", action="append", type=Path, default=[],
                        help="Supporting InteractionEvidence JSON; repeat as needed.")
    parser.add_argument("--prediction-id",
                        help="Caller-owned InteractionPrediction identifier.")
    parser.add_argument("--prediction-revision", type=int, default=1,
                        help="Positive InteractionPrediction revision; defaults to 1.")
    parser.add_argument("--prediction-input", type=Path,
                        help="Model-output JSON with probabilities, explanation, limitations and producer.")
    parser.add_argument("--evidence-only-unresolved", action="store_true",
                        help="Emit an explicit not_estimated prediction without inventing probabilities.")
    parser.add_argument("--predicted-at",
                        help="Optional ISO-8601 prediction time; defaults to now.")
    parser.add_argument("--phage-profiles", type=Path,
                        help="JSON array of PhageProfile records.")
    parser.add_argument("--interaction-prediction", action="append", type=Path, default=[],
                        help="Exact InteractionPrediction JSON for recommend-phages; repeat per phage.")
    parser.add_argument("--candidate-set-id", help="Caller-owned CandidateSet identifier.")
    parser.add_argument("--candidate-set-revision", type=int, default=1)
    parser.add_argument("--max-candidates", type=int, default=3,
                        help="Screening budget for recommend-phages; defaults to 3.")
    parser.add_argument("--exploration-slots", type=int, default=1,
                        help="Slots reserved for unresolved predictions; defaults to 1.")
    parser.add_argument("--recommended-at",
                        help="Optional ISO-8601 CandidateSet creation time; defaults to now.")
    parser.add_argument("--candidate-set", type=Path,
                        help="CandidateSet source for independent single-phage experimental arms.")
    parser.add_argument("--failure-attribution", type=Path, action="append", default=[],
                        help="Admitted feedback for active-learn; repeat for each reviewed arm.")
    parser.add_argument("--screening-criterion", help="Exact declared criterion for feedback screening.")
    parser.add_argument("--decision-id", help="Caller-owned ActiveLearningDecision identifier.")
    parser.add_argument("--decision-revision", type=int, default=1)
    parser.add_argument("--decision-at", help="Optional ISO-8601 decision creation time.")
    parser.add_argument("--previous-decision", type=Path,
                        help="Carry all feedback from this exact campaign decision forward.")
    parser.add_argument("--active-learning-decision", type=Path,
                        help="Feedback decision source for an ExperimentSpec in the fixed assay context.")
    parser.add_argument("--expected-readout", action="append", default=[],
                        help="Declared readout for CandidateSet-derived arms; repeat as needed.")
    parser.add_argument("--conditions", type=Path,
                        help="Optional JSON object of common conditions for CandidateSet-derived arms.")
    parser.add_argument("--cocktail-id",
                        help="Caller-owned identifier for a CocktailDesign.")
    parser.add_argument("--cocktail-design", type=Path,
                        help="Optional CocktailDesign source for an ExperimentSpec.")
    parser.add_argument("--arms", type=Path,
                        help="JSON array of ExperimentArm records for a generic ExperimentSpec.")
    parser.add_argument("--objective",
                        help="Scientific objective for a generic arm-based ExperimentSpec.")
    parser.add_argument("--scientific-question", action="append", default=[],
                        help="Scientific question for ExperimentSpec; repeat as needed.")
    parser.add_argument("--execution-constraint", action="append", default=[],
                        help="Additional generic ExperimentSpec constraint; repeat as needed.")
    parser.add_argument("--experiment-id",
                        help="Caller-owned identifier for an ExperimentSpec.")
    parser.add_argument("--experiment-spec", type=Path,
                        help="ExperimentSpec JSON that locks scientific membership for run.")
    parser.add_argument("--material-batches", type=Path,
                        help="JSON array of MaterialBatch records for an ExperimentSpec-bound run.")
    parser.add_argument("--batch-id", help="Caller-owned physical material batch identifier.")
    parser.add_argument("--material-type", choices=["host", "phage"])
    parser.add_argument("--profile-id", help="HostProfile or PhageProfile ID represented by a batch.")
    parser.add_argument("--material-source-kind",
                        choices=["acquired", "local_collection", "built"])
    parser.add_argument("--material-source-reference",
                        help="LIMS/order/build/source reference for a physical material batch.")
    parser.add_argument("--quality-status",
                        choices=["pending", "released", "rejected"], default="pending")
    parser.add_argument("--availability-status",
                        choices=["available", "reserved", "consumed", "unavailable"],
                        default="available")
    parser.add_argument("--quality-evidence", action="append", default=[],
                        help="Quality/QC record reference; repeat for multiple references.")

    parser.add_argument("--run-report", type=Path,
                        help="Completed report.json to ingest as Measurement.")
    parser.add_argument("--measurement-id", help="Caller-owned Measurement identifier.")
    parser.add_argument("--arm-id",
                        help="ExperimentArm ID for arm-scoped Measurement/Phenotype.")
    parser.add_argument("--step", default="measure",
                        help="Completed run step to ingest; defaults to measure.")
    parser.add_argument("--measurement-type", default="device_result",
                        help="Semantic label for the ingested device output.")
    parser.add_argument("--qc-status", choices=["pending", "valid", "invalid"],
                        default="pending",
                        help="QC admission state; never inferred from workflow success.")
    parser.add_argument("--qc-evidence", action="append", default=[],
                        help="QC record/reference; required for valid or invalid Measurement.")

    parser.add_argument("--measurements", type=Path,
                        help="Measurement JSON object or array used for Phenotype.")
    parser.add_argument("--phenotype-id", help="Caller-owned Phenotype identifier.")
    parser.add_argument("--phenotype-type", help="Phenotype semantic type.")
    parser.add_argument("--phenotype-outcome",
                        choices=["positive", "negative", "graded"])
    parser.add_argument("--phenotype-value",
                        help="Optional scalar value; required for graded outcome.")
    parser.add_argument("--unit", help="Optional phenotype value unit.")
    parser.add_argument("--interpretation",
                        help="Explicit biological interpretation; no automatic thresholding.")
    parser.add_argument("--assessor", help="Assessor/model identity for Phenotype.")
    parser.add_argument("--assessor-version", default="1",
                        help="Assessor/model version.")
    parser.add_argument("--baseline-phenotype", type=Path,
                        help="Baseline arm Phenotype JSON for explicit comparison.")
    parser.add_argument("--comparator-phenotype", type=Path,
                        help="Comparator arm Phenotype JSON for explicit comparison.")
    parser.add_argument("--comparison-id",
                        help="Caller-owned PhenotypeComparison identifier.")
    parser.add_argument("--comparison-type",
                        help="Semantic type of an explicit arm comparison.")
    parser.add_argument("--comparison-outcome",
                        help="Assessor-stated comparison outcome; not inferred.")
    parser.add_argument("--comparison-value",
                        help="Optional scalar effect/comparison value.")
    parser.add_argument("--phenotypes", action="append", type=Path, default=[],
                        help="Reviewed Phenotype JSON; repeat for all source arms/readouts.")
    parser.add_argument("--phenotype-comparison", action="append", type=Path, default=[],
                        help="Optional reviewed PhenotypeComparison JSON; repeat as needed.")
    parser.add_argument("--attribution-id", help="Caller-owned FailureAttribution identifier.")
    parser.add_argument("--attribution-revision", type=int, default=1)
    parser.add_argument("--attribution-input", type=Path,
                        help="Explicit review JSON: outcome, criterion, interpretation, limitations, hypotheses.")

    parser.add_argument("--cocktail-min", type=int, default=2,
                        help="Minimum PHIST-supported members for cocktail-design.")
    parser.add_argument("--cocktail-max", type=int, default=3,
                        help="Maximum members for cocktail-design.")
    parser.add_argument("--ranker", choices=["phist"], default="phist")
    parser.add_argument("--phist", type=Path,
                        help="Path to phist.py. Falls back to PHIST_PATH, then PATH.")
    parser.add_argument("--k", type=int, default=25, help="k-mer length for PHIST.")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--only-ranked", action="store_true",
                        help="Drop candidates the tool did not report.")

    parser.add_argument("--source", default="inphared", help="Snapshot source name.")
    parser.add_argument("--version", dest="snapshot_version",
                        help="Upstream release identifier, e.g. 1Oct2026.")
    parser.add_argument("--url", help="https URL to download the snapshot from.")
    parser.add_argument("--from-file", type=Path,
                        help="Use a file already on disk instead of downloading.")
    parser.add_argument("--source-uri", help="Where the data came from upstream.")
    parser.add_argument("--skip-verify", action="store_true",
                        help="Skip re-hashing a large snapshot on load.")
    return parser



def _host_profile(args, parser) -> int:
    """Create the first version of a host record without inventing annotations."""

    missing = [name for name, value in (("--sample-id", args.sample_id), ("--out", args.out))
               if not value]
    if missing:
        parser.error("host-profile requires " + ", ".join(missing))
    from .biology import read_fasta
    from .host_profile import new_host_profile, write_host_profile
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

    from .host_profile import load_host_profile
    from .host_state import (
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

    from .host_state import load_host_state
    from .interaction_evidence import load_interaction_evidence
    from .interaction_prediction import (
        evidence_only_unresolved_prediction,
        new_interaction_prediction,
        prediction_producer_from_dict,
        probability_estimate_from_dict,
        write_interaction_prediction,
    )
    from .phage_profile import load_phage_profile

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
    from .host_state import load_host_state
    from .interaction_prediction import load_interaction_prediction
    from .natural_phage_recommender import (
        RecommendationPolicy, recommend_natural_phages, write_candidate_set,
    )
    from .phage_profile import phage_profile_from_dict

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
    from .phage_profile import retrieved_candidate_to_phage_profile
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

    from .cocktail_design import phist_screening_design, write_cocktail_design
    from .host_profile import load_host_profile
    from .phage_profile import phage_profile_from_dict

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
            "experiment-spec requires exactly one of --cocktail-design, --arms, --candidate-set or --active-learning-decision"
        )
    if args.active_learning_decision and any((args.objective, args.workflow, args.conditions,
                                              args.expected_readout, args.scientific_question,
                                              args.execution_constraint)):
        parser.error("Active-learning experiments preserve the recorded context; omit context overrides")
    if (args.arms or args.candidate_set) and not args.objective:
        parser.error("experiment-spec with --arms or --candidate-set requires --objective")
    if args.candidate_set and not args.expected_readout:
        parser.error("experiment-spec with --candidate-set requires --expected-readout")

    from .experiment_spec import (
        experiment_arm_from_dict,
        experiment_spec_from_arms,
        experiment_spec_from_cocktail,
        write_experiment_spec,
    )

    try:
        workflow = _load_workflow(args.workflow)
        if args.active_learning_decision:
            from .active_learning import (
                experiment_spec_from_active_learning, load_active_learning_decision,
            )
            spec = experiment_spec_from_active_learning(
                load_active_learning_decision(args.active_learning_decision),
                experiment_id=args.experiment_id,
            )
        elif args.cocktail_design:
            from .cocktail_design import load_cocktail_design

            design = load_cocktail_design(args.cocktail_design)
            spec = experiment_spec_from_cocktail(
                design,
                experiment_id=args.experiment_id,
                workflow=workflow,
                purpose=args.objective,
            )
        elif args.candidate_set:
            from .natural_phage_recommender import (
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

    from .experiment_spec import load_experiment_spec
    from .phenotype import (
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


def _active_learn(args, parser) -> int:
    missing = [name for name, value in (
        ("--candidate-set", args.candidate_set), ("--experiment-spec", args.experiment_spec),
        ("--screening-criterion", args.screening_criterion), ("--decision-id", args.decision_id),
        ("--out", args.out),
    ) if not value]
    if missing:
        parser.error("active-learn requires " + ", ".join(missing))
    from .active_learning import (
        plan_next_screen, load_active_learning_decision, write_active_learning_decision,
    )
    from .experiment_spec import load_experiment_spec
    from .failure_attribution import load_failure_attribution
    from .natural_phage_recommender import load_candidate_set
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


def _failure_attribution(args, parser) -> int:
    missing = [name for name, value in (
        ("--experiment-spec", args.experiment_spec), ("--arm-id", args.arm_id),
        ("--measurements", args.measurements), ("--phenotypes", args.phenotypes),
        ("--attribution-id", args.attribution_id), ("--attribution-input", args.attribution_input),
        ("--assessor", args.assessor), ("--out", args.out),
    ) if not value]
    if missing:
        parser.error("failure-attribution requires " + ", ".join(missing))

    from .experiment_spec import load_experiment_spec
    from .phenotype import phenotype_from_dict, phenotype_comparison_from_dict
    from .failure_attribution import (
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

    from .material_batch import new_material_batch, write_material_batch

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

    from .measurement import measurement_from_run_report, write_measurement

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

    from .experiment_spec import load_experiment_spec
    from .phenotype import phenotype_from_measurements, write_phenotype

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


def _fetch_snapshot(args, parser) -> int:
    from .snapshots import SnapshotError, create_snapshot
    missing = [name for name, value in (("--snapshot", args.snapshot),
                                        ("--version", args.snapshot_version))
               if not value]
    if missing:
        parser.error("fetch-snapshot requires " + ", ".join(missing))
    if bool(args.url) == bool(args.from_file):
        parser.error("fetch-snapshot requires exactly one of --url or --from-file")
    source_uri = args.source_uri or args.url
    if not source_uri:
        parser.error("fetch-snapshot with --from-file also requires --source-uri")
    try:
        snapshot = create_snapshot(args.snapshot, source=args.source,
                                   version=args.snapshot_version, source_uri=source_uri,
                                   url=args.url, from_file=args.from_file)
    except (SnapshotError, OSError) as exc:
        print(f"快照获取失败：{exc}", file=sys.stderr)
        return 2
    print(f"快照已记录：{args.snapshot}\n  来源 {snapshot.source} {snapshot.version}"
          f"\n  sha256 {snapshot.sha256}\n  {snapshot.bytes} bytes", flush=True)
    return 0


def _retrieve_candidates(args, parser) -> int:
    from .candidates import ProviderError, load_snapshot_dir
    from .snapshots import SnapshotError
    missing = [name for name, value in (("--snapshot", args.snapshot), ("--host", args.host))
               if not value]
    if missing:
        parser.error("candidates requires " + ", ".join(missing))
    try:
        provider = load_snapshot_dir(args.snapshot, verify=not args.skip_verify)
        records = provider.search(args.host, limit=args.limit)
    except (ProviderError, SnapshotError, OSError, ValueError) as exc:
        print(f"候选检索失败：{exc}", file=sys.stderr)
        return 2
    payload = json.dumps(records, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.write_text(payload, encoding="utf-8")
        print(f"{len(records)} 条候选 → {args.out}", flush=True)
    else:
        print(payload, end="")
    print("提示：host 字段是 depositor 的注释，不是实验测定的 host range。", file=sys.stderr)
    return 0


def _rank(args, parser) -> int:
    from .biology import read_fasta
    from .host_profile import load_host_profile
    from .ranking import RankingError, phist_from_environment
    from .sequences import SequenceError, SequenceStore
    from .snapshots import SnapshotError, load_snapshot

    missing = [name for name, value in (("--candidates", args.candidates),
                                        ("--sequences", args.sequences),
                                        ("--host-genome", args.host_genome)) if not value]
    if missing:
        parser.error("rank requires " + ", ".join(missing))
    try:
        candidates = _load_candidates(args.candidates)
        store = SequenceStore(load_snapshot(args.sequences, verify=not args.skip_verify))
        host_profile_id = None
        if args.host_profile:
            profile = load_host_profile(args.host_profile)
            genome = read_fasta(args.host_genome)
            if profile.genome.sha256 != genome.sha256:
                raise ValueError(
                    "HostProfile genome identity does not match --host-genome."
                )
            host_profile_id = profile.profile_id
        ranker = phist_from_environment(args.phist, k=args.k, threads=args.threads)
        print(f"{ranker.describe()['tool']} {ranker.describe()['tool_version']}："
              f"{len(candidates)} 个候选 vs {args.host_genome.name}", flush=True)
        ranked = ranker.rank(
            args.host_genome,
            candidates,
            store,
            host_profile_id=host_profile_id,
        )
    except (RankingError, SequenceError, SnapshotError, OSError, ValueError) as exc:
        print(f"排序失败：{exc}", file=sys.stderr)
        return 2

    reported = [record for record in ranked if record["ranking"]["reported"]]
    if args.only_ranked:
        ranked = reported
        if not ranked:
            print("没有候选被工具报告出显著匹配；没有可用的排序结果。", file=sys.stderr)
            return 2
    payload = json.dumps(ranked, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.write_text(payload, encoding="utf-8")
        print(f"{len(ranked)} 条 → {args.out}", flush=True)
    else:
        print(payload, end="")
    print(f"工具报告 {len(reported)} 条显著匹配，{len(ranked) - len(reported)} 条未报告。\n"
          f"统计量是 phage 与 host 基因组之间的共享 k-mer，不是感染成功概率；"
          f"未报告只代表没有这一信号，不代表不能感染。", file=sys.stderr)
    return 0


def _run(args, parser) -> int:
    spec_mode = args.experiment_spec is not None
    if spec_mode:
        if not args.candidates or args.snapshot:
            parser.error(
                "run --experiment-spec requires --candidates and does not accept --snapshot"
            )
        if args.workflow is not None:
            parser.error(
                "run --experiment-spec uses the workflow locked in the spec; omit --workflow"
            )
    elif bool(args.candidates) == bool(args.snapshot):
        parser.error("run requires exactly one of --candidates or --snapshot")
    if args.material_batches is not None and not spec_mode:
        parser.error("--material-batches requires --experiment-spec")

    missing = [
        name
        for name, value in (
            ("--execution-mode", args.execution_mode),
            ("--sample-id", args.sample_id),
        )
        if not value
    ]
    if not spec_mode and args.snapshot and not args.host:
        missing.append("--host")
    if missing:
        parser.error("run requires " + ", ".join(missing))
    if not 1 <= args.select_min <= args.select_max:
        parser.error("--select-min must be at least 1 and no greater than --select-max")

    from .agents import AgentError, OpenRouterAgent, RuleAgent
    from .candidates import ProviderError, load_snapshot_dir
    from .experiment_spec import load_experiment_spec
    from .snapshots import SnapshotError

    try:
        agent = RuleAgent() if args.agent == "rule" else OpenRouterAgent.from_environment()
        spec = load_experiment_spec(args.experiment_spec) if spec_mode else None
        material_batches = (
            _load_material_batches(args.material_batches)
            if args.material_batches is not None
            else None
        )
        if spec_mode:
            candidates = _load_candidates(args.candidates)
            workflow = spec.workflow_dict()
        elif args.snapshot:
            provider = load_snapshot_dir(args.snapshot, verify=not args.skip_verify)
            manifest = provider.describe()
            candidates = provider.search(args.host, limit=args.limit)
            print(
                f"候选来自 {manifest['provider']} 快照 {manifest['snapshot_version']}："
                f"{len(candidates)} 条",
                flush=True,
            )
            workflow = _load_workflow(args.workflow)
        else:
            candidates = _load_candidates(args.candidates)
            workflow = _load_workflow(args.workflow)
    except (AgentError, ProviderError, SnapshotError, OSError, ValueError) as exc:
        print(f"无法启动：{exc}", file=sys.stderr)
        return 2

    if args.execution_mode == "virtual_hardware":
        print(
            "VIRTUAL HARDWARE: 设备动作与读数由软件 twin 产生，不是湿实验证据。",
            flush=True,
        )

    try:
        report, directory = asyncio.run(
            run_experiment(
                args.genome,
                args.output_dir,
                sample_id=args.sample_id,
                candidates=candidates,
                devices=None,
                workflow=workflow,
                agent=agent,
                execution_mode=args.execution_mode,
                selection_size=(args.select_min, args.select_max),
                require_snapshot=args.require_snapshot,
                timeout_seconds=args.timeout_seconds,
                echo=not args.quiet,
                experiment_spec=spec,
                material_batches=material_batches,
            )
        )
    except WorkflowError as exc:
        print(f"运行被拒绝：{exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"无法启动或保存报告：{exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130

    print(
        f"\n流程状态：{report['status']}\n报告：{directory / 'report.md'}",
        flush=True,
    )
    return 0 if report["status"] == "succeeded" else 2


def main(argv=None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "version":
        from .provenance import source_identity
        print(json.dumps(source_identity(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "host-profile":
        return _host_profile(args, parser)
    if args.command == "host-state":
        return _host_state(args, parser)
    if args.command == "interaction-prediction":
        return _interaction_prediction(args, parser)
    if args.command == "recommend-phages":
        return _recommend_phages(args, parser)
    if args.command == "active-learn":
        return _active_learn(args, parser)
    if args.command == "phage-profiles":
        return _phage_profiles(args, parser)
    if args.command == "cocktail-design":
        return _cocktail_design(args, parser)
    if args.command == "experiment-spec":
        return _experiment_spec(args, parser)
    if args.command == "material-batch":
        return _material_batch(args, parser)
    if args.command == "measurement":
        return _measurement(args, parser)
    if args.command == "phenotype":
        return _phenotype(args, parser)
    if args.command == "phenotype-comparison":
        return _phenotype_comparison(args, parser)
    if args.command == "failure-attribution":
        return _failure_attribution(args, parser)
    if args.command == "fetch-snapshot":
        return _fetch_snapshot(args, parser)
    if args.command == "candidates":
        return _retrieve_candidates(args, parser)
    if args.command == "rank":
        return _rank(args, parser)
    return _run(args, parser)


if __name__ == "__main__":
    raise SystemExit(main())

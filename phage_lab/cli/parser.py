"""Command-specific argument parsers; unrelated options are errors."""

import argparse
from pathlib import Path

from ..workflow import DEFAULT_SELECTION_SIZE, EXECUTION_MODES
from .science import (
    _host_profile,
    _host_state,
    _interaction_prediction,
    _recommend_phages,
    _phage_profiles,
    _cocktail_design,
)
from .experiments import _experiment_spec, _active_learn
from .results import (
    _material_batch,
    _measurement,
    _phenotype,
    _phenotype_comparison,
    _failure_attribution,
    _learning_observation,
    _calibration_report,
)
from .reference import _fetch_snapshot, _retrieve_candidates, _rank
from .run import _run


def _add_shared(parser, *names):
    # Only cross-command options live here. Command-specific options stay below.
    if 'genome' in names:
        parser.add_argument("--genome", type=Path,
                            default=Path(__file__).resolve().parents[2] / "examples" / "toy_genome.fasta",
                            help="Host bacterial FASTA; only a hash and summary are retained.")
    if 'candidates' in names:
        parser.add_argument("--candidates", type=Path,
                            help="JSON array of candidate records retrieved earlier.")
    if 'snapshot' in names:
        parser.add_argument("--snapshot", type=Path,
                            help="Snapshot directory to retrieve candidates from.")
    if 'host' in names:
        parser.add_argument("--host", help="Host organism to search the snapshot for.")
    if 'limit' in names:
        parser.add_argument("--limit", type=int, default=20, help="Maximum candidates to retrieve.")
    if 'out' in names:
        parser.add_argument("--out", type=Path, help="Write the command output artifact here.")
    if 'sample_id' in names:
        parser.add_argument("--sample-id", help="Caller-owned sample identifier.")
    if 'workflow' in names:
        parser.add_argument("--workflow", type=Path,
                            help="JSON object of operation -> dependency list. Defaults to the standard pipeline.")
    if 'host_profile' in names:
        parser.add_argument("--host-profile", type=Path,
                            help="HostProfile JSON used to bind scientific artifacts.")
    if 'host_state' in names:
        parser.add_argument("--host-state", type=Path,
                            help="Exact HostState H(t) JSON used for InteractionPrediction.")
    if 'phage_profiles' in names:
        parser.add_argument("--phage-profiles", type=Path,
                            help="JSON array of PhageProfile records.")
    if 'candidate_set' in names:
        parser.add_argument("--candidate-set", type=Path,
                            help="CandidateSet source for independent single-phage experimental arms.")
    if 'experiment_spec' in names:
        parser.add_argument("--experiment-spec", type=Path,
                            help="ExperimentSpec JSON that locks scientific membership for run.")
    if 'arm_id' in names:
        parser.add_argument("--arm-id",
                            help="ExperimentArm ID for arm-scoped Measurement/Phenotype.")
    if 'measurements' in names:
        parser.add_argument("--measurements", type=Path,
                            help="Measurement JSON object or array used for Phenotype.")
    if 'unit' in names:
        parser.add_argument("--unit", help="Optional phenotype value unit.")
    if 'interpretation' in names:
        parser.add_argument("--interpretation",
                            help="Explicit biological interpretation; no automatic thresholding.")
    if 'assessor' in names:
        parser.add_argument("--assessor", help="Assessor/model identity for Phenotype.")
    if 'assessor_version' in names:
        parser.add_argument("--assessor-version", default="1",
                            help="Assessor/model version.")
    if 'skip_verify' in names:
        parser.add_argument("--skip-verify", action="store_true",
                            help="Skip re-hashing a large snapshot on load.")


def build_parser():
    parser = argparse.ArgumentParser(description="Closed-loop phage R&D tools and laboratory orchestration.", allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)

    from ..dashboard import dashboard
    sub = commands.add_parser('dashboard', allow_abbrev=False,
                              help="Offline clinical workflow presentation; synthetic data only.")
    sub.set_defaults(handler=dashboard, command_parser=sub)
    sub.add_argument('--port', type=int, default=8765)
    sub.add_argument('--no-browser', action='store_true')

    sub = commands.add_parser('run', allow_abbrev=False)
    sub.set_defaults(handler=_run, command_parser=sub)
    _add_shared(sub, 'genome', 'candidates', 'snapshot', 'host', 'limit', 'sample_id', 'workflow', 'experiment_spec', 'skip_verify')
    sub.add_argument("--execution-mode", choices=EXECUTION_MODES,
                        help="Required for a run. No default: state which hardware you expect.")
    sub.add_argument("--require-snapshot", action="store_true",
                        help="Refuse candidates that do not name a pinned snapshot.")
    sub.add_argument("--agent", choices=["rule", "openrouter"], default="rule")
    sub.add_argument("--select-min", type=int, default=DEFAULT_SELECTION_SIZE[0],
                        help="Fewest candidates a plan may select.")
    sub.add_argument("--select-max", type=int, default=DEFAULT_SELECTION_SIZE[1],
                        help="Most candidates a plan may select.")
    sub.add_argument("--timeout-seconds", type=float, default=60.0)
    sub.add_argument("--output-dir", type=Path, default=Path("runs"))
    sub.add_argument("--quiet", action="store_true",
                        help="Do not echo the event stream; it is still written to events.jsonl.")
    sub.add_argument("--material-batches", type=Path,
                        help="JSON array of MaterialBatch records for an ExperimentSpec-bound run.")

    sub = commands.add_parser('host-profile', allow_abbrev=False)
    sub.set_defaults(handler=_host_profile, command_parser=sub)
    _add_shared(sub, 'genome', 'out', 'sample_id')

    sub = commands.add_parser('host-state', allow_abbrev=False)
    sub.set_defaults(handler=_host_state, command_parser=sub)
    _add_shared(sub, 'out', 'host_profile')
    sub.add_argument("--host-state-id",
                        help="Caller-owned identifier for a HostState H(t) series.")
    sub.add_argument("--host-state-revision", type=int, default=1,
                        help="Positive HostState revision; defaults to 1.")
    sub.add_argument("--as-of",
                        help="ISO-8601 time represented by HostState H(t).")
    sub.add_argument("--state-input", type=Path,
                        help="Optional JSON object with components/evidence/limitations.")
    sub.add_argument("--previous-host-state", type=Path,
                        help="Optional previous HostState snapshot for temporal lineage.")

    sub = commands.add_parser('interaction-prediction', allow_abbrev=False)
    sub.set_defaults(handler=_interaction_prediction, command_parser=sub)
    _add_shared(sub, 'out', 'host_state')
    sub.add_argument("--phage-profile", type=Path,
                        help="Exact PhageProfile JSON used for InteractionPrediction.")
    sub.add_argument("--interaction-evidence", action="append", type=Path, default=[],
                        help="Supporting InteractionEvidence JSON; repeat as needed.")
    sub.add_argument("--prediction-id",
                        help="Caller-owned InteractionPrediction identifier.")
    sub.add_argument("--prediction-revision", type=int, default=1,
                        help="Positive InteractionPrediction revision; defaults to 1.")
    sub.add_argument("--prediction-input", type=Path,
                        help="Model-output JSON with probabilities, explanation, limitations and producer.")
    sub.add_argument("--evidence-only-unresolved", action="store_true",
                        help="Emit an explicit not_estimated prediction without inventing probabilities.")
    sub.add_argument("--predicted-at",
                        help="Optional ISO-8601 prediction time; defaults to now.")

    sub = commands.add_parser('recommend-phages', allow_abbrev=False)
    sub.set_defaults(handler=_recommend_phages, command_parser=sub)
    _add_shared(sub, 'out', 'host_state', 'phage_profiles')
    sub.add_argument("--interaction-prediction", action="append", type=Path, default=[],
                        help="Exact InteractionPrediction JSON for recommend-phages; repeat per phage.")
    sub.add_argument("--candidate-set-id", help="Caller-owned CandidateSet identifier.")
    sub.add_argument("--candidate-set-revision", type=int, default=1)
    sub.add_argument("--max-candidates", type=int, default=3,
                        help="Screening budget for recommend-phages; defaults to 3.")
    sub.add_argument("--exploration-slots", type=int, default=1,
                        help="Slots reserved for unresolved predictions; defaults to 1.")
    sub.add_argument("--recommended-at",
                        help="Optional ISO-8601 CandidateSet creation time; defaults to now.")

    sub = commands.add_parser('active-learn', allow_abbrev=False)
    sub.set_defaults(handler=_active_learn, command_parser=sub)
    _add_shared(sub, 'out', 'candidate_set', 'experiment_spec')
    sub.add_argument("--failure-attribution", type=Path, action="append", default=[],
                        help="Admitted feedback for active-learn; repeat for each reviewed arm.")
    sub.add_argument("--screening-criterion", help="Exact declared criterion for feedback screening.")
    sub.add_argument("--decision-id", help="Caller-owned ActiveLearningDecision identifier.")
    sub.add_argument("--decision-revision", type=int, default=1)
    sub.add_argument("--decision-at", help="Optional ISO-8601 decision creation time.")
    sub.add_argument("--previous-decision", type=Path,
                        help="Carry all feedback from this exact campaign decision forward.")

    sub = commands.add_parser('phage-profiles', allow_abbrev=False)
    sub.set_defaults(handler=_phage_profiles, command_parser=sub)
    _add_shared(sub, 'candidates', 'out')

    sub = commands.add_parser('cocktail-design', allow_abbrev=False)
    sub.set_defaults(handler=_cocktail_design, command_parser=sub)
    _add_shared(sub, 'candidates', 'out', 'host_profile', 'phage_profiles')
    sub.add_argument("--cocktail-id",
                        help="Caller-owned identifier for a CocktailDesign.")
    sub.add_argument("--cocktail-min", type=int, default=2,
                        help="Minimum PHIST-supported members for cocktail-design.")
    sub.add_argument("--cocktail-max", type=int, default=3,
                        help="Maximum members for cocktail-design.")

    sub = commands.add_parser('experiment-spec', allow_abbrev=False)
    sub.set_defaults(handler=_experiment_spec, command_parser=sub)
    _add_shared(sub, 'out', 'workflow', 'candidate_set')
    sub.add_argument("--active-learning-decision", type=Path,
                        help="Feedback decision source for an ExperimentSpec in the fixed assay context.")
    sub.add_argument("--expected-readout", action="append", default=[],
                        help="Declared readout for CandidateSet-derived arms; repeat as needed.")
    sub.add_argument("--conditions", type=Path,
                        help="Optional JSON object of common conditions for CandidateSet-derived arms.")
    sub.add_argument("--cocktail-design", type=Path,
                        help="Optional CocktailDesign source for an ExperimentSpec.")
    sub.add_argument("--arms", type=Path,
                        help="JSON array of ExperimentArm records for a generic ExperimentSpec.")
    sub.add_argument("--objective",
                        help="Scientific objective for a generic arm-based ExperimentSpec.")
    sub.add_argument("--scientific-question", action="append", default=[],
                        help="Scientific question for ExperimentSpec; repeat as needed.")
    sub.add_argument("--execution-constraint", action="append", default=[],
                        help="Additional generic ExperimentSpec constraint; repeat as needed.")
    sub.add_argument("--experiment-id",
                        help="Caller-owned identifier for an ExperimentSpec.")

    sub = commands.add_parser('material-batch', allow_abbrev=False)
    sub.set_defaults(handler=_material_batch, command_parser=sub)
    _add_shared(sub, 'out')
    sub.add_argument("--batch-id", help="Caller-owned physical material batch identifier.")
    sub.add_argument("--material-type", choices=["host", "phage"])
    sub.add_argument("--profile-id", help="HostProfile or PhageProfile ID represented by a batch.")
    sub.add_argument("--material-source-kind",
                        choices=["acquired", "local_collection", "built"])
    sub.add_argument("--material-source-reference",
                        help="LIMS/order/build/source reference for a physical material batch.")
    sub.add_argument("--quality-status",
                        choices=["pending", "released", "rejected"], default="pending")
    sub.add_argument("--availability-status",
                        choices=["available", "reserved", "consumed", "unavailable"],
                        default="available")
    sub.add_argument("--quality-evidence", action="append", default=[],
                        help="Quality/QC record reference; repeat for multiple references.")

    sub = commands.add_parser('measurement', allow_abbrev=False)
    sub.set_defaults(handler=_measurement, command_parser=sub)
    _add_shared(sub, 'out', 'arm_id')
    sub.add_argument("--run-report", type=Path,
                        help="Completed report.json to ingest as Measurement.")
    sub.add_argument("--measurement-id", help="Caller-owned Measurement identifier.")
    sub.add_argument("--step", default="measure",
                        help="Completed run step to ingest; defaults to measure.")
    sub.add_argument("--measurement-type", default="device_result",
                        help="Semantic label for the ingested device output.")
    sub.add_argument("--qc-status", choices=["pending", "valid", "invalid"],
                        default="pending",
                        help="QC admission state; never inferred from workflow success.")
    sub.add_argument("--qc-evidence", action="append", default=[],
                        help="QC record/reference; required for valid or invalid Measurement.")

    sub = commands.add_parser('phenotype', allow_abbrev=False)
    sub.set_defaults(handler=_phenotype, command_parser=sub)
    _add_shared(sub, 'out', 'experiment_spec', 'arm_id', 'measurements', 'unit', 'interpretation', 'assessor', 'assessor_version')
    sub.add_argument("--phenotype-id", help="Caller-owned Phenotype identifier.")
    sub.add_argument("--phenotype-type", help="Phenotype semantic type.")
    sub.add_argument("--phenotype-outcome",
                        choices=["positive", "negative", "graded"])
    sub.add_argument("--phenotype-value",
                        help="Optional scalar value; required for graded outcome.")

    sub = commands.add_parser('phenotype-comparison', allow_abbrev=False)
    sub.set_defaults(handler=_phenotype_comparison, command_parser=sub)
    _add_shared(sub, 'out', 'experiment_spec', 'unit', 'interpretation', 'assessor', 'assessor_version')
    sub.add_argument("--baseline-phenotype", type=Path,
                        help="Baseline arm Phenotype JSON for explicit comparison.")
    sub.add_argument("--comparator-phenotype", type=Path,
                        help="Comparator arm Phenotype JSON for explicit comparison.")
    sub.add_argument("--comparison-id",
                        help="Caller-owned PhenotypeComparison identifier.")
    sub.add_argument("--comparison-type",
                        help="Semantic type of an explicit arm comparison.")
    sub.add_argument("--comparison-outcome",
                        help="Assessor-stated comparison outcome; not inferred.")
    sub.add_argument("--comparison-value",
                        help="Optional scalar effect/comparison value.")

    sub = commands.add_parser('failure-attribution', allow_abbrev=False)
    sub.set_defaults(handler=_failure_attribution, command_parser=sub)
    _add_shared(sub, 'out', 'experiment_spec', 'arm_id', 'measurements', 'assessor', 'assessor_version')
    sub.add_argument("--phenotypes", action="append", type=Path, default=[],
                        help="Reviewed Phenotype JSON; repeat for all source arms/readouts.")
    sub.add_argument("--phenotype-comparison", action="append", type=Path, default=[],
                        help="Optional reviewed PhenotypeComparison JSON; repeat as needed.")
    sub.add_argument("--attribution-id", help="Caller-owned FailureAttribution identifier.")
    sub.add_argument("--attribution-revision", type=int, default=1)
    sub.add_argument("--attribution-input", type=Path,
                        help="Explicit review JSON: outcome, criterion, interpretation, limitations, hypotheses.")

    sub = commands.add_parser('learning-observation', allow_abbrev=False)
    sub.set_defaults(handler=_learning_observation, command_parser=sub)
    _add_shared(sub, 'out', 'experiment_spec', 'interpretation', 'assessor', 'assessor_version')
    sub.add_argument("--interaction-prediction", type=Path,
                        help="Exact InteractionPrediction JSON to compare with physical evidence.")
    sub.add_argument("--phenotype", type=Path,
                        help="Physical single-phage treatment Phenotype used for the explicit label.")
    sub.add_argument("--observation-id", help="Caller-owned LearningObservation identifier.")
    sub.add_argument("--target",
                        choices=["adsorption", "productive_infection", "resistance_emergence"],
                        help="InteractionPrediction target being explicitly labeled.")
    sub.add_argument("--observed", choices=["true", "false"],
                        help="Assessor-declared binary outcome; never inferred from Phenotype polarity.")
    sub.add_argument("--limitation", action="append", default=[],
                        help="Learning-label limitation; repeat as needed and provide at least one.")
    sub.add_argument("--assessed-at",
                        help="Optional ISO-8601 label assessment time; defaults to now.")

    sub = commands.add_parser('calibration-report', allow_abbrev=False)
    sub.set_defaults(handler=_calibration_report, command_parser=sub)
    _add_shared(sub, 'out')
    sub.add_argument("--learning-observation", action="append", type=Path, default=[],
                        help="Scorable LearningObservation JSON; repeat for one comparable cohort.")
    sub.add_argument("--report-id", help="Caller-owned CalibrationReport identifier.")
    sub.add_argument("--target",
                        choices=["adsorption", "productive_infection", "resistance_emergence"],
                        help="Prediction target scored by the report.")
    sub.add_argument("--created-at",
                        help="Optional ISO-8601 report creation time; defaults to now.")

    sub = commands.add_parser('fetch-snapshot', allow_abbrev=False)
    sub.set_defaults(handler=_fetch_snapshot, command_parser=sub)
    _add_shared(sub, 'snapshot')
    sub.add_argument("--source", default="inphared", help="Snapshot source name.")
    sub.add_argument("--version", dest="snapshot_version",
                        help="Upstream release identifier, e.g. 1Oct2026.")
    sub.add_argument("--url", help="https URL to download the snapshot from.")
    sub.add_argument("--from-file", type=Path,
                        help="Use a file already on disk instead of downloading.")
    sub.add_argument("--source-uri", help="Where the data came from upstream.")

    sub = commands.add_parser('candidates', allow_abbrev=False)
    sub.set_defaults(handler=_retrieve_candidates, command_parser=sub)
    _add_shared(sub, 'snapshot', 'host', 'limit', 'out', 'skip_verify')

    sub = commands.add_parser('rank', allow_abbrev=False)
    sub.add_argument('--ranker', choices=['phist'], default='phist')
    sub.set_defaults(handler=_rank, command_parser=sub)
    _add_shared(sub, 'candidates', 'out', 'host_profile', 'skip_verify')
    sub.add_argument("--sequences", type=Path,
                        help="Genome FASTA snapshot directory, for tools that need sequences.")
    sub.add_argument("--host-genome", type=Path,
                        help="Host bacterial FASTA to rank candidates against.")
    sub.add_argument("--phist", type=Path,
                        help="Path to phist.py. Falls back to PHIST_PATH, then PATH.")
    sub.add_argument("--k", type=int, default=25, help="k-mer length for PHIST.")
    sub.add_argument("--threads", type=int, default=2)
    sub.add_argument("--only-ranked", action="store_true",
                        help="Drop candidates the tool did not report.")

    sub = commands.add_parser("version", allow_abbrev=False)
    sub.set_defaults(handler=_version, command_parser=sub)
    return parser


def _version(args, parser):
    import json
    from ..provenance import source_identity
    print(json.dumps(source_identity(), ensure_ascii=False, indent=2))
    return 0

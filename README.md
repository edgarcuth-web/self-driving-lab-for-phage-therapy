# SELF-DRIVING PHAGE THERAPY
### Observe → Model → Design → Test → Learn → Adapt

A research software system for traceable phage characterization, screening,
experimental intent, execution records, result review and next-round selection.

The long-term goal is an autonomous phage R&D loop that improves predictions and
decisions using experimental evidence. The current software records explicit
learning labels and supports feedback screening; model retraining, calibration
and release remain separate, reviewed model-side actions.

Engineering is an escalation path — not the default. The fast path evaluates
existing natural phages and cocktails first; engineering requires an explicit
evidence gap. Mechanistic attribution should guide the engineering hypothesis
when the available evidence can support it.

## System overview

```text
                         SCIENTIFIC CONTROL
                                │
                                ▼
Host / phage evidence → OBSERVE → MODEL → DESIGN → TEST → LEARN → ADAPT
                          ▲                                      │
                          └──────────────────────────────────────┘

experimental failure / ambiguity
        │
        ▼
mechanism attribution
        │
        ▼
engineering escalation
        │
        └────────────────────────────────────────► DESIGN
```

The architecture is intentionally split into separate views rather than one
all-encompassing diagram. See [architecture](docs/architecture.md) for the
scientific control plane, decision/model layer, experimental loop, engineering
escalation path, and stable domain contracts.

## Current implementation status

The current implementation is a **feedback-driven screening software loop**:
it records inputs and predictions, produces frozen experimental intent, ingests
QC-admitted results, creates explicit prediction-vs-outcome learning records, and
selects the next unresolved screening question. Biological characterization also
belongs in this repository; the first real analyzer is PADLOC. Model-specific
embeddings, training, calibration and inference live in the separate
`phage-host-interaction-predictor` repository.

The first scientific-control vertical slice now lives in
`phage_lab/scientific_control/`. A deterministic `ScientificOrchestrator` invokes
only the explicitly registered natural-phage recommender and records exact module,
input and output lineage. An independent `ScientificReviewer` checks lineage,
missing/unresolved evidence and unsupported semantic upgrades before approving a
screening proposal. This slice does not create, mutate or execute an
`ExperimentSpec`, and it has no workflow/device dependency. See
[scientific control](docs/scientific-control.md).

The first model exchange uses **ModelInputBundle v1 → PairPrediction v1**:
SDL exports complete pair snapshots, explicit source-label/context semantics and
selected local sequence/annotation payloads; model-side consumers verify actual
bytes. This implements exchange and abstention, not trained inference. Source
scores cannot enter the existing productive-infection screening policy by renaming
fields. See [model boundary](docs/model-interface.md).

The current external host baseline predicts audited source-coded `MLC > 0` and
returns uncalibrated research scores. It is not served through this bundle path
or admitted to SDL candidate decisions. Source positivity, clearing, plaque
formation, productive infection and growth suppression are distinct endpoints;
see [endpoint semantics](docs/endpoint-semantics.md).

| Part | Implemented | Current limit |
| --- | --- | --- |
| Inputs and evidence | HostProfile, HostState, PhageProfile, reference snapshots, PHIST evidence | Unassessed features remain unknown; PHIST is not an infection probability |
| Scientific control | ScientificObjective, ScientificPlan/Task, trusted PADLOC characterization + ModelRequest handoffs, ScientificProposal, ScientificReview | Unknown host-defense characterization gates pair planning; PADLOC output still requires explicit HostProfile admission and no wet-lab execution is implied |
| Scientific decision | InteractionPrediction contract, CandidateSet, PHIST cocktail baseline | Unresolved predictions remain unresolved; no validated efficacy optimizer yet |
| Experiment design | ExperimentSpec v2, control/treatment arms, MaterialBatch binding | Records intent and material provenance; does not define experimental methods for the user |
| Execution | Scheduling, logs, timeout reconciliation, cancellation/recovery, virtual device, HTTP adapter example | CLI has no configured real driver by default; virtual hardware produces no biological evidence |
| Feedback and learning | Measurement, Phenotype, Comparison, FailureAttribution, LearningObservation, CalibrationReport, next-round selection | Labels must be explicit; calibration is descriptive and does not train a model or update H(t) |

Current software path:

```text
ScientificObjective
  → ScientificOrchestrator → ScientificPlan
  ├→ host defense unknown
  │    → trusted PADLOC → FeatureArtifact → explicit admission required
  ├→ missing pair after characterization
  │    → exact ModelRequest handoff
  └→ explicit pair states complete
       → trusted natural-phage recommender
       → CandidateSet → ScientificProposal → ScientificReviewer

HostState + PhageProfile + InteractionEvidence
  → InteractionPrediction → CandidateSet
  → ExperimentSpec → execution + MaterialBatch
  → Measurement → Phenotype / Comparison → FailureAttribution
  ├→ LearningObservation → CalibrationReport
  └→ feedback-screening decision → next ExperimentSpec
```

`CocktailDesign` is another possible source of an ExperimentSpec; single-phage
screening does not need to form a cocktail first.

## Local checks

### Core CLI

Python 3.11+ is required. Core orchestration uses the standard library; sequence
registration and FeatureArtifact validation require `jsonschema`, and real PADLOC
analysis uses the pinned external environment in `envs/padloc.yml`.

From the repository root:

```bash
python -m phage_lab version
python -m unittest discover -s tests -v
```

The following only checks file flow with the repository's toy FASTA. It does not
execute devices or generate experimental results:

```bash
python -m phage_lab host-profile \
  --genome examples/toy_genome.fasta \
  --sample-id local-check --out local-data/local-check/host-profile.json

python -m phage_lab host-state \
  --host-profile local-data/local-check/host-profile.json \
  --host-state-id local-check-state \
  --as-of 2026-10-16T12:00:00+00:00 \
  --out local-data/local-check/host-state.json
```

The generated profile has no assessed biological features; an empty HostState is
not a biological negative.

## Real biological characterization: PADLOC

This repository owns sequence-resource registration, FeatureArtifact v1 and the
first real analyzer, PADLOC v2.0.0. It runs actual analysis against registered
FASTA that matches the HostState genome fingerprint, pins PADLOC-DB v2.0.0, and
records native outputs, logs, database-tree fingerprints and provenance.

No hit means only that no system was detected within that database and run scope;
it does not prove the bacterium has no defense systems. Current results are not
automatically promoted into an assessed-negative HostProfile. Installation,
execution and limitations are documented in
[`docs/padloc-adapter.md`](docs/padloc-adapter.md).

```bash
conda env create -f envs/padloc.yml
conda activate phage-padloc
python -m phage_lab annotate-host-defense-padloc --help
```

Across the repository boundary, SDL exports a frozen ModelInputBundle containing
approved scientific annotations, screening state and provenance. The predictor
repository owns only model-specific representations, training, evaluation,
weights, calibration and inference.

ModelInputBundle v1 supports complete snapshots, explicit endpoint/context,
readable local sequences and annotation outputs. PairPrediction v1 binds the whole
input bundle. Legacy ModelRequest/ModelResult v1 remains available for the existing
mechanistic targets; the two paths do not convert automatically. There is currently
no trained, calibrated inference implementation in this repository.

## Presentation-only clinical workflow

The repository also contains a browser presentation used to demonstrate workflow
concepts with synthetic data. It is intentionally separate from the scientific
loop: it does not call the real scientific modules, create biological evidence, or
represent clinical recommendations.

Run it with:

```bash
python -m phage_lab dashboard
```

On Windows, `start-dashboard.bat` can be launched directly. Open
`http://127.0.0.1:8765`; use `--port 8766` if needed, or `--no-browser` to
avoid automatic browser opening.

The presentation shows a synthetic path from patient sampling through metadata,
simulated isolate detection, parallel phage/antibiotic matching, simulated phage
preparation, and the screening/experiment/feedback concepts implemented by the
main project. Sample cases, timings, DNA fragments, candidate identifiers and
detection scores are synthetic demonstration fixtures, not validated clinical or
biological results.

The optional Kimi K3 report feature drafts a clinical-format narrative from the
synthetic terminal snapshot. The API key stays in process memory; raw FASTA is not
sent. Generated text is a draft requiring review, not a scientific domain artifact,
diagnosis, prescription or efficacy claim.

Presentation checks:

```bash
python -m unittest discover -s tests -p test_dashboard.py -v
node --test tests/test_dashboard_model.cjs
node --test tests/test_presentation.cjs
python -m unittest discover -s tests -p test_clinical_reports.py -v
sh scripts/smoke.sh
```

Node 18+ is required only for the JavaScript presentation tests.

## Usage and development

- [CLI guide](docs/usage.md): commands, inputs and later-round workflows.
- [Architecture and domain contracts](docs/architecture.md): system planes, object relationships, evidence semantics and validation boundaries.
- [Scientific control](docs/scientific-control.md): the first bounded orchestrator/reviewer slice and its hard execution boundary.
- [External model interface](docs/model-interface.md): versioned JSON boundary with `phage-host-interaction-predictor`.
- [Device interface](docs/hardware.md): drivers, safe-state and HTTP adapter.
- [OpenRouter configuration](docs/openrouter.md): optional constrained orchestration decisions.
- [Development constraints](AGENTS.md): repository rules that must remain true while changing code.

`python -m phage_lab <command> --help` shows command-specific parameters.

Formal execution starts from a frozen ExperimentSpec. The old candidate-based run
remains as a compatibility path; new integrations use the spec. Real execution
requires an explicitly configured driver and test-ready MaterialBatch and never
silently falls back from real to virtual hardware.

Each run writes `report.json`, `report.md` and `events.jsonl` under
`runs/<run-id>/`. Raw FASTA and headers stay local by default.

## Next steps

1. Resolve source-label and assay-context review before adding endpoint mappings or a source-endpoint screening policy; retain the current mechanistic decision boundary.
2. Evaluate host–phage pair models and available pretrained representations in `phage-host-interaction-predictor`, using explicit generalization regimes and an independent release holdout.
3. Make characterization requirements model-declared, then extend validated prediction-driven decisions and curated experimental feedback.

## License

[Apache License 2.0](LICENSE)

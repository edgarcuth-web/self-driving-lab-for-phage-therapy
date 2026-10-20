# SELF-DRIVING PHAGE THERAPY
### Observe → Model → Design → Test → Learn → Adapt

A closed-loop system that:
- learns the evolving phage–host arms race
- converts experimental evidence into the next decision
- updates its models and decision policy as new experimental outcomes arrive

## System overview

```text
                         SCIENTIFIC CONTROL
                                │
                                ▼

Host / Phage ──► OBSERVE ──► MODEL ──► DESIGN ──► TEST ──► LEARN ──► ADAPT
                    ▲                                                │
                    └────────────────────────────────────────────────┘

                                 failure / ambiguity
                                        │
                                        ▼
                              mechanism attribution
                                        │
                                        ▼
                              engineering escalation
                                        │
                                        └──────────────► DESIGN
```

Engineering is an escalation path — not the default.

The repository owns the experimental decision loop, biological characterization,
evidence/provenance, experiment specification and execution boundary. Model-specific
embeddings, training, calibration and inference live in the separate
`phage-host-interaction-predictor` repository and communicate through versioned
exchange contracts.

The current implementation is a **feedback-driven screening software loop**:
it records inputs and predictions, freezes experiment intent, ingests QC-admitted
results, creates explicit prediction-vs-outcome learning records, and selects the
next unresolved screening question. Biological characterization also belongs here
(the first real analyzer is PADLOC). There is not yet automatic model training,
automatic recalibration, or validated real-instrument execution.

The first model integration uses **ModelInputBundle v1 → PairPrediction v1**:
SDL exports complete pair snapshots, explicit source-label/context semantics and
selected local sequence/annotation payloads; model-side consumers verify actual
bytes. This implements exchange and abstention, not trained inference. Source
scores cannot enter the existing productive-infection screening policy by renaming
fields. See [model boundary](docs/model-interface.md).

## Current capabilities

| Part | Implemented | Current boundary |
| --- | --- | --- |
| Inputs and evidence | HostProfile, HostState, PhageProfile, reference snapshots, PHIST evidence | Unassessed analyzer features remain unknown; PHIST is not an infection probability |
| Scientific decision | InteractionPrediction contract, CandidateSet, PHIST cocktail baseline | Unresolved predictions stay unresolved; no validated efficacy optimizer yet |
| Experiment design | ExperimentSpec v2, control/treatment arms, MaterialBatch binding | Records intent and material provenance; does not define laboratory methods for the user |
| Execution | Scheduling, logging, timeout reconciliation, cancellation recovery, virtual device, HTTP adapter example | CLI does not configure real drivers by default; virtual devices create no biological evidence |
| Feedback and learning | Measurement, Phenotype, Comparison, FailureAttribution, LearningObservation, CalibrationReport, next-round selection | Labels are explicit; calibration is descriptive only and does not train a model or update H(t) |

Main implemented path:

```text
HostState + PhageProfile + InteractionEvidence
  → InteractionPrediction → CandidateSet
  → ExperimentSpec → execution + MaterialBatch
  → Measurement → Phenotype / Comparison → FailureAttribution
  ├→ LearningObservation → CalibrationReport
  └→ feedback-screening decision → next ExperimentSpec
```

CocktailDesign is an alternative source for ExperimentSpec. Single-phage screening
does not need to form a cocktail first.

For the full architecture, including scientific control/review, decision modules,
the experimental loop, engineering escalation and software/data planes, see
[docs/architecture.md](docs/architecture.md).

## Local checks

### Core CLI

Python 3.11+ is required. Core orchestration uses the standard library; sequence
registration and FeatureArtifact validation require `jsonschema`; real PADLOC
analysis uses the pinned external-tool environment in `envs/padloc.yml`.

From the repository root:

```bash
python -m phage_lab version
python -m unittest discover -s tests -v
```

The following checks only file flow with the repository's toy FASTA. They do not
run devices or generate experimental results:

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

Generated profiles do not imply assessed biological features; an empty HostState
does not mean a biological negative.

## Real biological characterization: PADLOC

This repository owns sequence-asset registration, FeatureArtifact v1, and the first
real analyzer, PADLOC v2.0.0. It runs real analysis on registered FASTA files whose
genome fingerprint matches the HostState, pins PADLOC-DB v2.0.0, and preserves
native outputs, logs, database-tree fingerprints and provenance.

No hit means only that the pinned database and this run did not detect a defense
system. It does not prove that the bacterium has no defense system. Current PADLOC
results are not automatically promoted to an assessed-negative HostProfile.

See [docs/padloc-adapter.md](docs/padloc-adapter.md).

```bash
conda env create -f envs/padloc.yml
conda activate phage-padloc
python -m phage_lab annotate-host-defense-padloc --help
```

Across the repository boundary, SDL exports frozen ModelInputBundle records with
approved scientific annotations, screening state and provenance. The model
repository owns model-specific representations, training, evaluation, weights and
inference. ModelInputBundle v1 supports full snapshots, explicit endpoint/context
semantics, readable local sequence payloads and annotation outputs. PairPrediction
v1 binds the entire bundle. Legacy ModelRequest/ModelResult v1 remains for existing
mechanistic endpoints; the two paths are not silently converted. There is not yet
a trained, calibrated inference implementation in this repository.

## Clinical workflow presentation (offline simulation)

```bash
python -m phage_lab dashboard
```

On Windows, `start-dashboard.bat` starts the local presentation. Open
`http://127.0.0.1:8765`; use `--port 8766` if needed and `--no-browser` to
disable automatic browser launch.

This browser workflow is a presentation layer built on synthetic local data. It
illustrates patient sampling, metadata capture, simulated isolate detection,
parallel phage/antibiotic matching, simulated preparation and the screening /
experiment / feedback concepts. It does **not** call the scientific modules,
create domain experiment objects, run real devices, or create biological evidence.

`ABX-DEMO` / `PHG-DEMO`, the approximately seven-day preparation interval,
artificial DNA fragments, confidence scores and reference windows are presentation
fixtures, not clinical claims, validated thresholds, real sequences, PCR primers,
or efficacy evidence. Unclassified bacterial-like signals remain review items and
do not establish a novel species or enter candidate matching automatically.

The optional Kimi K3 report path produces a clinical-format draft from the terminal
presentation state. Credentials stay in process memory; raw FASTA is not sent.
A failed model response remains a failure. Generated reports are drafts requiring
review, not diagnoses, prescriptions, susceptibility results, or scientific
domain artifacts.

Presentation checks:

```bash
python -m unittest discover -s tests -p test_dashboard.py -v
node --test tests/test_dashboard_model.cjs
node --test tests/test_presentation.cjs
python -m unittest discover -s tests -p test_clinical_reports.py -v
sh scripts/smoke.sh
```

Node 18+ is only required for the JavaScript presentation tests.

## Use and development

- [CLI usage](docs/usage.md): stage-by-stage commands, inputs and later rounds.
- [Architecture and domain contracts](docs/architecture.md): system planes, object relationships, evidence semantics and validation boundaries.
- [External model interface](docs/model-interface.md): versioned JSON contracts between the SDL and `phage-host-interaction-predictor`.
- [Device interface](docs/hardware.md): drivers, safe-state behavior and HTTP adapter.
- [OpenRouter configuration](docs/openrouter.md): optional constrained orchestration decisions.
- [Development constraints](AGENTS.md): invariants for code and documentation changes.

`python -m phage_lab <command> --help` shows command-specific options.

Formal execution starts from a frozen ExperimentSpec. The legacy candidate-based
run remains a compatibility entry; new integrations use specs. Real execution
requires an explicit driver and test-ready MaterialBatch binding and never falls
back silently from virtual mode.

Each run writes `report.json`, `report.md` and `events.jsonl` under
`runs/<run-id>/`. Raw FASTA and headers are not sent to external models by
default.

## Next steps

1. Accumulate real LearningObservation records from physical experiments with independent training/validation splits.
2. Complete reproducible fitting, held-out evaluation and calibration in `phage-host-interaction-predictor`; this repository admits only versioned outputs through the model boundary.
3. After validated prediction, add prediction-driven cocktail optimization and then evaluate evidence-gated engineering escalation.

## License

[Apache License 2.0](LICENSE)

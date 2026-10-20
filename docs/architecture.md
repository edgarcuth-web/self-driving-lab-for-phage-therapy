# Architecture

The system is organized as a closed scientific loop:

```text
Observe → Model → Design → Test → Learn → Adapt
   ▲                                      │
   └──────────────────────────────────────┘
```

Scientific components choose what to test. Workflow orchestration executes a
frozen ExperimentSpec and records what happened. Current capabilities and planned
work belong in [README](../README.md); commands belong in [usage](usage.md).

The diagrams below are architectural views, not new artifact contracts. They
clarify responsibilities already represented by the domain objects and software.
Formal object semantics remain defined by the later sections of this document.

## System overview

The project has a fast natural-phage path and an evidence-gated engineering
escalation path.

```text
FAST LOOP
host / phage evidence
        │
        ▼
 characterize → predict → select natural phage / cocktail → test → learn
        ▲                                                    │
        └────────────────────────────────────────────────────┘

ESCALATION LOOP
failed or ambiguous result
        │
        ▼
failure attribution → mechanistic gap → engineering hypothesis
        │                                      │
        └──────────────────────────────────────┘
                           re-enter prediction / test
```

Engineering is an escalation path, not the default. A lack of natural candidates
does not by itself justify an engineered design; the system should preserve the
evidence gap and, where possible, identify a mechanism that motivates the
engineering hypothesis.

## Scientific control and review

Scientific control coordinates work; it is not itself the phage–host prediction
model, cocktail optimizer or failure model.

```text
                         Human objective
                               │
                               ▼
                    SCIENTIFIC ORCHESTRATOR
                  decompose / delegate / integrate
                               │
          ┌────────────────────┼────────────────────┐
          ▼                    ▼                    ▼
 host characterization   phage evaluation   failure/mechanism review
          │                    │                    │
          └────────────────────┼────────────────────┘
                               ▼
                    scientific decision modules
                               │
                               ▼
                        ExperimentSpec
```

A scientific reviewer is a cross-cutting quality role rather than a step that
silently rewrites scientific outputs:

```text
SCIENTIFIC REVIEWER
  ├─ evidence quality
  ├─ methodology
  ├─ uncertainty / missingness
  ├─ unsupported claims
  └─ reproducibility
          │
          └── request revision of the relevant scientific task
```

This control-plane view is distinct from `workflow.py` / `agents.py`, which
assign devices, schedule steps and recover execution of already-frozen intent.
Scientific orchestration may propose or coordinate a new ExperimentSpec; workflow
orchestration must not mutate an approved one.

## Scientific decision architecture

The pairwise interaction layer and the set-level cocktail decision layer are
different scientific problems.

```text
HostProfile / HostState                  PhageProfile
          │                                  │
          └──────────────┬───────────────────┘
                         ▼
               InteractionPrediction
       adsorption / productive infection /
       resistance emergence / uncertainty
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
     natural-phage ranking     mechanism / risk hypotheses
              │
              └──────────┬──────────┘
                         ▼
                  CandidateSet
                         │
                         ▼
                 CocktailDesign
          pairwise evidence + set-level
       compatibility / diversity / constraints
                         │
                         ▼
                  ExperimentSpec
```

Pairwise coverage is not cocktail efficacy. Set-level design may consume pairwise
predictions, but it must separately represent cocktail assumptions, unresolved
gaps, compatibility, diversity and other objectives. The current PHIST cocktail
baseline is deliberately conservative and does not establish these properties.

Mechanism/risk hypotheses before an experiment are also distinct from
post-experiment FailureAttribution. A predicted risk is not an observed cause.

## Experimental closed loop

```text
ExperimentSpec
     │
     ▼
MaterialBatch binding
     │
     ▼
workflow / scheduler
     │
     ▼
device abstraction
  ┌──┴─────────────┐
  ▼                ▼
real device    virtual hardware
  │                │
  └──────┬─────────┘
         ▼
      Raw Data
         │
         ▼
Measurement + QC
         │
         ▼
Phenotype / Comparison
         │
         ▼
ExperimentResult / review
         │
    ┌────┴───────────────┐
    ▼                    ▼
FailureAttribution   LearningObservation
    │                    │
    └──────────┬─────────┘
               ▼
      next scientific decision
               │
               └──────────────────────────────↺
```

Virtual hardware tests control flow and lineage only. It must never create
biological evidence. Physical observations enter learning only through explicit
QC admission and assessor-declared semantics.

## Failure to engineering escalation

```text
experimental failure / ambiguity
              │
              ▼
       FailureAttribution
              │
      ranked mechanism hypotheses
              │
      ┌───────┼───────────────┐
      ▼       ▼               ▼
 adsorption  intracellular   kinetics / resistance / unknown
      │       │
      ▼       ▼
 Tier 1      Tier 2
 RBP /       defense–counterdefense-aware
 adsorption  engineering
 engineering
      │       │
      └───┬───┘
          ▼
 engineered PhageProfile
          │
          └──► re-enter prediction → design → test

Tier 0  existing natural phage
Tier 1  adsorption / RBP engineering
Tier 2  defense–counterdefense-aware engineering
Tier 3  whole-genome generative design
```

Tier 3 is a mature-platform capability, not a starting point. Engineered candidates
must re-enter the same profile, prediction, review and experimental evidence path
as natural candidates rather than bypassing it.

## System planes

```text
Scientific control / review
────────────────────────────────────────
Scientific characterization, models and decisions
────────────────────────────────────────
Experiment specification
────────────────────────────────────────
Workflow orchestration
────────────────────────────────────────
Device abstraction
────────────────────────────────────────
Real device │ Virtual hardware
────────────────────────────────────────
Data / provenance / model and artifact records
```

Stable contracts between these planes allow models, decision policies, workflows
and hardware integrations to evolve independently without collapsing their
responsibilities into one "model" or one "orchestrator."

## Objects and ownership

`dashboard.py` and `web/` provide a separate browser-only clinical workflow
presentation. Synthetic fixture isolation/matching and a scenario clock never
call the scientific modules or scheduler. The page illustrates domain concepts
without constructing domain artifacts; `execution_mode=presentation_only`,
`physical_execution=false`, and `evidence_class=none` describe this boundary.
`clinical_reports.py` optionally minimizes terminal snapshots and calls Kimi Code
K3 to draft a clinical-format narrative. Credentials/jobs live in process memory;
the loopback API checks origin/host/session tokens and deduplicates requests per
run/configuration. Failed or truncated responses remain failures, with no local
model fallback. The generated draft is text, not a scientific domain artifact,
physical evidence, susceptibility result, prescription or clinician approval.
The presentation's fragment detector uses deterministic artificial query/reference
windows and a documented uncalibrated support score. Unclassified bacterial-like
signals stay separate from named candidates and never establish a novel species
or automatically enter matching. The report boundary recomputes score components,
retains review flags and fragment IDs, and strips all query/reference bases.
The presentation tour maps elapsed playback seconds to the existing scenario
clock without modifying node dependencies or duration contracts. Pause/reset,
case changes and leaving presentation mode stop automatic advancement. A
separate derived timeline shows independent matching/preparation states; review
counts include low-support candidates and unresolved signals even after the
main workflow completes. Terminal notification is once per run, separate from
the tour's final report chapter and actual asynchronous report completion.

| Module | Artifact / responsibility |
| --- | --- |
| `host_profile.py` | Stable HostProfile identity, normalized genome hash and characterization |
| `host_state.py` | Time-indexed HostState H(t), components, evidence and previous-state pointer |
| `phage_profile.py` | PhageProfile identity and retrieved / natural / engineered provenance |
| `interaction_evidence.py`, `ranking.py` | Pairwise source signals and PHIST adapter |
| `interaction_prediction.py` | Exact H(t)/phage predictions with uncertainty and model provenance |
| `model_contract.py` | Legacy mechanistic ModelRequest/ModelResult exchange and external-result admission |
| `model_input_bundle.py` | Frozen source-endpoint inputs, portable resources and PairPrediction validation |
| `natural_phage_recommender.py` | CandidateSet, screening policy and single-phage spec conversion |
| `cocktail_design.py` | CocktailDesign and conservative PHIST screening baseline |
| `experiment_spec.py` | ExperimentSpec v2, arms, optional source references and abstract workflow |
| `material_batch.py` | Physical batch identity, QC/availability and spec binding |
| `measurement.py` | Arm-scoped device results and explicit QC admission |
| `phenotype.py` | Single-arm Phenotype and explicit PhenotypeComparison |
| `failure_attribution.py` | Assessor review against a declared criterion; mechanism hypotheses |
| `learning.py` | Explicit prediction-vs-phenotype labels and descriptive calibration reports |
| `active_learning.py` | Fixed-context feedback screening and next-spec conversion |
| `biology.py`, `snapshots.py`, `candidates.py`, `sequences.py` | Local FASTA, reference snapshots and retrieval |
| `workflow.py`, `agents.py` | Input validation, device assignment, scheduling and recovery |
| `devices.py`, `virtual_hardware.py` | Driver contract and control-path twins |
| `records.py`, `provenance.py` | Run artifacts and source identity |
| `artifacts.py` | Shared primitive validation, JSON hashing and atomic writes |
| `cli/` | Command-specific parsers and handlers |
| `legacy.py` | Candidate-planning compatibility before the common scheduler |

The main path is prediction → CandidateSet → ExperimentSpec → execution → results
→ review → next selection. CocktailDesign is an alternative spec source, not a
required parent of a single-phage screening experiment. Artifacts already used in
build/test retain their versions; later changes create new records.

## Identity, state and evidence

HostProfile anchors a sample and normalized genome identity. An unassessed feature
class is `unknown`; `assessed` requires analyzer provenance. An empty assessed
result can represent an assessed negative. Raw FASTA is local input, not profile
content or default external-model context.

HostState binds one exact profile/genome, `as_of`, explicit components and evidence.
Missing components are unknown. Each component cites evidence admitted in that
snapshot; future or other-host evidence is rejected. H(t+1) may reference H(t),
but never inherits dynamic components implicitly. Measurement/Phenotype adapters
copy lineage only, leaving interpretation to the caller.

PhageProfile separates intrinsic identity from host queries and interaction data:

- `retrieved`: external record provenance, with no assertion of natural origin;
- `natural`: locally tracked collection/isolate identity;
- `engineered`: design identity and parent-profile lineage, never invented accessions.

InteractionEvidence is one content-addressed host/phage source signal, including
producer/version/parameters, timestamp and input provenance. Current kinds are
source annotation and computational evidence; physical results use Measurement.
PHIST reported/no-signal statuses are neither susceptibility verdicts nor infection
probabilities. Cohort-relative rank stays in ranking/design context.

## External model boundary

The design/decision system is larger than any one predictor. Its first delivery
module is Candidate Phage Prioritization. The first model task is a source-defined
binary outcome for one existing host–phage pair; batch calls form a pair matrix.

| Responsibility | Owner and current boundary |
| --- | --- |
| Characterization | SDL sequence registry, HostState/PhageProfile, PADLOC and FeatureArtifact; model-specific embeddings stay with each model |
| Prediction | External model consumes frozen ModelInputBundle and returns an exact source-endpoint PairPrediction |
| Retrieval | SDL snapshot/candidate retrieval determines the available pool; retrieval itself asserts no susceptibility |
| Decision | SDL owns screening/combination policies and ExperimentSpec; existing CandidateSet policy still requires compatible mechanistic predictions |
| Execution | SDL executes frozen ExperimentSpec and records physical/virtual provenance |
| Feedback | SDL QC, phenotype and explicit learning labels; models train/validate/release separately |

Source-label scores cannot feed the productive-infection policy without reviewed
endpoint mapping. Pair-matrix coverage is not mixture efficacy. Inverse feature
requirements and engineering hypotheses remain later system capabilities.


Model training, model-specific preprocessing/embeddings, evaluation and calibration
live in a separate repository. This repository owns biological characterization
pipelines (including sequence-resource resolution and PADLOC), their FeatureArtifact
provenance, experimental state, and the content-addressed ModelRequest/ModelResult
exchange and prediction-admission gate. A scientific annotation remains useful if
model architecture or weights are replaced. A matching hash proves lineage
consistency, not scientific validity. See [model-interface](model-interface.md).

## Predictions and selection

InteractionPrediction binds exact HostState ID/hash, PhageProfile ID/content
fingerprint, supporting evidence IDs and model provenance. Pair evidence may be
empty for unseen-pair prediction, but that absence stays explicit. Supplied evidence
must match the host/phage and must not postdate H(t).

All three targets—adsorption, productive infection and resistance emergence—must
be present. `estimated` requires a probability in [0,1], containing uncertainty
bounds and a named method; `not_estimated` requires null numeric fields. The
evidence-only adapter emits unresolved targets, never invented probabilities.

CandidateSet retains the complete input pool, prediction snapshots, dispositions,
policy/version/budget, reasons and exact H(t) reference. Loading checks hash and
recomputes selection. The baseline:

1. admits natural/retrieved records; excludes engineered or missing-prediction records;
2. orders productive-infection estimates by descending uncertainty lower bound;
3. reserves exploration slots for unresolved predictions and fills unused budget
   from either queue; profile ID is only a deterministic tie-break;
4. records unselected eligible candidates as deferred, not negative.

Comparable estimates require identical producer/configuration/model artifact and
uncertainty method. Matching provenance does not establish calibration or assay
comparability. Adsorption/resistance estimates are retained but do not affect this
baseline's ordering. Material readiness, safety, diversity, compatibility and
information gain are outside this policy. Duplicate/ambiguous inputs, wrong state
or profile fingerprints and future predictions are rejected.

CocktailDesign records exact members/evidence, objectives, assumptions, producer
and unresolved gaps. The PHIST baseline selects at least two non-engineered,
reported-signal candidates by cohort rank without topping up from no-signal
records. It does not establish efficacy, receptor complementarity or cross-resistance
protection. Generic designs may represent engineered provenance separately.

## Frozen intent and execution

Each ExperimentArm locks role, host, phages, conditions and expected readouts.
Controls may have zero phages; treatments require members. ExperimentSpec also
locks objective/questions, constraints, optional source ID/hash references and an
abstract dependency workflow. Device assignments and instrument commands are
outside the spec. CandidateSet conversion creates a host control and independent
single-phage treatments with caller-declared objective/readouts.

Execution resolves only locked members, verifies genome/workflow identity and
calls device assignment rather than scientific candidate selection. Recovery may
change devices, never intent. Legacy candidate-based runs remain a compatibility
entry. The example prepare/infect/measure graph is an orchestration example, not
a biological protocol. See [hardware](hardware.md) for driver lifecycle details.

A MaterialBatch is tracked physical material, not an accession. Released/rejected
QC states require evidence; test-ready binding requires released and usable status.
Spec-bound real execution requires exactly one matching host batch and one per
phage before dispatch. Virtual runs may carry batch IDs for lineage tests but do
not consume material. Physical/virtual modes never mix or silently fall back.

## Results and review

Measurement preserves exact run/spec/arm/device/material lineage, raw device
output and explicit QC. Workflow success does not imply valid QC. Valid/invalid
states require QC evidence; pending may omit it. Virtual outputs always have
`evidence_class=none`.

Phenotype admits only physical, QC-valid Measurements from one exact spec/arm
and material set. The assessor declares type, outcome, value and interpretation;
there is no automatic efficacy threshold. PhenotypeComparison binds two distinct
arms' exact phenotype hashes, same spec/type and an explicit assessor statement.

FailureAttribution reviews one phage-containing treatment arm against a declared
criterion. Negative phenotype does not automatically mean failure, and the review
criterion does not establish preregistration. It embeds spec/results, re-admits
source Measurements, verifies all exact lineage and temporal order, and rejects
unreferenced results. Other-arm phenotypes require a target-arm comparison.

Only observed failure may carry mechanism hypotheses, with exact reviewed-result
references, rationale and limitations. Empty hypotheses mean unknown; hypotheses
are never confirmed causes. Cocktail reviews stay whole-arm, with no automatic
member attribution, HostState mutation or probability update.

## Learning and calibration

LearningObservation links one exact InteractionPrediction to one physical,
QC-admitted Phenotype from a single-phage treatment arm. The target
(adsorption / productive infection / resistance emergence) and binary observed
label are assessor-declared; phenotype polarity, value or FailureAttribution is
never converted automatically into a training label. Exact host/profile lineage
and prediction/spec/result time order are revalidated. An unresolved prediction
may still produce a label-only observation for later model fitting.

CalibrationReport accepts only scorable observations for one target whose
PredictionProducer configuration and uncertainty method are identical. It reports
descriptive sample count, mean predicted probability, observed rate, calibration
gap, Brier score and log loss. It does not fit or recalibrate a model, establish
assay comparability, create confidence intervals, update H(t), or replace any
InteractionPrediction. Training/validation splitting and model fitting remain a
separate future boundary.

## Feedback screening

The historical `ActiveLearningDecision` API implements a feedback-screening
heuristic. It fixes the exact CandidateSet, original single-phage screening spec,
criterion and assay context (host, conditions/readouts, objective, workflow and
constraints). Declared context equality cannot prove an unchanged physical host.

Conclusive single-phage reviews retire that screening question only in this
context. Inconclusive/conflicting reviews require explicit review. Missing feedback
remains unknown; cocktail feedback does not retire members. Source exclusions
remain in force; remaining untested entries use the original budget policy. Empty
selection abstains and cannot produce an experiment.

Decisions retain cumulative feedback, exact references and per-candidate reasons.
`previous_decision` explicitly carries history forward; loading revalidates embedded
inputs, while independent verification of the prior pointer needs that artifact.
Same-ID replacement, competing revisions and duplicate experiment-arm reviews are
rejected. Next-spec conversion copies the fixed context and workflow, uses a new
experiment ID and never dispatches devices. This software loop does not train a
model, update H(t)/probabilities or demonstrate biological improvement.

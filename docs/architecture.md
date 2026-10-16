# Architecture

## System flow

```text
Host genome / isolate
        ↓
HostProfile
        ↓
PhageProfile + InteractionEvidence
        ↓
CocktailDesign
        ↓
ExperimentSpec
        ↓
MaterialBatch + Lab orchestration
        ↓
Measurement
        ↓
Phenotype / FailureAttribution
        ↓
Feedback / model update
        └────────────────────→ next cycle
```

Scientific components choose what to test. The orchestration layer executes a validated `ExperimentSpec`.

## Core domain objects

| Object | Purpose |
| --- | --- |
| `HostProfile` | Versioned host characterization |
| `PhageProfile` | Versioned natural or designed phage characterization |
| `InteractionEvidence` | One traceable phage-host observation or model output |
| `CocktailDesign` | Versioned member set, objectives and supporting evidence |
| `ExperimentSpec` | What will be tested and under which constraints |
| `MaterialBatch` | Physical material identity, quality and availability |
| `Measurement` | Raw/processed measurement linked to experiment and device |
| `Phenotype` | Biological interpretation of valid measurements |
| `FailureAttribution` | Mechanism hypothesis with supporting evidence |
| model/analysis record | Tool/model identity, version, inputs and parameters |

Target lineage:

```text
HostProfile
  → Design
  → MaterialBatch
  → ExperimentSpec
  → Measurement
  → Phenotype / FailureAttribution
  → Feedback
  → next Design
```

Design versions already used in build/test are immutable.

## HostProfile

Raw FASTA is input to local analysis, not the profile itself.

`HostProfile` may contain:

- taxonomy / strain identity;
- receptor candidates;
- capsule, LPS and other surface structures;
- anti-phage defense systems;
- AMR / virulence context;
- prior susceptibility or phenotype references.

Semantics:

- `unknown`: no admitted analyzer assessed the feature class;
- `assessed`: an identified analyzer assessed it; an empty result may then represent an assessed negative.

Every assessed feature must point to analysis provenance. Raw FASTA is not sent to external models by default.

HostProfile v1 currently implements schema, genome identity, feature-state semantics and local serialization; analyzers are separate components.

## PhageProfile and InteractionEvidence

PhageProfile v1 separates identity from interaction evidence and defines three provenance variants:

- `retrieved`: constructed from an external reference/database record. This states record provenance only; it does not by itself prove natural biological origin.
- `natural`: a locally tracked natural isolate with collection and isolate identity.
- `engineered`: a designed/engineered phage with design identity and one or more parent PhageProfile IDs.

A profile may carry sequence accession/hash/length and scalar source annotations. Host queries, PHIST rankings and other phage-host signals are not intrinsic profile fields; they belong in `InteractionEvidence`.

Future PhageProfile characterization may add RBP/tail, receptor and counter-defense annotations through separately versioned analyzers.

InteractionEvidence v1 is now implemented as a content-addressed record linking one host identity and one versioned PhageProfile to a source signal. It stores evidence kind, signal, raw result fields, interpretation, producer identity/version/parameters, observation time and input provenance.

Current evidence kinds are `source_annotation` and `computational`. Physical measurements will enter through the later Measurement/Phenotype slice rather than being mislabeled as generic computational evidence.

PHIST is the first implemented evidence producer. For compatibility it still emits the legacy `ranking` block, but it also emits `interaction_evidence` for every candidate:

- reported PHIST match → `status=reported_signal`;
- no significant PHIST match → `status=no_signal`;
- neither status is converted into susceptible/resistant or infection probability.

The PHIST host digest now uses the same normalized genome identity as HostProfile. When a matching HostProfile is supplied, its profile ID is bound into the evidence. Cohort-relative rank remains outside the pairwise evidence object.

Evidence IDs are hashes of the evidence content, so modified evidence fails validation.

## CocktailDesign

CocktailDesign v1 is implemented as an immutable, content-hashed scientific design artifact. It records:

- target HostProfile identity;
- versioned PhageProfile members;
- the exact InteractionEvidence supporting each member;
- named objectives and rationale;
- assumptions and unresolved evidence gaps;
- designer identity/version/parameters;
- cohort-relative selection context such as legacy PHIST rank.

The first designer is deliberately named `phist-screening-baseline`, not an optimizer. It selects at least two non-engineered PhageProfiles with PHIST-reported evidence, in cohort rank order. It does not top up with `no_signal` candidates and explicitly records missing physical phenotype, receptor/RBP, defense/counter-defense, cross-resistance and phage-phage compatibility evidence.

Generic CocktailDesign can represent later engineered designs, but this baseline excludes engineered provenance to preserve the natural-first escalation rule.

Cocktail selection is a scientific decision, not an orchestration-agent task.

## ExperimentSpec

ExperimentSpec v1 is the implemented boundary between scientific design and execution. It freezes:

- the exact source CocktailDesign ID and content hash;
- target HostProfile identity;
- the complete ordered set of member PhageProfile IDs;
- an abstract operation/dependency workflow;
- purpose, scientific questions and execution constraints.

ExperimentSpec contains no device assignments or instrument-specific commands. Candidate records remain temporary execution inputs until MaterialBatch exists; a binding step resolves only the records whose PhageProfile IDs are locked in the spec and ignores unrelated discovery candidates.

For spec-bound runs:

- the runtime host genome must match the spec target;
- runtime workflow must exactly match the locked workflow;
- orchestration calls `assign_devices()`, never candidate-selection `plan()`;
- assignment responses cannot contain candidate IDs;
- the execution payload carries ExperimentSpec ID/hash, source CocktailDesign ID and locked PhageProfile IDs;
- device recovery may change a device, but never scientific membership.

The legacy candidate-based run path remains for compatibility while downstream artifacts migrate to ExperimentSpec.

## Engineering escalation

```text
natural phage evaluation
        ↓
cocktail optimization
        ↓
unresolved coverage / resistance gap?
        ├─ no → test / learn
        └─ yes
             ↓
      host-range engineering
             ↓ if needed
      defense/counter-defense
             ↓ if needed
      broader genome-level design
```

Each escalation step needs an explicit gap and its own design provenance.

## Materials and Synbio

Keep these separate:

- design;
- acquisition/order;
- synthesis/build product;
- material batch;
- quality status;
- inventory/reservation/consumption.

A completed device task does not by itself make material test-ready. Experiments reference the exact material batches used.

## Experiment execution

The testing layer is moving toward:

```text
ExperimentSpec
+ MaterialBatch(es)
+ device capabilities
```

ExperimentSpec is now consumed directly. MaterialBatch and first-class Measurement ingestion are still pending; current candidate records bridge material identity temporarily. Execution produces run records and device outputs, not biological phenotype claims.

The current `prepare → infect → measure` workflow is an orchestration example, not the final domain model.

Execution rules:

- `real_hardware` and `virtual_hardware` are explicit and never mixed;
- timeout means unknown outcome until reconciled;
- retries require confirmed cancellation or confirmed prior completion;
- real drivers declare and confirm safe-state;
- workflow success is not a biological conclusion;
- ExperimentSpec-bound orchestration cannot change cocktail membership or workflow.

Virtual hardware tests the control path only. It does not create biological evidence.

## Measurement and feedback

Keep these outcomes distinct:

1. acquisition/build failure;
2. device execution failure;
3. invalid/incomplete measurement;
4. valid negative phenotype;
5. valid positive/graded phenotype.

Only valid physical measurements can support physical phenotype claims.

`FailureAttribution` may later classify mechanisms such as adsorption-level failure, intracellular incompatibility, kinetics or unknown, but only from supporting evidence.

Feedback creates a new design/version; it does not overwrite previous experimental lineage.

## Current module mapping

| Module | Role |
| --- | --- |
| `biology.py` | FASTA validation and genome summary |
| `host_profile.py` | HostProfile v1 |
| `phage_profile.py` | PhageProfile v1 and retrieved/natural/engineered provenance |
| `interaction_evidence.py` | InteractionEvidence v1 and PHIST adapter |
| `cocktail_design.py` | CocktailDesign v1 and conservative PHIST screening baseline |
| `experiment_spec.py` | ExperimentSpec v1, design freezing and member binding |
| `snapshots.py`, `candidates.py` | Reference snapshots and retrieved candidate records |
| `sequences.py` | Accession-indexed sequences |
| `ranking.py` | PHIST ranking compatibility layer and evidence producer |
| `agents.py` | Bounded orchestration decisions |
| `workflow.py` | Validation, scheduling and recovery |
| `devices.py` | Device contract |
| `virtual_hardware.py` | Control-path device twins |
| `records.py`, `provenance.py` | Run records and provenance |

Current implementation status belongs in [README.md](../README.md).

## Build order

1. host-characterization analyzers;
2. MaterialBatch and measurement / phenotype ingestion;
3. FailureAttribution;
4. active learning;
5. engineering escalation;
6. additional real-device and Synbio integrations.

Each step should be mergeable and keep `main` runnable.

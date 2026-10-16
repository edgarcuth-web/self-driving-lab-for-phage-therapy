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

Natural/retrieved phages and generated/engineered designs have different provenance.

`PhageProfile` may include sequence/design identity, RBP/tail annotations, receptor evidence, counter-defense annotations, host-range phenotype references and material references.

`InteractionEvidence` separates evidence from design decisions. Sources may include:

- database annotation;
- PHIST or other genome-based tools;
- sequence/embedding models;
- RBP-receptor models;
- defense/counter-defense models;
- physical experiments.

PHIST is one evidence producer. Its shared-k-mer statistic is not an infection probability.

## CocktailDesign

`CocktailDesign` records:

- target `HostProfile`;
- member `PhageProfile` versions;
- supporting `InteractionEvidence`;
- design objective and rationale;
- assumptions, uncertainty and unresolved gaps;
- model/optimizer identity.

Cocktail selection is a scientific decision, not an orchestration-agent task.

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

The testing layer consumes:

```text
ExperimentSpec
+ MaterialBatch(es)
+ device capabilities
```

and produces execution records plus `Measurement` artifacts.

The current `prepare → infect → measure` workflow is an orchestration example, not the final domain model.

Execution rules:

- `real_hardware` and `virtual_hardware` are explicit and never mixed;
- timeout means unknown outcome until reconciled;
- retries require confirmed cancellation or confirmed prior completion;
- real drivers declare and confirm safe-state;
- workflow success is not a biological conclusion.

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
| `snapshots.py`, `candidates.py` | Reference snapshots and natural candidate retrieval |
| `sequences.py` | Accession-indexed sequences |
| `ranking.py` | PHIST evidence source |
| `agents.py` | Bounded orchestration decisions |
| `workflow.py` | Validation, scheduling and recovery |
| `devices.py` | Device contract |
| `virtual_hardware.py` | Control-path device twins |
| `records.py`, `provenance.py` | Run records and provenance |

Current implementation status belongs in [README.md](../README.md).

## Build order

1. host-characterization analyzers;
2. PhageProfile;
3. InteractionEvidence;
4. CocktailDesign;
5. ExperimentSpec integration;
6. measurement / phenotype ingestion;
7. FailureAttribution;
8. active learning;
9. engineering escalation;
10. additional real-device and Synbio integrations.

Each step should be mergeable and keep `main` runnable.

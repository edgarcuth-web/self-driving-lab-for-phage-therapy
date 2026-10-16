# Architecture

## System flow

```text
Host genome / isolate
        ↓
HostProfile
        ↓
HostState H(t)
        ↓
PhageProfile + InteractionEvidence
        ↓
[next: InteractionPrediction]
        ↓
CandidateSet / CocktailDesign / scientific intent
        ↓
ExperimentSpec v2 + ExperimentArm(s)
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
| `HostProfile` | Stable versioned host identity and characterization anchor |
| `HostState` | Content-addressed H(t): explicit time-dependent host state backed by admitted evidence |
| `PhageProfile` | Versioned natural or designed phage characterization |
| `InteractionEvidence` | One traceable phage-host observation or model output |
| `CocktailDesign` | Versioned member set, objectives and supporting evidence; one optional ExperimentSpec source |
| `ExperimentArm` | One control/treatment arm with host, 0/1/N phages, conditions and expected readouts |
| `ExperimentSpec` | Versioned arm-aware experimental intent independent of any one design artifact |
| `MaterialBatch` | Physical material identity, quality and availability |
| `Measurement` | Arm-scoped raw/processed measurement with run/spec/device/material/QC lineage |
| `Phenotype` | Biological interpretation of valid physical Measurements from exactly one ExperimentArm |
| `PhenotypeComparison` | Explicit assessor-stated comparison between two admitted arm phenotypes |
| `FailureAttribution` | Mechanism hypothesis with supporting evidence |
| model/analysis record | Tool/model identity, version, inputs and parameters |

Target lineage:

```text
HostProfile
  → HostState H(t)
  → scientific source(s) / intent
  → ExperimentSpec + ExperimentArm(s)
  → MaterialBatch
  → arm-scoped Measurement
  → Phenotype
  → PhenotypeComparison / FailureAttribution
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

## HostState H(t)

`HostState` v1 separates time-dependent state from stable `HostProfile` identity. It is an immutable, content-addressed snapshot with:

- exact HostProfile ID and genome hash;
- an explicit `as_of` timestamp;
- zero or more state components;
- evidence records referenced by every component;
- explicit limitations;
- an optional previous-state ID/hash/time pointer.

Current component domains are `receptor_state`, `surface_state`, `defense_state`, `physiology`, `antimicrobial_state`, `phage_exposure`, `phenotype_history`, and `environment`. Component basis is explicitly `observed`, `derived`, or `declared`.

Important semantics:

- omission means unknown; HostState does not encode an implicit negative;
- evidence observed after `as_of` is rejected;
- evidence for another HostProfile is rejected;
- every component must cite admitted evidence in the same snapshot;
- H(t+1) may point to H(t), but no components are inherited automatically;
- stable HostProfile features are not copied into HostState;
- Measurement/Phenotype adapters copy lineage only and do not infer state values.

This makes the future prediction boundary explicit: `InteractionPrediction` should consume an exact HostState record/hash rather than an unversioned notion of “current host”. New experimental evidence can produce a new H(t+1) without rewriting either HostProfile or earlier state snapshots.

## PhageProfile and InteractionEvidence

PhageProfile v1 separates identity from interaction evidence and defines three provenance variants:

- `retrieved`: constructed from an external reference/database record. This states record provenance only; it does not by itself prove natural biological origin.
- `natural`: a locally tracked natural isolate with collection and isolate identity.
- `engineered`: a designed/engineered phage with design identity and one or more parent PhageProfile IDs.

A profile may carry sequence accession/hash/length and scalar source annotations. Host queries, PHIST rankings and other phage-host signals are not intrinsic profile fields; they belong in `InteractionEvidence`.

Future PhageProfile characterization may add RBP/tail, receptor and counter-defense annotations through separately versioned analyzers.

InteractionEvidence v1 is now implemented as a content-addressed record linking one host identity and one versioned PhageProfile to a source signal. It stores evidence kind, signal, raw result fields, interpretation, producer identity/version/parameters, observation time and input provenance.

Current InteractionEvidence kinds are `source_annotation` and `computational`. Physical evidence now enters through the separate Measurement/Phenotype objects rather than being mislabeled as generic computational InteractionEvidence.

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

ExperimentSpec v2 is the implemented boundary between scientific design and execution. It freezes explicit ExperimentArms, each with role, target HostProfile, 0/1/N phages, conditions and expected readouts. CocktailDesign is one optional source artifact rather than a required parent. It also freezes the abstract operation/dependency workflow, scientific objective/questions and execution constraints.

ExperimentSpec contains no device assignments or instrument-specific commands. Candidate records still bridge discovery/source identity for compatibility, but physical execution lineage is now represented separately by MaterialBatch. A candidate binding step resolves only records whose PhageProfile IDs are locked in the spec and ignores unrelated discovery candidates.

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

## MaterialBatch and physical material lineage

MaterialBatch v1 is implemented as an immutable, content-hashed record tied to one HostProfile or PhageProfile. It records:

- caller-owned physical batch identity and revision;
- material type (`host` or `phage`);
- versioned profile identity;
- source kind/reference and timestamp;
- quality state (`pending`, `released`, `rejected`);
- availability state (`available`, `reserved`, `consumed`, `unavailable`);
- quality evidence references.

A database candidate/accession is not a MaterialBatch. A completed acquisition/build/device task does not make material test-ready. `released` and `rejected` states require explicit quality evidence.

For ExperimentSpec binding, exactly one test-ready host batch and one test-ready phage batch per locked member must be resolvable. Formal spec-bound real-hardware execution requires this binding before device dispatch. Virtual runs may carry the same batch IDs for lineage tests but explicitly state that no physical material was consumed.

Design, acquisition/build, material identity, QC state and inventory state remain separate concepts.

## Experiment execution

The testing layer now has the formal boundary:

```text
ExperimentSpec
+ MaterialBatch(es)
+ device capabilities
```

ExperimentSpec is consumed directly. Formal real-hardware spec execution requires test-ready MaterialBatch lineage; legacy candidate records remain a compatibility/source bridge. Execution produces run records and device outputs, not biological phenotype claims.

The current `prepare → infect → measure` workflow is an orchestration example, not the final domain model.

Execution rules:

- `real_hardware` and `virtual_hardware` are explicit and never mixed;
- timeout means unknown outcome until reconciled;
- retries require confirmed cancellation or confirmed prior completion;
- real drivers declare and confirm safe-state;
- workflow success is not a biological conclusion;
- ExperimentSpec-bound orchestration cannot change cocktail membership or workflow.

Virtual hardware tests the control path only. It does not create biological evidence.

## Measurement and Phenotype

Measurement v2 ingests one arm-scoped completed run result into a content-hashed artifact while preserving:

- run ID;
- exact ExperimentSpec ID/hash when present;
- source step and assigned device;
- MaterialBatch IDs when bound;
- raw JSON-compatible device result;
- physical vs virtual provenance;
- explicit QC status and QC evidence references.

Workflow success does not imply `qc_status=valid`. `valid` and `invalid` both require explicit QC evidence references; `pending` is the only status allowed without them. A virtual Measurement may be useful for control-path analysis but always carries `evidence_class=none`.

Phenotype v2 is a separate single-arm content-hashed interpretation artifact. It is never automatically inferred from a device value. A caller must state phenotype type, outcome, interpretation and assessor identity/version. Every source Measurement must be physical, QC-valid and belong to the same ExperimentSpec and ExperimentArm. PhenotypeComparison v1 then records an explicit assessor-stated comparison between two admitted arm phenotypes; it does not infer efficacy from raw values.

Keep these outcomes distinct:

1. acquisition/build/material failure;
2. device execution failure;
3. invalid/pending Measurement;
4. valid negative Phenotype;
5. valid positive/graded Phenotype.

`FailureAttribution` may later classify mechanisms such as adsorption-level failure, intracellular incompatibility, kinetics or unknown, but only from supporting evidence.

Feedback creates a new design/version; it does not overwrite previous experimental lineage.

## Current module mapping

| Module | Role |
| --- | --- |
| `biology.py` | FASTA validation and genome summary |
| `host_profile.py` | HostProfile v1 |
| `host_state.py` | HostState H(t) v1, temporal lineage and artifact-evidence adapters |
| `phage_profile.py` | PhageProfile v1 and retrieved/natural/engineered provenance |
| `interaction_evidence.py` | InteractionEvidence v1 and PHIST adapter |
| `cocktail_design.py` | CocktailDesign v1 and conservative PHIST screening baseline |
| `experiment_spec.py` | ExperimentSpec v2, ExperimentArm, generic scientific intent and optional source binding |
| `material_batch.py` | MaterialBatch v1 and test-ready material binding |
| `measurement.py` | Measurement v2, arm-scoped run-report ingestion and arm-specific material lineage |
| `phenotype.py` | Phenotype v2 plus explicit PhenotypeComparison v1 |
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

1. add InteractionPrediction above InteractionEvidence, consuming exact HostState H(t) lineage;
2. natural-phage recommender / CandidateSet;
3. active learning and FailureAttribution;
4. engineering escalation.

MaterialBatch, provenance, device abstraction and simulator detail are otherwise frozen unless one of these scientific-layer steps requires a change.

Each step should be mergeable and keep `main` runnable.

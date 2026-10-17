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
InteractionPrediction
        ↓
CandidateSet / natural-phage recommender
        ↓
CocktailDesign / scientific intent
        ↓
ExperimentSpec v2 + ExperimentArm(s)
        ↓
MaterialBatch + Lab orchestration
        ↓
Measurement
        ↓
Phenotype / FailureAttribution
        ↓
ActiveLearningDecision / next ExperimentSpec
        └────────────────────→ next cycle
```

Scientific components choose what to test. The orchestration layer executes a validated `ExperimentSpec`.

## Core domain objects

| Object | Purpose |
| --- | --- |
| `HostProfile` | Stable versioned host identity and characterization anchor |
| `HostState` | Content-addressed H(t): explicit time-dependent host state backed by admitted evidence |
| `PhageProfile` | Versioned natural or designed phage characterization |
| `InteractionEvidence` | One traceable phage-host source signal; never a calibrated infection probability |
| `InteractionPrediction` | Content-addressed probability prediction for one exact HostState-phage pair with uncertainty and model provenance |
| `CandidateSet` | Versioned screening selection, full input-pool decisions, exact prediction snapshots and explicit exploration |
| `CocktailDesign` | Versioned member set, objectives and supporting evidence; one optional ExperimentSpec source |
| `ExperimentArm` | One control/treatment arm with host, 0/1/N phages, conditions and expected readouts |
| `ExperimentSpec` | Versioned arm-aware experimental intent independent of any one design artifact |
| `MaterialBatch` | Physical material identity, quality and availability |
| `Measurement` | Arm-scoped raw/processed measurement with run/spec/device/material/QC lineage |
| `Phenotype` | Biological interpretation of valid physical Measurements from exactly one ExperimentArm |
| `PhenotypeComparison` | Explicit assessor-stated comparison between two admitted arm phenotypes |
| `FailureAttribution` | Explicit arm-level review against a criterion, with unconfirmed mechanism hypotheses |
| `ActiveLearningDecision` | Content-addressed feedback-screening decision in a fixed campaign/context, with full feedback history and next-experiment bridge |
| model/analysis record | Tool/model identity, version, inputs and parameters |

Target lineage:

```text
HostProfile
  → HostState H(t)
  → PhageProfile + InteractionEvidence
  → InteractionPrediction
  → CandidateSet
  → scientific source(s) / intent
  → ExperimentSpec + ExperimentArm(s)
  → MaterialBatch
  → arm-scoped Measurement
  → Phenotype
  → PhenotypeComparison / FailureAttribution
  → ActiveLearningDecision
  → next ExperimentSpec
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

## InteractionPrediction

InteractionPrediction v1 is the only domain layer allowed to emit probability-shaped interaction outputs. It binds one exact HostState record/hash to one exact PhageProfile ID plus a SHA-256 fingerprint of the serialized profile content. It also records the exact pairwise InteractionEvidence IDs supplied to the predictor and exact producer/model provenance.

The fixed v1 targets are:

- `P(adsorption)`;
- `P(productive infection)`;
- `P(resistance emergence)`.

Each target is a `ProbabilityEstimate` with one of two states:

- `estimated`: requires probability in [0,1], uncertainty lower/upper bounds that contain the point estimate, and a named uncertainty method;
- `not_estimated`: all probability/uncertainty numeric fields must be null.

This distinction prevents missing models from being represented by arbitrary priors or fake precision.

Creation-time lineage checks require every supplied InteractionEvidence record to match the same phage, host genome and (when present) HostProfile. Evidence observed after HostState.as_of is rejected to prevent temporal leakage. Pairwise evidence may be empty for a genuinely unseen pair because a feature-based model must be able to generalize; the absence remains explicit in the prediction lineage/limitations.

The repository includes an `evidence_only_unresolved_prediction` adapter. It preserves PHIST or other source signals but deliberately emits `not_estimated` for all three probabilities. It is a migration/boundary tool, not a biological model.

A calibrated biological predictor is not yet implemented. External or future model output can be ingested only when it supplies all probability/uncertainty fields plus mechanistic explanation, limitations and producer identity/version/parameters. Optional model artifact SHA-256 can pin exact weights/artifacts.

## Natural-phage recommender / CandidateSet

`recommend_natural_phages` consumes one exact HostState, a pool of PhageProfiles and explicitly chosen InteractionPredictions. It never reads PHIST rank or manufactures probabilities. CandidateSet v1 records the full pool, including deferred and excluded entries, not only the selected subset.

Each evaluation pins the profile ID/content fingerprint and provenance kind, embeds the complete prediction snapshot (including its ID/hash, model, uncertainty and limitations), and records disposition, selection basis and reasons. The set pins HostState ID/hash, policy name/version, candidate budget, exploration reservation and decision time. Loading checks the hash and recomputes the policy decision. Input order does not affect the result.

The `natural-phage-screening` v1 policy:

1. admits natural and retrieved profile records while explicitly retaining the retrieved-origin caveat; excludes engineered records;
2. excludes profiles with no prediction, rather than silently inventing an unresolved record;
3. sorts eligible productive-infection estimates by descending uncertainty lower bound; identical bounds use profile ID as a non-biological tie-break;
4. reserves `exploration_slots` for productive-infection `not_estimated` candidates, ordered by profile ID without an efficacy rank;
5. fills unused capacity from the other queue up to `max_candidates` and records every unselected eligible entry as deferred.

All-unresolved pools therefore support exploratory screening. `exploration_slots=0` removes the reservation but still permits exploration to fill unused capacity. A probability of zero is an estimate, not missing information; no efficacy threshold is inferred. Empty pools or entirely excluded pools yield an explicit empty decision, not a negative phenotype.

Estimated candidates must share exact producer/version/parameters/model artifact and uncertainty method. Different model cohorts are rejected instead of ranked together. This is a necessary comparability check, not proof of calibration or equivalent assay context. Callers must establish those scientific preconditions. Adsorption and resistance estimates remain available in the embedded predictions but are not combined into a synthetic score. Material readiness, safety, receptor diversity, compatibility and expected information gain are outside this baseline.

Exact HostState and profile fingerprints must match. Ambiguous duplicate profiles, competing predictions per phage, duplicate prediction IDs, predictions outside the pool and predictions later than the decision time are rejected. Missing pairwise evidence remains explicit in the prediction and evaluation reasons.

`experiment_spec_from_candidate_set` creates a host-only control plus an independent single-phage treatment arm for every selected profile, using caller-declared objective, readouts and common conditions. The spec pins CandidateSet ID/hash; the set transitively pins H(t) and predictions. Empty decisions cannot produce a screening spec. This adapter does not synthesize a cocktail or dispatch hardware and requires no orchestration/device/MaterialBatch changes.

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

ExperimentSpec v2 is the implemented boundary between scientific design and execution. It freezes explicit ExperimentArms, each with role, target HostProfile, 0/1/N phages, conditions and expected readouts. CocktailDesign and CandidateSet are optional source artifact types rather than required parents. It also freezes the abstract operation/dependency workflow, scientific objective/questions and execution constraints.

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

`FailureAttribution v1` records an explicit assessor judgment against a declared criterion for one phage-containing treatment arm. Outcome is `failure_observed`, `failure_not_observed` or `inconclusive`. Negative Phenotype has no automatic success/failure interpretation. A criterion recorded here is not evidence of pre-registration.

The artifact preserves full ExperimentSpec, Measurement, Phenotype and optional PhenotypeComparison snapshots. Construction and loading re-admit every source Measurement through the existing physical/QC-valid Phenotype gate and verify host/phage/arm/material/spec lineage. Comparisons must involve the target arm and bind the exact supplied phenotype contents. All source Measurements must be referenced; other-arm phenotypes require a comparison with the target. Source timestamps must precede the assessments that use them.

No hypotheses means `mechanism_status=unknown`. An assessor may attach adsorption / intracellular / kinetics / other hypotheses only to an observed failure, with exact reviewed-result references, rationale and limitations. These remain `hypothesized`, never automatically confirmed. The result remains scoped to the whole treatment arm, including a cocktail; there is no inferred member-level failure, host-state mutation, probability update, engineering recommendation or automatic next experiment. ActiveLearner is a separate consumer, not part of this artifact.

Feedback creates a new design/version; it does not overwrite previous experimental lineage.

## Current module mapping

| Module | Role |
| --- | --- |
| `biology.py` | FASTA validation and genome summary |
| `host_profile.py` | HostProfile v1 |
| `host_state.py` | HostState H(t) v1, temporal lineage and artifact-evidence adapters |
| `phage_profile.py` | PhageProfile v1 and retrieved/natural/engineered provenance |
| `interaction_evidence.py` | InteractionEvidence v1 and PHIST adapter |
| `interaction_prediction.py` | InteractionPrediction v1, calibrated probability contract, uncertainty and exact input lineage |
| `natural_phage_recommender.py` | CandidateSet v1, prediction-aware screening with unresolved exploration, and single-phage ExperimentSpec adapter |
| `cocktail_design.py` | CocktailDesign v1 and conservative PHIST screening baseline |
| `experiment_spec.py` | ExperimentSpec v2, ExperimentArm, generic scientific intent and optional source binding |
| `material_batch.py` | MaterialBatch v1 and test-ready material binding |
| `measurement.py` | Measurement v2, arm-scoped run-report ingestion and arm-specific material lineage |
| `phenotype.py` | Phenotype v2 plus explicit PhenotypeComparison v1 |
| `active_learning.py` | Fixed-context feedback screening, cumulative decision history and next ExperimentSpec bridge |
| `snapshots.py`, `candidates.py` | Reference snapshots and retrieved candidate records |
| `sequences.py` | Accession-indexed sequences |
| `ranking.py` | PHIST ranking compatibility layer and evidence producer |
| `agents.py` | Bounded orchestration decisions |
| `workflow.py` | Validation, scheduling and recovery |
| `devices.py` | Device contract |
| `virtual_hardware.py` | Control-path device twins |
| `records.py`, `provenance.py` | Run records and provenance |

Current implementation status belongs in [README.md](../README.md).

## Feedback-driven screening

`active_learning.py` implements ActiveLearner v1 as a bounded screening heuristic. It consumes an exact CandidateSet, its initial single-phage ExperimentSpec, an explicit criterion and admitted FailureAttribution snapshots. Matching host identity alone is insufficient: source CandidateSet hash, conditions, readouts, objective, abstract workflow and constraints must match the fixed campaign context. The initial spec must correspond to the original selected single-phage members and have one host-only control.

A reviewed single-phage question leaves automatic screening regardless of whether failure was observed. Inconclusive or conflicting reviews become `needs_review`; absence of feedback remains unknown. A cocktail review remains arm-scoped and never changes individual member status. Remaining untested candidates use the existing comparable lower-bound / unresolved-exploration policy. Empty automatic selection is `abstained`, not a biological conclusion. Predictions, H(t), mechanisms and source CandidateSet dispositions are preserved rather than overwritten.

The decision embeds the original pool, initial spec and cumulative feedback, with derived per-candidate states, dispositions, reasons, exact feedback references, selection, policy name/version/budget, timestamp and content hash. Construction/load re-admits physical/QC-valid feedback and checks result lineage, criterion and time causality. Competing revisions, duplicate reviews of one experiment arm, and same-ID/different-content specs are rejected. Construction detaches caller-owned nested data, and export checks that stored snapshots have not been mutated.

`plan_next_screen(..., previous_decision=...)` revalidates the prior decision, verifies the exact campaign/criterion and temporal order, carries all previous feedback forward, and stores its exact ID/hash reference. The reference is a lineage pointer; standalone loading revalidates embedded cumulative inputs, while independent verification of the prior decision requires that referenced artifact. No background history lookup or last-write-wins revision resolution is performed.

`experiment_spec_from_active_learning()` generates a new experiment ID with one host control and independent single-phage arms, copying the fixed context and workflow and referencing the CandidateSet, decision and initial spec. It refuses abstention and backward time. It never dispatches hardware or invents assay conditions. Multiple rounds therefore work without changing the orchestrator. Virtual execution can check the control path but never supplies feedback evidence.

This closes the software feedback-selection path. It does not fit a model, update infection probabilities, establish causal mechanisms or demonstrate biological improvement. Matching declared assay context does not prove a physically unchanged host state. Human-resolved revisions, broader assay design, calibrated predictors and information-gain optimization remain separate scientific work.

## Build order

1. validate the feedback-screening loop against admitted real experimental results when available;
2. replace evidence-only unresolved records with calibrated predictors as training/evaluation data becomes available;
3. introduce prediction-driven cocktail optimization when its evidence requirements are met;
4. engineering escalation.

MaterialBatch, provenance, device abstraction and simulator detail are otherwise frozen unless one of these scientific-layer steps requires a change.

Each step should be mergeable and keep `main` runnable.

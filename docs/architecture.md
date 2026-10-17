# Architecture

Scientific components choose what to test. Orchestration executes a frozen
ExperimentSpec and records what happened. Current capabilities and planned work
belong in [README](../README.md); commands belong in [usage](usage.md).

## Objects and ownership

| Module | Artifact / responsibility |
| --- | --- |
| `host_profile.py` | Stable HostProfile identity, normalized genome hash and characterization |
| `host_state.py` | Time-indexed HostState H(t), components, evidence and previous-state pointer |
| `phage_profile.py` | PhageProfile identity and retrieved / natural / engineered provenance |
| `interaction_evidence.py`, `ranking.py` | Pairwise source signals and PHIST adapter |
| `interaction_prediction.py` | Exact H(t)/phage predictions with uncertainty and model provenance |
| `natural_phage_recommender.py` | CandidateSet, screening policy and single-phage spec conversion |
| `cocktail_design.py` | CocktailDesign and conservative PHIST screening baseline |
| `experiment_spec.py` | ExperimentSpec v2, arms, optional source references and abstract workflow |
| `material_batch.py` | Physical batch identity, QC/availability and spec binding |
| `measurement.py` | Arm-scoped device results and explicit QC admission |
| `phenotype.py` | Single-arm Phenotype and explicit PhenotypeComparison |
| `failure_attribution.py` | Assessor review against a declared criterion; mechanism hypotheses |
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

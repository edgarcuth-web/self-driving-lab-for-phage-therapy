# Working agreements

## Goal

Build a traceable Design–Build/Acquire–Test–Learn loop for phage R&D.

Scientific components decide what to test and why. The lab layer executes validated experiments and records what happened.

## Hard boundaries

### Scientific decisions vs orchestration

Scientific components may produce:

- `HostProfile`
- `PhageProfile`
- `InteractionEvidence`
- `CocktailDesign`
- `ExperimentSpec`
- `FailureAttribution`
- engineering proposals

The orchestrator handles:

- task dependencies;
- device assignment;
- dispatch;
- timeout reconciliation;
- cancellation/recovery;
- safe-state;
- execution records.

Do not let the orchestration agent invent biological conclusions or bypass `ExperimentSpec`.

### Domain objects and lineage

Treat the following as versioned objects, not anonymous dicts:

- `HostProfile`
- `PhageProfile`
- `InteractionEvidence`
- `CocktailDesign`
- `ExperimentSpec`
- `MaterialBatch`
- `Measurement`
- `Phenotype`
- `FailureAttribution`

Preserve lineage. If a design has been built or tested, later changes create a new version.

### Natural-first escalation

Default path:

1. evaluate natural phages;
2. optimize cocktail composition;
3. identify unresolved coverage/resistance gaps;
4. escalate to host-range engineering only when supported by evidence;
5. use deeper defense/counter-defense or genome-level design only when needed.

Do not treat engineering as the default entry point.

### Evidence semantics

Keep source annotation, prediction and physical measurement distinct.

- `unknown` is not an assessed negative.
- workflow success is not biological success.
- build/device failure is not a negative phenotype.
- PHIST shared-k-mer statistics are not infection probabilities.
- no PHIST match is not evidence that infection is impossible.

Every model/tool output needs tool/model identity, version, inputs and parameters.

`InteractionEvidence` is an evidence record, not a susceptibility verdict. It links a host identity and a versioned PhageProfile to one source signal. Evidence objects must remain content-addressed and reject probability-shaped fields that are not actually emitted by the source. Cohort-relative ordering such as rank belongs to ranking/design context, not pairwise InteractionEvidence.

`CocktailDesign` is a scientific design artifact, not an execution plan. Every member must reference supporting InteractionEvidence; objectives, assumptions and unresolved gaps must be explicit. A baseline may prioritize weak computational evidence, but must not relabel it as mechanistic complementarity, cross-resistance protection or efficacy.

`ExperimentSpec` is the scientific-to-orchestration boundary. It locks the exact CocktailDesign reference, target HostProfile, member PhageProfiles and abstract workflow before device assignment. In spec-bound execution, orchestration may assign/recover devices but must never add, drop or replace scientific members or alter the workflow.

`MaterialBatch` represents tracked physical material, not a database candidate or accession. A batch may exist while QC is pending; test-ready binding requires `quality_status=released`, usable availability, and explicit quality evidence. ExperimentSpec-bound real-hardware execution requires one unambiguous host batch and one unambiguous phage batch per member.

`Measurement` preserves run/device/spec/material lineage and raw device output. Its QC status is explicit and must never be inferred from workflow success. Virtual run output may be ingested as Measurement only with `evidence_class=none`.

`Phenotype` is an interpretation of admitted physical evidence. It may be created only from physical, QC-valid Measurements bound to the same ExperimentSpec and material set. Invalid, pending or virtual Measurements must never become positive, negative or graded biological phenotypes.

### Virtual hardware

Virtual hardware may simulate job lifecycle, timeout, cancellation, failover, safe-state and artifact handoff.

It must not create biological evidence. A virtual run may carry MaterialBatch IDs for lineage testing and may be ingested as a Measurement, but it must remain `evidence_class=none` and must never imply material consumption or support Phenotype.

### Sequence and external models

Raw FASTA and headers are not sent to external models by default. Local bioinformatics tools may consume sequence; external reasoning components receive structured data unless explicitly required otherwise.

`PhageProfile` provenance kinds are `retrieved`, `natural`, and `engineered`.
`retrieved` describes record provenance and must not be treated as proof of natural biological origin.
`natural` requires local collection/isolate lineage. `engineered` requires design identity and parent profile lineage.
Never invent database accessions for designed candidates.

## Hardware execution

`execution_mode` is explicit:

- `real_hardware`: devices declare `simulated=False`;
- `virtual_hardware`: devices declare `simulated=True`.

Never mix or silently fall back between modes.

A timeout means outcome unknown. Reconcile the original job before retrying. Retry/fail over only after cancellation is confirmed.

Real drivers declare `safe_state`. If the device cannot confirm its physical state, record it as `unknown`.

Never execute model-generated code directly on devices.

For an ExperimentSpec-bound run, the agent interface is limited to `assign_devices()` and recovery. Legacy `plan()` candidate selection is permitted only on the compatibility path without an ExperimentSpec.

## Current code map

- `biology.py`: FASTA validation and sequence summary.
- `host_profile.py`: HostProfile v1.
- `phage_profile.py`: PhageProfile v1 and provenance variants.
- `interaction_evidence.py`: InteractionEvidence v1 and PHIST evidence adapter.
- `cocktail_design.py`: CocktailDesign v1 and conservative PHIST screening baseline.
- `experiment_spec.py`: ExperimentSpec v1, CocktailDesign freezing and candidate binding.
- `material_batch.py`: MaterialBatch v1 and test-ready ExperimentSpec binding.
- `measurement.py`: Measurement v1 and run-report ingestion.
- `phenotype.py`: Phenotype v1 from admitted physical Measurements.
- `snapshots.py`, `candidates.py`, `sequences.py`: reference data and retrieved candidates.
- `ranking.py`: PHIST integration; emits legacy ranking plus InteractionEvidence.
- `agents.py`: bounded orchestration decisions.
- `workflow.py`: validation, scheduling and recovery.
- `devices.py`, `virtual_hardware.py`: device interface and twins.
- `records.py`, `provenance.py`: run records and provenance.

## Next work

Priority order:

1. host-characterization analyzers;
2. FailureAttribution and active learning;
3. engineering escalation.

Do not expand robot simulation unless it supports one of these steps.

## Development

Python 3.11+.

```bash
python -m unittest discover -s tests -v
```

Keep README for user-facing scope/status, `docs/architecture.md` for domain architecture, and this file for implementation constraints.

Do not commit credentials, raw user genomes or generated run directories.

Before GitHub writes, inspect the current branch head and diff. Preserve concurrent work and never force-push over another contributor's changes.

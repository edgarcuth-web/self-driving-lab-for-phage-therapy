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

### Virtual hardware

Virtual hardware may simulate job lifecycle, timeout, cancellation, failover, safe-state and artifact handoff.

It must not create biological evidence. Measurement-shaped test data should come from explicit fixtures or historical-data replay.

### Sequence and external models

Raw FASTA and headers are not sent to external models by default. Local bioinformatics tools may consume sequence; external reasoning components receive structured data unless explicitly required otherwise.

Generated/engineered phages and retrieved natural phages use different provenance. Never invent database accessions for designed candidates.

## Hardware execution

`execution_mode` is explicit:

- `real_hardware`: devices declare `simulated=False`;
- `virtual_hardware`: devices declare `simulated=True`.

Never mix or silently fall back between modes.

A timeout means outcome unknown. Reconcile the original job before retrying. Retry/fail over only after cancellation is confirmed.

Real drivers declare `safe_state`. If the device cannot confirm its physical state, record it as `unknown`.

Never execute model-generated code directly on devices.

## Current code map

- `biology.py`: FASTA validation and sequence summary.
- `host_profile.py`: HostProfile v1.
- `snapshots.py`, `candidates.py`, `sequences.py`: reference data and natural candidates.
- `ranking.py`: PHIST integration.
- `agents.py`: bounded orchestration decisions.
- `workflow.py`: validation, scheduling and recovery.
- `devices.py`, `virtual_hardware.py`: device interface and twins.
- `records.py`, `provenance.py`: run records and provenance.

## Next work

Priority order:

1. host-characterization analyzers;
2. PhageProfile;
3. InteractionEvidence;
4. CocktailDesign;
5. ExperimentSpec integration;
6. real measurement / phenotype ingestion;
7. FailureAttribution and active learning;
8. engineering escalation.

Do not expand robot simulation unless it supports one of these steps.

## Development

Python 3.11+.

```bash
python -m unittest discover -s tests -v
```

Keep README for user-facing scope/status, `docs/architecture.md` for domain architecture, and this file for implementation constraints.

Do not commit credentials, raw user genomes or generated run directories.

Before GitHub writes, inspect the current branch head and diff. Preserve concurrent work and never force-push over another contributor's changes.

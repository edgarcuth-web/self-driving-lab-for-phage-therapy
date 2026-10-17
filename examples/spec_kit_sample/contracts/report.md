# Contract: Run Report

**Status**: FROZEN — only the integrator may change this file.

**Producer**: a run writes `runs/<run-id>/report.json`.

## Top-level keys (verified from a real run)

```
schema_version  started_at        status            simulated
execution_mode  physical_execution agent            sample_id
results         recoveries        error             limitations
source          genome            candidates        candidate_sources
candidate_ranking                candidate_snapshots
plan            plan_ranking      physical_state    evaluation
run_id          finished_at       events_file
```

## Fields the dashboard reads

The dashboard reads only these and ignores the rest:

| Field | Purpose |
| --- | --- |
| `status` | Top-level status light |
| `execution_mode` / `simulated` / `physical_execution` | **Always-visible honesty markers** |
| `plan` | Selected candidates and device assignment |
| `results` | Measurement readings |
| `evaluation` | Contains `biological_conclusion` |
| `limitations` | Rendered directly in the UI; never hidden |

## Non-negotiable rendering rule

`limitations` MUST be shown on screen. It is the evidence for the project's honesty claim, not something to cosmeticize. `evaluation.biological_conclusion` MUST NOT be upgraded from `not_assessed` by the UI.

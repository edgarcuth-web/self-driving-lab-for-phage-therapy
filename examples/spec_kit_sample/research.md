# Phase 0 Research: Two-Round Closed Loop with Live Dashboard

**Feature**: `001-round2-loop-dashboard`（样例目录：`examples/spec_kit_sample/`，非正式特性）

All findings below were measured against this repository on 2026-10-17 (not inferred).

## Decision: Use a repository-local snapshot fixture

- **Rationale**: The INPHARED download endpoint returned **403 Forbidden** for both HEAD and GET; `data/snapshots/` did not exist. A live download would fail on stage.
- **Alternatives rejected**: (a) retry live download at demo time — non-deterministic and already proven to fail; (b) commit a full snapshot — large and unnecessary.
- **Evidence**: 403 on INPHARED HEAD/GET; `data/snapshots/` absent.
- **Resolution**: Commit a minimal fixture under `examples/fixtures/` and ingest via the local-file path.

## Decision: Build the dashboard from the standard library

- **Rationale**: The repository had **no web code at all** (no Flask/FastAPI/`http.server` usage). Adding a framework violates the "no new frameworks without concrete need" constraint.
- **Alternatives rejected**: Flask/FastAPI — new dependency, unnecessary for a single-page SSE dashboard.
- **Evidence**: no web modules present; `AGENTS.md` forbids needless frameworks.

## Decision: Drive the demo with the rule-based agent

- **Rationale**: No OpenRouter key was configured. The demo must be offline and deterministic.
- **Alternatives rejected**: LLM-driven planning at demo time — network/key dependent, non-deterministic.
- **Evidence**: OpenRouter key unset.

## Decision: Keep PHIST out of the demo path

- **Rationale**: PHIST is not installed and is an optional external tool; installing it on stage is an incident risk.
- **Evidence**: PHIST unavailable locally.

## Verified: Event stream schema

A `virtual_hardware` run produced **16 events** with the shape `{seq, at, run_id, event, details}`. Event names observed:

```
run_started → source_identified → input_validated → devices_discovered
→ planning_requested → plan_accepted
→ (job_submitted → device_job_completed → step_completed) × N
→ run_finished
```

The full schema and the unknown-event rule are frozen in [`contracts/events.md`](./contracts/events.md).

## Verified: Run report top-level keys

A run produced `runs/<run-id>/report.json` with these top-level keys:

```
schema_version  started_at        status            simulated
execution_mode  physical_execution agent            sample_id
results         recoveries        error             limitations
source          genome            candidates        candidate_sources
candidate_ranking                candidate_snapshots
plan            plan_ranking      physical_state    evaluation
run_id          finished_at       events_file
```

The dashboard reads only `status`, `execution_mode`, `simulated`, `physical_execution`, `plan`, `results`, `evaluation`, `limitations`. Frozen in [`contracts/report.md`](./contracts/report.md).

## Verified: End-to-end offline path

The following path was executed successfully:

```
local snapshot TSV
  → fetch-snapshot --from-file          exit 0, sha256 recorded
  → candidates --host "Escherichia coli" returns 3 provenance-bearing candidates
  → run --execution-mode virtual_hardware  16 events, status=succeeded,
                                            report.md/json + events.jsonl produced
```

Observed first-round signal: `mean_virtual_signal = 0.1672`, `biological_conclusion = not_assessed`. This is consistent with the constitution: simulated readings are not biological evidence.

## Verified: Console encoding

On Windows PowerShell, Chinese output is garbled unless `PYTHONIOENCODING=utf-8` (or `chcp 65001`) is set. All demo output must be forced to UTF-8.

## Open technical risk: Python version

This development machine runs Python **3.10.11**, while the repository's test gate and this feature require **Python 3.11+**. `T000` must verify this before implementation; the Spec Kit CLI itself was installed with a uv-managed Python 3.11.17.

## Open items for `/speckit.clarify`

- The explicit round-two selection rule (threshold for removal, definition of "complementary", ordering).
- Port-conflict behavior for the one-command demo.
- Whether the "ignore unknown events" rule has a dedicated test.

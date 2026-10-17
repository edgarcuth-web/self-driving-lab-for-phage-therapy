# Implementation Plan: Two-Round Closed Loop with Live Dashboard

**Branch**: `001-round2-loop-dashboard`（样例：该分支不存在） | **Date**: 2026-10-17 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/examples/spec_kit_sample/spec.md`（样例，非 `specs/` 正式编号位）

## Summary

Add a second feedback round that changes the next design based on the first round's measured signal, expose the whole loop through a local real-time dashboard, and make the entire two-round demo runnable with one offline command. Implementation uses the Python standard library only; all interface shapes are frozen in `contracts/`.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: Python standard library only (no new frameworks)

**Storage**: Filesystem — `runs/<run-id>/report.json`, `runs/<run-id>/events.jsonl`

**Testing**: `unittest` (`python -m unittest discover -s tests -v`)

**Target Platform**: Windows (PowerShell) and Linux

**Project Type**: CLI + local web service

**Performance Goals**: Full two-round demo completes in under 30 seconds

**Constraints**: Offline; zero API keys; zero environment variables; no new dependencies

**Scale/Scope**: Two rounds; small local fixture; single user, single machine

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
| --- | --- | --- |
| I. Truth Over Demo | Simulated readings are never presented as biological evidence; limitations rendered | PASS |
| II. Frozen Domain Contracts | No change to `ExperimentSpec` arms/membership/workflow; versioned artifacts preserved | PASS |
| III. Execution Honesty | Explicit execution mode; no silent fallback; virtual = `evidence_class=none` | PASS |
| IV. Demonstrable and Offline | Zero network/key/env-var demo; honesty markers always visible | PASS |
| V. Testable Delivery | Every task has one runnable command; merge gate defined | PASS |

**Post-Phase-1 re-check**: PASS — no violations; no complexity justification required.

## Project Structure

### Documentation (this feature)

```text
examples/spec_kit_sample/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── spec.md              # Feature specification
├── tasks.md             # Phase 2 output (/speckit.tasks)
├── checklists/
│   └── requirements.md  # Spec-quality checklist
└── contracts/
    ├── events.md
    ├── report.md
    ├── sse.md
    ├── round2-delta.md
    └── demo-entrypoint.md
```

### Source Code (repository root)

```text
phage_lab/
├── feedback.py          # Round-two feedback loop and selection strategy
├── demo.py              # NEW: one-command end-to-end orchestration
├── server.py            # NEW: SSE server (stdlib http.server)
└── ...                  # Existing domain modules unchanged

web/                     # NEW: single-page dashboard (no build step)
examples/fixtures/       # NEW: committed offline snapshot fixture
tests/                   # Existing unittest suite (+ feedback/server tests)
scripts/smoke.sh         # NEW: end-to-end smoke gate
```

**Structure Decision**: Single project. Preserve the existing `phage_lab/` package layout and add only `demo.py`, `server.py`, a static `web/` directory, and a fixture. No new framework or build pipeline.

## Module Ownership

| Owner | Files |
| --- | --- |
| Core backend | `phage_lab/feedback.py`, `phage_lab/demo.py`, `tests/test_feedback.py` |
| Dashboard frontend | `web/**`, `phage_lab/server.py` |
| Science & data | `examples/fixtures/**` |
| QA | `tests/**` (except feedback test), `scripts/smoke.sh` |
| Integrator | `examples/spec_kit_sample/**`, `contracts/**`, merge actions |

Shared files require the integrator. No agent edits a file it does not own.

## Contracts

| Contract | File | Frozen content |
| --- | --- | --- |
| Event stream | [`contracts/events.md`](./contracts/events.md) | `{seq, at, run_id, event, details}`, 16 event names, unknown-event rule |
| Run report | [`contracts/report.md`](./contracts/report.md) | Top-level keys; dashboard read fields |
| SSE | [`contracts/sse.md`](./contracts/sse.md) | Endpoints, frame format, first-frame snapshot |
| Round-two delta | [`contracts/round2-delta.md`](./contracts/round2-delta.md) | `delta_from_previous` shape |
| Demo entrypoint | [`contracts/demo-entrypoint.md`](./contracts/demo-entrypoint.md) | One-command signature and guarantees |

Contracts are frozen. Only the integrator may change them, and a change must synchronize `spec.md` FRs and `tasks.md` criteria.

## Risks

| Risk | Status | Mitigation |
| --- | --- | --- |
| INPHARED 403 | Measured | Commit offline fixture; use local-file ingest |
| No web code exists | Measured | Dashboard is the core work of this feature |
| Chinese console garbling | Measured | Force `PYTHONIOENCODING=utf-8` / `chcp 65001` |
| No OpenRouter key | Measured | Demo uses the rule agent only |
| Concurrent edits to `workflow.py` | Structural | Exclusive file ownership + frozen contracts |
| PHIST not installed | Optional dependency | Keep it out of the demo path |
| Python < 3.11 | To verify | `T001` environment check |
| Port already in use | Runtime | Defined in `contracts/sse.md` / edge cases |

## Complexity Tracking

No constitution violations. No additional projects, patterns or abstractions are introduced.

---
description: "Task list for the two-round closed loop and live dashboard"
---

# Tasks: Two-Round Closed Loop with Live Dashboard

**Input**: Design documents from `/examples/spec_kit_sample/`（样例，非 `specs/` 正式编号位）

**Prerequisites**: plan.md, spec.md, research.md, contracts/

**Tests**: Each task's acceptance criterion is a runnable command (constitution Principle V). Tests are included where they are the criterion.

**Organization**: Grouped by user story so each story is independently implementable and testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependencies)
- **[Story]**: US1–US5, mapping to `spec.md`
- Exact file paths are included.

## Path Conventions

Single project: `phage_lab/`, `web/`, `tests/`, `scripts/` at repository root.

---

## Phase 1: Setup (Shared Infrastructure)

- [ ] **T001** Verify runtime: `python --version` is **3.11+** (blocker if not).
- [ ] **T002** Add offline fixture `examples/fixtures/inphared-mini.tsv` (columns include Accession / Description / Host); verify with
  `python -m phage_lab fetch-snapshot --snapshot /tmp/snap --source inphared --version smoke --from-file examples/fixtures/inphared-mini.tsv --source-uri local` → exit 0.
- [ ] **T003** [P] Confirm the frozen event contract in `contracts/events.md` matches a real `runs/<id>/events.jsonl` (16 events).

---

## Phase 2: Foundational (Blocking Prerequisites)

**⚠️ No user story work begins until this phase is complete.**

- [ ] **T004** Ensure `run` produces `runs/<id>/events.jsonl` with the frozen `{seq, at, run_id, event, details}` shape.
  **Criterion**: `python -m unittest discover -s tests -v` includes a passing event-schema test.
- [ ] **T005** Ensure `runs/<id>/report.json` contains the top-level keys in `contracts/report.md`.
  **Criterion**: a passing test asserting the key set.
- [ ] **T006** Create `phage_lab/demo.py` skeleton with CLI entrypoint.
  **Criterion**: `python -m phage_lab demo --help` → exit 0.

**Checkpoint**: foundation ready; user stories can proceed.

---

## Phase 3: User Story 1 — Two-Round Closed Loop (Priority: P1) 🎯 MVP

**Goal**: Round two's selection changes because of round one's measured signal, with recorded rationale.

**Independent Test**: Produce two rounds; the second report references the first and records added/removed with reasons.

- [ ] **T007** [US1] Implement round-two selection in `phage_lab/feedback.py`.
  **Criterion**: `python -m unittest tests.test_feedback` passes.
- [ ] **T008** [US1] Emit `delta_from_previous` per `contracts/round2-delta.md` in the round-two report.
  **Criterion**: round-two `report.json` contains `added`, `removed`, `reason_field`.
- [ ] **T009** [P] [US1] Add `tests/test_feedback.py` covering: lowest-signal candidate removed; delta recorded; empty-selection abstains explicitly.
  **Criterion**: `python -m unittest tests.test_feedback -v`.

**Checkpoint**: US1 is independently testable.

---

## Phase 4: User Story 2 — Live Dashboard (Priority: P1)

**Goal**: A browser shows design → build → test → learn as ordered events, cold-starting from a full snapshot.

**Independent Test**: A single run is visible; first frame is non-empty; unknown events are ignored.

- [ ] **T010** [US2] Implement SSE server in `phage_lab/server.py` per `contracts/sse.md`.
  **Criterion**: `curl -N localhost:8080/api/events` first frame contains a full snapshot.
- [ ] **T011** [P] [US2] Build `web/` single-page dashboard consuming SSE; render `status`, `plan`, `results`, `evaluation`, `limitations`.
  **Criterion**: page renders a completed run; `limitations` visible.
- [ ] **T012** [US2] Handle unknown event names by ignoring them.
  **Criterion**: `python -m unittest tests.test_server` includes a passing unknown-event test.

**Checkpoint**: US2 is independently testable.

---

## Phase 5: User Story 3 — One-Command Offline Demo (Priority: P2)

**Goal**: A clean clone with no env vars runs both rounds within 30 seconds and prints a dashboard address.

**Independent Test**: Run the entrypoint in a clean shell with no network.

- [ ] **T013** [US3] Wire `phage_lab/demo.py` to run round one, round two, then serve the dashboard, per `contracts/demo-entrypoint.md`.
  **Criterion**: `python -m phage_lab demo --host "Escherichia coli" --port 8080` prints a URL and completes both rounds.
- [ ] **T014** [US3] Make failures exit non-zero with a readable Chinese reason (no stack trace).
  **Criterion**: with the fixture removed, the command exits non-zero and prints a Chinese reason.

**Checkpoint**: US3 is independently testable.

---

## Phase 6: User Story 4 — Honesty Markers (Priority: P2)

**Goal**: Execution truthfulness and limitations are always visible.

**Independent Test**: In any dashboard state, the four honesty markers are on screen.

- [ ] **T015** [US4] Render `simulated` / `execution_mode` / `physical_execution` / `limitations` persistently in `web/`.
  **Criterion**: visual check plus an automated assertion that the rendered HTML contains all four markers.

**Checkpoint**: US4 is independently testable.

---

## Phase 7: User Story 5 — Offline Snapshot Input (Priority: P3)

**Goal**: Ingest a committed local snapshot and keep provenance.

**Independent Test**: Ingest with no network and record a hash.

- [ ] **T016** [US5] Record sha256 in the snapshot provenance during ingest.
  **Criterion**: the snapshot manifest contains a sha256 equal to a separately computed hash.
- [ ] **T017** [US5] Assert ingest makes no network call.
  **Criterion**: a test or stub proves no `urllib`/`requests` network access during local-file ingest.

**Checkpoint**: US5 is independently testable.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [ ] **T018** Add `scripts/smoke.sh` running the full offline demo.
  **Criterion**: `scripts/smoke.sh` → exit 0.
- [ ] **T019** Clean-clone acceptance: `git clone` → one command → dashboard shows both rounds within 30 s.
- [ ] **T020** [P] Run `/speckit.analyze` and resolve all cross-artifact inconsistencies.
- [ ] **T021** [P] Run `/speckit.converge`; append and implement any remaining tasks until Converged.
- [ ] **T022** Merge gate: `python -m unittest discover -s tests -v` green **and** `scripts/smoke.sh` passing.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies.
- **Foundational (Phase 2)**: depends on Setup; BLOCKS all user stories.
- **US1 / US2 (P1)**: after Foundational; can proceed in parallel by different owners.
- **US3 (P2)**: depends on US1 + US2.
- **US4 (P2)**: depends on US2 (dashboard exists).
- **US5 (P3)**: after Foundational.
- **Polish**: depends on all desired stories.

### User Story Dependencies

- US1: independent after Foundational.
- US2: independent after Foundational.
- US3: integrates US1 + US2.
- US4: extends US2.
- US5: independent after Foundational.

### Within Each Story

- Tests (where the criterion is a test) fail before implementation.
- Models/data before services; services before endpoints; core before integration.

### Parallel Opportunities

- T003 can run with T001–T002.
- T009 can run with T007–T008 (different files).
- US1 and US2 can be worked in parallel once Foundational is green.
- T011 can run in parallel with T010 (frontend vs server, different files).

---

## Implementation Strategy

### MVP First (US1 only)

1. Phase 1 Setup → 2. Phase 2 Foundational → 3. Phase 3 (US1) → **validate delta independently** → demo if ready.

### Incremental Delivery

Setup + Foundational → US1 (MVP) → US2 (dashboard) → US3 (one command) → US4 (honesty markers) → US5 (offline input) → Polish.

## Notes

- `[P]` = different files, no dependencies.
- A task is complete only when its runnable criterion passes.
- Do not mark a task complete because the code "looks done".

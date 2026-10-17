# Feature Specification: Two-Round Closed Loop with Live Dashboard

> **样例说明（非正式 spec）**：本目录是 Spec Kit 流程的**样例/演练产物**，不是已立项特性。
> 无 issue 编号、未实现、未占用 `specs/` 的正式编号位；`tasks.md` 中 T001–T022 全部未执行。
> 来源与处置见同目录 [`README.md`](./README.md)。

**Feature Branch**: `001-round2-loop-dashboard`（样例：该分支不存在）

**Created**: 2026-10-17

**Status**: Draft

**Input**: User description: "把当前的实验室流水线做成可演示的两轮自主闭环，并提供实时看板；全程离线、虚拟硬件、零 API key。"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Two-Round Closed Loop (Priority: P1)

As an evaluator or researcher, I can see the second round's design change **because of** the first round's measured signal, and the change is shown with its rationale.

**Why this priority**: A single round is a pipeline, not a self-driving lab. The second round is the core value of this project.

**Independent Test**: Implement only this story and the system still produces two rounds where the second report references the first and records what changed and why.

**Acceptance Scenarios**:

1. **Given** round one completed with a report, **When** round two starts, **Then** the second report references the first run and lists added/removed selections with reasons.
2. **Given** one candidate had the lowest signal in round one, **When** round two selection is produced, **Then** that candidate is removed or de-prioritized and the change is recorded.
3. **Given** both rounds exist, **When** they are compared, **Then** the delta is determinable without reading source code.

---

### User Story 2 - Live Dashboard (Priority: P1)

As an evaluator, I can watch design → build → test → learn happen in real time, with measurements clearly marked as simulated.

**Why this priority**: The dashboard is the demonstration itself; without it the system is invisible.

**Independent Test**: Implement only this story and a single run is visible in a browser as ordered events.

**Acceptance Scenarios**:

1. **Given** the dashboard cold-starts, **When** it connects to the event stream, **Then** the first frame is a complete snapshot rather than empty.
2. **Given** the run continues, **When** new events occur, **Then** the dashboard updates incrementally.
3. **Given** an unknown event name arrives, **When** the dashboard receives it, **Then** it is ignored and the dashboard does not crash.

---

### User Story 3 - One-Command Offline Demo (Priority: P2)

As a demo operator, on a clean clone with no environment variables configured, I can run one command and get the full two-round loop within 30 seconds.

**Why this priority**: Evaluators judge "one command works", not three separate demos.

**Independent Test**: On a clean environment, the command completes without network or secrets.

**Acceptance Scenarios**:

1. **Given** a clean clone and no environment variables, **When** the entrypoint command runs, **Then** both rounds complete within 30 seconds and a dashboard address is printed.
2. **Given** required input is missing, **When** the command runs, **Then** it exits non-zero and prints a readable reason (no stack trace).
3. **Given** the demo runs, **Then** it makes no external network request.

---

### User Story 4 - Honesty Markers (Priority: P2)

As an evaluator, I can always tell this is virtual hardware and not biological evidence.

**Why this priority**: The project's differentiator is that it refuses to overclaim.

**Independent Test**: In any dashboard state, execution mode and limitations are visible.

**Acceptance Scenarios**:

1. **Given** any dashboard state, **Then** execution mode, simulated flag, physical-execution flag and limitations are always visible.
2. **Given** the report contains limitations, **Then** they are rendered rather than hidden.

---

### User Story 5 - Offline Snapshot Input (Priority: P3)

As a data role, I can use a snapshot file committed to the repository as input and keep its provenance.

**Why this priority**: External snapshot download is unreliable (403 measured).

**Independent Test**: Ingest a local file and record its hash, with no network.

**Acceptance Scenarios**:

1. **Given** a local snapshot file, **When** ingest runs, **Then** it succeeds and records a sha256.
2. **Given** no network, **When** ingest runs, **Then** it still succeeds.

---

### Edge Cases

- What happens when the dashboard port is already in use?
- What happens when the event stream disconnects and reconnects — is the first frame still a full snapshot?
- What happens when the fixture is missing a required column or is empty?
- What happens when a device job times out — is physical state recorded as unknown?
- What happens when round two has no candidate to add — is "abstain" expressed explicitly rather than an empty error?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST support two rounds, where round two explicitly references round one's result.
- **FR-002**: Round-two selection MUST record added/removed candidates and the reason relative to round one.
- **FR-003**: The system MUST emit an ordered event stream consumable by the dashboard; unknown event names MUST NOT fail the dashboard.
- **FR-004**: The system MUST emit a structured run report including status, execution mode, physical-execution flag, results and limitations.
- **FR-005**: The system MUST provide one command that runs the end-to-end two-round demo with no network, secrets or environment variables.
- **FR-006**: On failure the system MUST exit non-zero and print a human-readable reason.
- **FR-007**: The system MUST always display execution truthfulness and limitations.
- **FR-008**: The system MUST ingest from a local snapshot file and preserve provenance including a hash.
- **FR-009**: The system MUST NOT mark or interpret simulated readings as biological conclusions.

### Key Entities

- **Experiment Run**: one execution — run id, mode, timestamps, results, limitations.
- **Run Report**: structured outcome read by the dashboard and audit.
- **Run Event**: ordered event record driving the dashboard.
- **Selection Delta**: round-two change relative to round one, with reasons.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On a clean clone with no environment variables, the full two-round loop plus dashboard is available within 30 seconds.
- **SC-002**: The dashboard's first frame on cold start contains the complete current state (non-empty).
- **SC-003**: The demo performs zero external network requests and requires zero API keys.
- **SC-004**: Unknown event names cause dashboard failure 0 times (ignored and continue).
- **SC-005**: Every run produces an auditable report and event stream.

## Assumptions

- The demo runs on virtual hardware; no biological conclusion is claimed.
- Python 3.11+ is available; otherwise it must be upgraded first.
- The external snapshot source is unavailable, so a repository-local fixture is used.
- Single machine, single user, no concurrent writes.

## Dependencies

- Interface schemas are defined in [`contracts/`](./contracts/); this specification intentionally avoids implementation details.

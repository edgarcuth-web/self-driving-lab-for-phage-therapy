# self-driving-lab-for-phage-therapy Constitution

## Core Principles

### I. Truth Over Demo (NON-NEGOTIABLE)

Unknown is not negative. Workflow success is not biological success. PHIST statistics are not infection probabilities. Missing calibrated predictions remain `not_estimated`; any estimated probability MUST carry uncertainty bounds/method and exact model/input provenance. Source annotation, prediction, physical measurement and assessor interpretation MUST remain distinct and MUST NOT impersonate one another.

### II. Frozen Domain Contracts (NON-NEGOTIABLE)

The domain contracts in `AGENTS.md` and `docs/architecture.md` are authoritative and non-negotiable: `ExperimentSpec` arms, membership and workflow are frozen during execution/recovery; versioned artifact IDs, hashes, provenance and time ordering are preserved; changing a built/tested design creates a new version; physical execution requires test-ready `MaterialBatch` binding and an explicit, independent QC admission. This constitution does not restate those contracts; on conflict they win.

### III. Execution Honesty

Execution mode MUST be explicit (`real_hardware` or `virtual_hardware`); never mix or silently fall back, and driver `simulated` flags must match. Virtual hardware validates lifecycle and lineage only: `evidence_class=none`, no material consumption, no Phenotype support. Reconcile timed-out jobs before retrying; record unconfirmed physical state as unknown and preserve safe-state handling.

### IV. Demonstrable and Offline

Every deliverable MUST be demonstrable with zero network, zero API keys and zero environment variables; demos use `--agent rule` with a local fixture. Honesty markers (`simulated` / `execution_mode` / `physical_execution` / `limitations`) MUST remain always visible on the dashboard and MUST NOT be hidden or cosmeticized.

### V. Testable Delivery (NON-NEGOTIABLE)

Every task MUST carry an acceptance criterion a reviewer can verify without trusting the author. Prefer one runnable command; when the outcome is inherently visual, use a **named manual check plus an archived screenshot artifact** stored with the feature. An unrecorded visual glance, or any criterion that is always green, is no criterion. The merge gate is: `python -m unittest discover -s tests -v` green AND `scripts/smoke.sh` passing. A summary is input, never a decision.

## Additional Constraints

- Do not add frameworks, schema migrations or compatibility aliases without a concrete need (see `AGENTS.md`).
- Do not commit credentials, raw user genomes or generated run directories.
- Without an explicit user request, agents MUST NOT run `git add`, `git commit` or `git push`. Open a branch only after an issue number exists. PRs use `Refs #N`; never `Closes`/`Fixes`.
- Do not execute model-generated code directly on devices; raw FASTA and headers stay local by default.

## Development Workflow

The development loop is: constitution → specify → clarify → plan → checklist → tasks → analyze → implement → converge (Spec Kit). After the interface contract is frozen, only the integrator/maintainer may change it. Shared files are owned exclusively by one role; changes require the integrator.

## Governance

This constitution is subordinate to `AGENTS.md` and `docs/architecture.md`; where they conflict, they prevail. Amendments require: (1) a entry in the decision record, (2) synchronizing affected `spec.md`/`plan.md`/`tasks.md`, and (3) integrator review. All PRs/reviews must verify compliance; complexity must be justified.

**Version**: 1.0.0 | **Ratified**: 2026-10-17 | **Last Amended**: 2026-10-17

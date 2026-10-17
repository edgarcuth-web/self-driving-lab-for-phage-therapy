# Working agreements

Build a traceable Design–Build/Acquire–Test–Learn loop for phage R&D.
Read [docs/architecture.md](docs/architecture.md) for the domain contracts and
[docs/usage.md](docs/usage.md) for CLI inputs. Keep those contracts when refactoring.

## Required boundaries

- Scientific components choose what to test; orchestration assigns devices and executes frozen intent. Never change ExperimentSpec arms, membership or workflow during execution/recovery.
- Preserve versioned artifact IDs, hashes, provenance and time ordering. Changes to built/tested designs create new versions; do not silently replace same-ID content.
- Keep source annotation, prediction, physical measurement and assessor interpretation distinct. Unknown is not negative; workflow success is not biological success; PHIST statistics are not infection probabilities.
- Missing calibrated predictions remain `not_estimated`. Estimated probabilities require uncertainty bounds/method and exact model/input provenance.
- Preserve CandidateSet exclusions, deferred candidates, prediction snapshots and selection reasons. Do not compare incompatible model cohorts or assign efficacy meaning to profile-ID ordering.
- HostState components require explicit evidence. New states never inherit dynamic components implicitly; lineage adapters do not infer biological state.
- Physical execution requires test-ready MaterialBatch binding. QC admission is explicit, independent of execution success. Phenotype requires physical, QC-valid, same-arm/spec/material Measurements.
- Failure review remains arm-scoped and criterion-based. Mechanism hypotheses are not confirmed causes; cocktail outcomes are not member outcomes.
- Learning labels are explicit assessor declarations tied to exact prediction/spec/physical Phenotype lineage. Never infer a target label from phenotype polarity. Calibration reports are descriptive and must not fit, replace or silently recalibrate a model.
- Feedback screening preserves its fixed campaign/context, criterion and history. Conflicts/inconclusive reviews require review; empty selection abstains. No automatic model, probability or HostState update.
- Prefer evaluating natural phages, then cocktails; engineering requires an explicit evidence gap. Retrieved record provenance alone does not establish natural origin.

## Execution and data

- Require explicit `real_hardware` or `virtual_hardware`; never mix or silently fall back. Driver `simulated` flags must match.
- Virtual hardware tests lifecycle and lineage only: `evidence_class=none`, no material consumption, no Phenotype support.
- Reconcile timed-out jobs before retrying. Retry/fail over only after confirmed cancellation or completion. Record unconfirmed physical state as unknown and preserve safe-state handling.
- Never execute model-generated code directly on devices. Raw FASTA and headers stay local by default; external reasoning receives structured data.
- Keep legacy candidate selection isolated from spec execution. New execution integrations use ExperimentSpec.
- Do not commit credentials, raw user genomes or generated run directories.

## Issue rules

- Open an issue only when the user asks. Treat a new report as feedback on
  already-shipped behaviour and align it with the existing issue first.
- Resolve what the repository can answer yourself; do not run a question loop
  inside the issue. Ask one minimal question list only when the fact is outside
  the repository (real instrument, live device, external network, missing data),
  then stop and wait.
- Get an issue number first, then create a branch scoped to that issue. Do not
  edit `main` directly.
- Merge is not completion. The user closes the issue after acceptance; agents
  do not close it.

## PR rules

- Do not run `git add`, `git commit` or `git push` unless the user explicitly asks.
- One issue per branch and pull request. Reference the issue with `Refs #N`;
  never use `Closes` or `Fixes`.
- Keep the change scoped to that issue and keep the frozen domain contracts in
  this file and [docs/architecture.md](docs/architecture.md).
- Match verification to the change scope. The full gate is
  `python -m unittest discover -s tests -v`, which must be green before merge.

## Change loop (SDD/TDD)

- Every change starts from an issue number on a branch scoped to that issue.
- Write the failing criterion or test first and confirm it goes red before implementing.
- Implement the smallest change that turns the criterion green while keeping the frozen contracts above.
- Run the full gate `python -m unittest discover -s tests -v`; it must be green before merge.
- Open one pull request per issue with `Refs #N`. Merge is not completion; the user closes the issue after acceptance.
- This file is the source of truth for the change process; `docs/hackathon/` describes the event setup, not day-to-day process.

## Windows tooling

- On Windows, before the first GitHub operation, check `gh` and install it
  when missing: `powershell -ExecutionPolicy Bypass -File scripts/setup-windows.ps1`.
  The script installs only what is absent — pinned `gh` from its official
  release URL (SHA-256 verified) into `.tools/`, and pinned `specify-cli`
  via `uv` when scaffold-level Spec Kit work needs it.
- `deps/windows/README.md` holds download links and checksums, not binaries.
  Keep extracted tools in `.tools/` (git-ignored). Never commit installers,
  extracted binaries, tokens or credential files.
- `gh auth login` is interactive. Never write tokens or credential files into the
  repository.
- Spec Kit is checked in (`.specify/`, `specs/`, agent command files). The
  `specify` CLI is optional — the `/speckit*` commands run from the committed
  `.specify/scripts/` helpers without it. Install it only for CLI-level work
  (adding agent integrations, extensions, upgrades), using the version pinned in
  `.specify/init-options.json`:
  `uv tool install "specify-cli==1.2.1" --python 3.11`.

## Development

Python 3.11+, standard library. Run from the repository root:

```bash
python -m unittest discover -s tests -v
```

Keep shared mechanics small; retain domain validation in domain modules. Do not add
new frameworks, schema migrations or compatibility aliases without a concrete need.

README owns current capability/status and a runnable local check. Architecture owns
domain contracts and module relationships. Usage owns command examples. This file
owns development constraints; do not duplicate the other documents here.

Freeze material/provenance/device/simulator scope unless a scientific requirement
forces a change. Before GitHub writes, inspect the current branch head and diff.
Preserve concurrent work and never force-push over another contributor's changes.

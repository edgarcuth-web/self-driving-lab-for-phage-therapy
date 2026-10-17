# Working agreements

## Goal and scope

Build a hackathon prototype that runs a simulated phage-screening workflow,
encounters an instrument fault, recovers when the state permits, and reports
the outcome. Keep the one-command offline demo working.

## Architecture

- `phage_lab/biology.py`: FASTA validation and explicitly synthetic candidates.
- `phage_lab/agents.py`: offline policy and optional OpenRouter API decisions.
- `phage_lab/devices.py`: device contract, manifests, asynchronous simulators.
- `phage_lab/workflow.py`: fixed task template, validation, scheduler, recovery.
- `phage_lab/records.py`: append-only events and final JSON/Markdown reports.
- `phage_lab/provenance.py`: runtime source fingerprint, with optional Git metadata.
- `phage_lab/dashboard.py`: loopback HTTP server, run management and artifact reads.
- `phage_lab/web/`: buildless HTML/CSS/JS dashboard for actual scheduler events.
- `phage_lab/__main__.py`: command-line entry point.

## Invariants

- All instruments, synthesis requests, candidates and assay results are simulated.
  Never present synthetic scores as infection probabilities or efficacy evidence.
- Label the interface **MHS-inspired**, not an implementation of the official
  unpublished specification. Keep the local contract documented.
- Agent output is untrusted structured data. Validate device capabilities,
  candidate IDs and recovery actions before execution; never execute model code.
- A timeout means the outcome is unknown. Reconcile the job first. Reuse a
  completed result; require acknowledged cancellation before retry/failover.
- Unknown/unreachable state must produce a failure report, not duplicate work.
- Keep a stable logical command ID across attempts. Reject conflicting payloads
  for the same ID. Bound retries and preserve dependency order.
- The default is offline and needs no API key. API mode must be explicitly
  selected, must fail clearly on configuration/API errors, and must never
  silently fall back to the offline policy.
- Do not store credentials, raw user genomes, or generated run data in Git.
  OpenRouter receives summary metadata only, not FASTA contents or headers.
- Simulation determinism concerns decisions and generated values, not run IDs,
  event timestamps or wall-clock timing. Live model decisions can vary.
- ZIP downloads must work without Git. Record the source fingerprint on new runs;
  never guess a commit for a historical run or a ZIP.
- Bind the dashboard only to loopback. Keep Host/Origin and per-session mutation
  token checks; never return API keys or accept arbitrary filesystem paths.
- Panel API settings are process-local and never persisted or logged. Capture the
  configuration when constructing a run's agent; reject edits during active runs.
  Do not mutate environment variables or treat a saved config as verified API access.
- Render model output and report data as text, never HTML. Use the actual event
  stream for UI state; label offline and live modes accurately.

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
  `python -m unittest discover -s tests -v` on the interpreter required by
  `## Development`. Read `## Verification on this branch` before quoting a gate
  result: this branch has no CI and its gate is red at the base commit.

## Change loop (SDD/TDD)

- Every change starts from an issue number on a branch scoped to that issue.
- Write the failing criterion or test first and confirm it goes red before implementing.
- Implement the smallest change that turns the criterion green while keeping the frozen contracts above.
- Run the full gate `python -m unittest discover -s tests -v` and compare the
  failing test IDs with the base commit; the change must not add failures (see
  `## Verification on this branch`).
- Open one pull request per issue with `Refs #N`. Merge is not completion; the user closes the issue after acceptance.
- This file is the source of truth for the change process. Do not restate this loop in other documents; keep one description.

## Verification on this branch

This is the demo branch, not `main`, and its verification facts differ:

- **No CI.** `.github/workflows/` exists only on `main`. Nothing here is checked
  by GitHub, so a pull request against this branch never reports a check status.
  An absent check is neither pending nor passing; run the gate yourself.
- **The gate is red at the base commit.** `python -m unittest discover -s tests -v`
  runs 43 tests and fails before any change: 12 failures + 4 errors in
  `test_workflow.RunTests`, `test_workflow.DeviceTests` and
  `test_dashboard.DashboardTests`, plus a flaky dashboard test that adds a
  thirteenth failure in some runs (measured 2026-10-17, Python 3.10.11, Windows).
- **So the gate is differential.** Record the failing test IDs on the base commit
  and on the change, and state the diff in the pull request. The requirement is
  no new failures and no unexplained disappearance, not an absolute green.
- **State the interpreter.** That measurement used Python 3.10.11, below the
  3.11+ required by `## Development`. Report the version you used instead of
  implying the supported one.
- Green on `main` remains the merge gate there. Where a Spec Kit artifact's
  merge gate cannot be met here (no `scripts/smoke.sh` on this branch,
  pre-existing failures), say so in the pull request instead of restating it as
  satisfied.

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
- Spec Kit SDD artifacts are checked in: `.specify/` (templates, scripts,
  constitution), `.kilo/command/` (agent commands) and `examples/spec_kit_sample/`
  (a frozen worked example, not an approved feature). Real features live under
  `specs/NNN-<name>/`; `/speckit.specify` creates that directory and the
  per-checkout `.specify/feature.json` pointer, which is git-ignored. To point the
  tooling at an existing feature, set `SPECIFY_FEATURE_DIRECTORY` or write that
  pointer.
- The `specify` CLI is optional — the `/speckit*` commands run from the committed
  `.specify/scripts/` helpers without it. Install it only for CLI-level work
  (agent integrations, extensions, upgrades), using the version pinned in
  `.specify/init-options.json`:
  `uv tool install "specify-cli==1.2.1" --python 3.11`.

## Development

Python 3.11+; standard library only for the first milestone. Avoid new services,
frameworks or dependencies unless the task needs them. Keep user instructions
short, in Chinese, and separate offline setup from API setup.

Dashboard assets are buildless; do not introduce npm dependencies just for layout.
The Windows ZIP entry point is `start-dashboard.bat`; the CLI is
`python -m phage_lab dashboard`. Test via ephemeral local HTTP servers. Browser
visual QA must be reported separately from API or JavaScript syntax checks.

Run from repository root:

```bash
python -m unittest discover -s tests -v
python -m phage_lab demo --seed 42 --time-scale 0.1
```

Test failure semantics and public behavior: hanging tasks, lost acknowledgments,
unreachable devices, idempotency, malformed model output, and report integrity.
Do not claim live API verification unless an actual authorized request succeeded.

For GitHub changes, inspect the current branch head before updating it. Preserve
other contributors' work and never force-push over concurrent changes.

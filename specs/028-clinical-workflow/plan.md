# Implementation plan — Refs #28

Use Python standard-library loopback static serving and plain HTML/CSS/JavaScript.
The browser-only model owns fixture data, DAG dependencies and scenario clock.
UI rendering uses textContent, avoiding raw metadata HTML. The workflow stays
offline; optional Kimi reports submit explicitly labeled structured summaries via
the local server after API configuration. No data or credential persistence.
Do not restore the removed simulation backend.

Write HTTP boundary tests and Node behavior tests first; capture their red result.
Implement the isolated model, presentation, CLI entry and Windows launcher. Verify
branch parallelism, reset, report truthfulness and unavailable candidate handling.
Run Python full gate, Node tests, JS syntax and browser checks separately.

Baseline: before edits on Windows/Python 3.11, with PYTHONUTF8=1, 302 tests ran:
one CRLF fixture byte-count failure, three temporary event-file cleanup errors,
one skip. Without UTF-8 the existing provenance subprocess also fails in this
Chinese checkout path. Do not change scientific code to mask baseline problems.

The constitution mentions scripts/smoke.sh, which is absent on main. The added
scoped offline smoke command runs dashboard HTTP/model checks and JS syntax.
Full core-suite baseline problems are reported separately in verification/README.md.

Follow-up implementation: clinical_reports.py validates/minimizes terminal inputs,
calls the fixed Kimi Code `k3` endpoint, and holds deduplicated asynchronous jobs in
memory. Token/Host/Origin checks protect configuration and report submission.
report-ui.js owns optional automatic generation, polling, explicit retries,
stale-result detachment and Markdown export. No scientific contract changes.

Demonstration follow-up: pure tourFrame/timelineOf/reviewOf derivations in the
existing browser model; presentation CSS and app controls for narrated playback,
chapter stepping, pause, automatic focus and independent report status. Reuse
existing fixtures, API configuration and static assets; no new dependencies.

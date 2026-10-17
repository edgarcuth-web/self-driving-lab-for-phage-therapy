# Verification — Refs #28

Date: 2026-10-17. Base: dad81da. Branch: codex/28-clinical-workflow-ui.

## Red → green

Before implementation, the Python dashboard check failed with
`ModuleNotFoundError: phage_lab.dashboard`; the Node model check failed with
`MODULE_NOT_FOUND: workflow-model.js`. System Node is 16.16.0, which cannot run
`--test`; model checks used the bundled Node 24.19.0, with no package installation.

Passed after implementation:

- `python -m unittest discover -s tests -p test_dashboard.py -v`: 3/3.
- `node --test tests/test_dashboard_model.cjs`: 5/5 using Node 24.19.0.
- `node --check phage_lab/web/app.js`: passed.
- `scripts/smoke.sh`: passed via Git Bash with NODE_BIN pointing to bundled Node.
- `git diff --check`: passed.

## Full Python regression

Run with `PYTHONUTF8=1` in the Windows Chinese-path checkout. 305 tests ran:
300 passed, 1 skipped, 1 failed, 3 errored. The identical four problems occurred
before implementation (302 tests) on main:

- `test_candidates.SnapshotTests.test_snapshot_records_identity_and_reloads`:
  Windows CRLF write produces 569 bytes versus expected 563.
- `test_workflow.DeviceTests.test_completion_during_agent_decision_is_not_repeated`
- `test_workflow.DeviceTests.test_retry_limit_is_enforced_when_faults_persist`
- `test_workflow.DeviceTests.test_unacknowledged_cancellation_cannot_trigger_retry`

The latter three error on temporary `events.jsonl` cleanup with WinError 32.
The full merge gate is therefore **not green**; no merge, commit or push performed.

## Named browser checks (actual UI, separate from automated tests)

Browser viewport: 923 × 874 CSS pixels (narrow desktop), in-app browser.

| Check | Observed result | Evidence |
| --- | --- | --- |
| Desktop overview / parallel branches | At D+2, all three isolates returned; phage and antibiotic matching both running. All eight nodes visible in compact desktop canvas. | [parallel-desktop.png](parallel-desktop.png) |
| Independent antibiotic completion | At D+3, antibiotic candidates returned for all three isolates while phage preparation remains running. | [antibiotic-output.png](antibiotic-output.png) |
| Complete workflow | Stepping through D+10/11/12/13 completes eight nodes; read-only domain stages stay illustrative. | [completed-desktop.png](completed-desktop.png) |
| Unmatched sample | Both match nodes require review; preparation/design/test/learn blocked. | [unmatched-desktop.png](unmatched-desktop.png) |
| Pause / continue / reset | Real playback started and paused at D+2.2; scenario time remained D+2.2 after further checks. Reset restored D+0, empty outputs/events. | UI accessibility observations |
| Metadata edits / text rendering | A markup-shaped sample ID rendered literally; zero img elements created. Updating metadata reset the workflow. Restored normal fixture afterward. | UI accessibility and DOM observations |
| JSON download | Browser downloaded clinical-workflow-mixed.json; file inspection confirmed eight succeeded nodes, scenario_day=13, simulated=true, physical_execution=false, evidence_class=none, presentation_only. | Actual browser download and filesystem inspection |

Below-700px phone layout and a wide desktop viewport were not visually checked.
For this initial offline-only validation, no live API, external database, real
hardware or scientific inference was tested. The later Kimi extension below adds
an explicitly configured network report path; the workflow remains local.

## Kimi K3 report extension (2026-10-17)

Official API/model documentation:
[Kimi Code models](https://www.kimi.com/code/docs/kimi-code/models.html).
Fixed endpoint: `https://api.kimi.com/coding/v1/chat/completions`; model `k3`.
No alternate model, spoofed client identity or fallback report is used.

Red criteria: missing `phage_lab.clinical_reports` module; missing config route
returned 404. Green checks: 5 dashboard HTTP tests, 9 report-service tests,
5 workflow-model tests, 2 async report-client tests, both JS syntax checks,
Python compile and `git diff --check`. `scripts/smoke.sh` passes with bundled
Node 24.19.0. All report unit tests mock upstream I/O and need no credentials.
Final full Python regression: 316 tests, 311 passed, 1 skipped, the same original
1 CRLF fixture failure and 3 Windows temporary-file cleanup errors listed above.
The full merge gate remains not green; no commit, push or merge was performed.

Actual authorized live checks used the supplied key only in server-process memory:

1. Completed synthetic mixed-sample snapshot → actual Kimi response `model=k3`,
   8 report sections, server completion at 2026-10-17T06:26:06Z.
2. Browser completed all 8 nodes using step controls. The terminal transition
   automatically submitted a new run, showed “K3 生成中”, then “草稿已生成”.
   Actual returned model `k3`, generation at 2026-10-17 14:27:06 Asia/Shanghai;
   input hash starts `cf81566bad41`.
3. Report contains all 3 synthetic isolates, PHG-DEMO/ABX-DEMO candidates, evidence
   limitations and physician-review items. It makes no physical-execution claim.
4. Browser downloaded a 4,254-character Markdown file. File inspection confirmed
   model identity, simulation labels, source SHA-256 and absence of key prefixes.
   No generated report or credential was copied into the repository.
5. [kimi-report.png](kimi-report.png) shows the actual model-generated report,
   model/time/hash, source metadata and narrative. This is browser visual QA,
   separate from the mocked API tests.

The supplied key is not present in repository files, response JSON, screenshots,
Markdown or browser storage. Session configuration is cleared on server restart.
Real clinical records, external isolation databases and physical evidence were
not tested. Generated reports remain simulated clinical-format drafts.

## Report tables and copy actions

Red criteria initially found zero tables instead of three, and no complete-report
copy action. Green: all four report-client tests pass, including preserved
unmatched rows, independent module clipboard contents, full-report contents and
explicit feedback when clipboard access is denied. The complete scoped smoke
command passes 5 HTTP + 9 report-service + 5 workflow + 4 report-client checks,
plus JS syntax checks.

Browser checks on a real generated K3 report confirmed 3 semantic tables, all
3 isolates, 4 phage candidates and 4 antibiotic candidates. Every module and the
report header has a top-right copy action. All four actions were tested by copying
and pasting into a local input (without submitting it); contents matched the
selected module or full report. The original field value was restored afterward.
Table data comes from the source snapshot; model paragraphs stay grouped below
their corresponding tables. Markdown export uses the same three tables.
Final browser layout at 736 CSS pixels: each table viewport and content is
392 pixels wide, with all four columns visible. Archived screenshots:
[table modules](report-tables.png) and [complete report copy action](report-copy-header.png).
A fresh Markdown download was inspected and contains all three four-column tables.

## Fragment detection and unnamed-signal review

Scientific framing references: [clinical assay validation](https://pmc.ncbi.nlm.nih.gov/articles/PMC6499319/)
and [clinical mNGS interpretation](https://pmc.ncbi.nlm.nih.gov/articles/pmid/30355154/).
These motivate separate sequence-support/background/identification concepts;
they do not validate the prototype's invented weights, scores or synthetic data.

Red checks: missing `detectionOf`; missing minimized detection report fields.
Green checks: deterministic synthetic fragments, score changes across evidence
profiles, no clinical-probability claim, unknown species remain unassigned, no
automatic candidates for the mixed sample's unresolved signal, fragment bases
stripped at the report API boundary, and report/copy rendering of unknown signals.
Scoped smoke: 5 HTTP + 10 report-service + 7 workflow-model + 5 report-client tests.

Actual browser: mixed fixture produces candidate support scores 96.7 / 89.7 /
64.0, with one unresolved signal scored 62.6. These are explicitly uncalibrated
0–100 support scores, not probabilities. The unknown signal has no species
assignment and no automatic phage/antibiotic match. Single fixture shows zero
unknowns; unmatched fixture shows zero named candidates and one unknown signal.
No results appear before detection completion. Expanded fragment panels remain
open across subsequent scenario steps. The graph contains an 02B review card
directly below detection, outside the eight core execution tasks.

[fragment-detection.png](fragment-detection.png) archives the actual unknown-signal
review, metrics and paired artificial query/reference sequences. Two 60 nt
representative fragments per record are generated deterministically; no real
reference genome, gene accession or validated PCR target was used.

The full Python gate ran 317 tests: 312 passed, 1 skipped, the identical baseline
1 CRLF fixture failure and 3 Windows file-cleanup errors. No merge was performed.
An actual K3 report from the new flow contains confidence scores and a separate
unnamed-signal table, explicitly retaining species_assignment=null and review
status. [unnamed-report.png](unnamed-report.png) archives that report. Inspection
of the downloaded report's source JSON confirmed no query/reference sequence
fields and no automatic matches for UNCL-001; physical_execution remains false.

## Presentation mode and narrated case tour

Red: the four new presentation tests failed because tourFrame/timelineOf/reviewOf
did not exist. Green: 5 HTTP + 10 report-service + 7 workflow-model + 4 presentation
+ 5 report-client checks pass (31 total), as do syntax and whitespace checks.
The full Python gate remains 317 tests, 312 passed, 1 skipped, 1 known CRLF
fixture failure and the same 3 Windows event-file cleanup errors. Full output:
`%TEMP%/phage-presentation-full-tests.log`. No merge, commit or push performed.

Browser checks used the actual loopback page in the in-app browser. Presentation
mode hides the sidebar and API configuration, fits the graph (1207px viewport and
1207px content), highlights both matching branches, and keeps the narrated story
and chapter controls visible during focus changes. [presentation-workflow.png](presentation-workflow.png)
shows the complete graph in the available desktop viewport.
[presentation-timeline.png](presentation-timeline.png) shows independent D+3
antibiotic completion alongside the D+3–10 seven-day preparation window.

Chapter stepping, real autoplay, pause/resume, case switching and exit were
checked. The paused clock remained at 00:58 / D+3.0 while other checks ran. Single
case reached D+13 with zero unresolved signals; mixed case retained 2 review items;
unmatched case stopped at D+3 with preparation blocked. Leaving the tour restored
manual inspection; leaving presentation mode restored the sidebar. Raw inspector
JSON defaults to a collapsed disclosure. A tour ending is independent of the
actual asynchronous report job; no placeholder is presented as a generated report.

The mixed case continued through its remaining chapters using real 6× autoplay,
finished at 02:12 / D+13, triggered K3 automatically, displayed generating status,
then displayed an actual completed K3 draft. [presentation-report.png](presentation-report.png)
archives the result. Downloaded Markdown:
`Downloads/clinical-report-b60a239f-e811-4cba-a18f-1566d5242c6b.md`.
The tour ends independently of API latency. Clicking a node explicitly leaves
the tour and opens manual inspection; the final browser check verified a visible
sample inspector and hidden tour controls, then reset to a fresh D+0 case with
automatic reporting enabled.

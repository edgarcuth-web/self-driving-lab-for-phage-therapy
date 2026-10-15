# Architecture and v0.2 contract

## Responsibilities

| Component | Owns |
|---|---|
| `biology.py` | Validate FASTA; hash normalized contigs; generate synthetic candidate scores |
| `agents.py` | Select 2–3 offered candidates, assign compatible devices, propose recovery |
| `workflow.py` | Validate decisions; enforce dependencies; reconcile and bound attempts |
| `devices.py` | Discoverable manifests; asynchronous jobs; one in-flight job per device |
| `records.py` | Ordered append-only events, partial results and final reports |
| `provenance.py` | Source SHA-256 and optional Git commit; works without `.git` |
| `dashboard.py` | Loopback HTTP API, single active run, uploads, history and downloads |
| `web/` | Buildless dashboard; actual events drive displayed state |

The task template is fixed: `synthesize`, `prepare`, `transfer`, `infect`, `measure`.
Each task depends on the preceding task. This first milestone schedules one
logical sample sequentially. The simulator uses two devices per capability.

All five operations are abstract simulation stages. They do not contain real
laboratory quantities, timings, synthesis sequences or vendor integrations.

## DeviceDriver: our local interface

This is an **MHS-inspired** Python contract, not an official MHS API, network
transport or SDK. Public MHS material informs discovery and descriptive metadata.
MCP exposure, real drivers and official schema alignment are future work.

| Method | Behavior |
|---|---|
| `describe()` | Device ID, supported operations, simulation flag, capacity and notes |
| `read(job_id=None)` | Device availability or authoritative job state and result |
| `write(Command)` | Validate and submit an asynchronous job; return a job ID |
| `wait(job_id)` | Await acknowledgment; waiting can time out without cancelling the job |
| `cancel(job_id)` | Return true only after cancellation is confirmed; false if already completed |

`Command` contains a logical command ID, operation, payload and attempt number.
The payload contains only a simulated sample ID and candidate IDs. The controller
validates candidate membership; the driver validates its operation and payload
shape and enforces its one-job capacity. No model-generated code is executed.

Driver instances keep a per-command ledger in memory. Same ID and payload returns
the existing job, even after completion. A conflicting payload is rejected.
A higher attempt number can create a new job only after the previous attempt has
acknowledged cancellation. On another device the scheduler enforces this condition.
This does not claim distributed exactly-once execution or durability across restarts.

## Recovery state machine

1. Submit the task and wait with a deadline.
2. On timeout, query the original job before asking for recovery.
3. If it succeeded, reuse its result. A lost response must not duplicate an order.
4. If it is still running, ask the agent for `cancel_and_retry`,
   `cancel_and_failover` or `abort`.
5. Validate the action and target device. Require cancellation acknowledgment.
6. If completion races with cancellation, re-read and use the completed result.
7. Once cancellation is confirmed, retry with the same logical command ID and a
   new attempt number, or quarantine the old device and choose the validated backup.
8. Unknown state, invalid decisions or exhausted attempts stop the run and preserve
   partial results. Simulator cleanup is never reported as remote cancellation.

The simulator's hang happens before its atomic effect. Real instruments may have
partial, irreversible effects; a future driver must expose sample disposition and
reconciliation requirements before this controller can safely support it.

## Fault injection and reproducibility

The demo injects at most one fault. Its operation is selected from the seed unless
`--fault-step` is specified. The fault type is fixed by the option or chosen by
`--fault random`. Injected faults are logged separately from controller observations;
the AI is not told which hidden fault was injected.

- `hang`: job remains running until confirmed cancellation.
- `response-lost`: job succeeds but the acknowledgment is withheld.
- `unreachable`: the job cannot be queried or cancelled; report an unknown outcome.

Candidate scores depend on the input's normalized fingerprint. Synthetic readings
depend on the seed and selected IDs, independently of ranking scores and device
attempts. Therefore a failover does not magically improve the measured value.
These values are test fixtures, not a mechanistic model or predicted probabilities.

## Data and reports

FASTA contents and headers remain local and are never copied into run records.
The normalized fingerprint, length and contig count are recorded. In live mode
these metadata, candidate fixtures, manifests and observed device states are sent
to OpenRouter and the selected provider; the raw genome is not sent.

`events.jsonl` is flushed after each append. `report.json` and `report.md` are written
via temporary files at a terminal state. Power loss or forced process termination
can still prevent a final report; restart/resume is not implemented. Each run has
a distinct directory, so a later run does not overwrite the earlier report.

`succeeded` means all template steps returned successfully. Biological efficacy
is always `not_assessed`. When any step is missing, the report quality is `incomplete`.

## Dashboard and local API

`python -m phage_lab dashboard` serves `http://127.0.0.1:8765`. The controller is
the same `run_demo` used by the CLI. It runs in a worker thread, while a lightweight
event callback identifies the active run. Each browser polls the ordered file-backed
events every 500 ms. Refreshes and server restarts can read saved reports.

| Route | Purpose |
|---|---|
| `GET /api/status` | Connection state, configured model ID, source identity, local mutation token |
| `POST /api/config` | Set an in-memory API key/model or clear this process's configuration |
| `POST /api/runs` | Start a validated run; return 409 while another run is active |
| `GET /api/runs` | Up to 20 recent runs from the configured output directory |
| `GET /api/runs/<id>?after=<seq>` | Events newer than the cursor and final report when available |
| `GET /api/runs/<id>/download/<filename>` | Only report.md, report.json or events.jsonl |

The server enforces loopback Host/Origin checks and a process-scoped token on writes.
It does not expose API keys or accept output/input path strings from the browser.
API settings live in process memory (user-facing rules: [openrouter.md](openrouter.md)); each
live run receives an agent constructed from a snapshot of the current configuration.
User FASTA contents (up to 1 MB) are staged in a temporary local file for the run
and removed afterward. Run IDs and filenames are constrained; symlinked reports
and directories are refused. This is a local demo server, not a shared hosted service.

The UI renders decision text as text, never HTML, and loads no external assets.
Only one run can be active per dashboard process; durable resume and cross-process
resource locking are not implemented.

## Source identity without Git

Every new run records `source.version`, `source.source_sha256`, `source.source_files`,
`source.git_commit` and `source.git_dirty`. Git fields are null for ZIP downloads or
when Git is unavailable. A parent directory's unrelated repository is not used.
The fingerprint hashes a sorted manifest of runtime Python, web assets, example
input and the Windows launcher after CRLF normalization. Run data, secrets and
user genomes are excluded. It is a content identity, not a signature or proof that
an earlier historical run used that code. Existing records are not rewritten.

## Source references

- [Anthropic: Previewing the Model Hardware Standard](https://www.anthropic.com/news/model-hardware-standard-research-preview)
- [MHS research-preview access](https://modelhardwarestandard.com/)
- [OpenRouter Tool Calling](https://openrouter.ai/docs/guides/features/tool-calling)

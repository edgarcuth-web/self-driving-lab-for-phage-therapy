# Architecture

## System boundary

项目把"科学输入是否真实"和"硬件是否真实"分开处理。

实验路径中的 candidate records 必须带可追溯的外部来源。硬件执行则有两个显式模式：

- **`real_hardware`**：真实设备 adapter，manifest 必须声明 `simulated=false`。没有提供 adapter 时直接拒绝运行。
- **`virtual_hardware`**：软件 device twin，manifest 必须声明 `simulated=true`。没有物理动作，输出不构成实验数据。

`execution_mode` 没有默认值。调用方没说清楚期望哪种硬件，就什么都拿不到；模式切换必须显式发生，系统不会从 real hardware 静默 fallback 到 virtual hardware。

## Components

| Component | Responsibility |
|---|---|
| `biology.py` | FASTA validation and privacy-preserving input summary |
| `devices.py` | Generic command/device contract |
| `workflow.py` | Candidate provenance, execution-mode validation, scheduling and reconciliation |
| `snapshots.py` | Pinned local copies of upstream reference data, with checksum manifests |
| `candidates.py` | Providers that read a snapshot and emit provenance-stamped candidates |
| `sequences.py` | Accession-indexed genome sequences from a pinned FASTA snapshot |
| `ranking.py` | Host-range ranking delegated to external tools |
| `virtual_hardware.py` | Software device twins |
| `agents.py` | Bounded structured planning/recovery proposals |
| `records.py` | Append-only events, reports and execution-mode disclosure |
| `provenance.py` | Runtime source identity |

## Experiment path

`run_experiment()` requires:

- FASTA/input reference;
- caller-owned sample ID;
- externally supplied candidate records with provenance;
- workflow/dependency definition;
- planner;
- an explicit execution mode.

For `virtual_hardware`, callers may pass `devices=None`; the workflow then creates no-fault software twins for the declared operations. These twins carry real candidate IDs through the orchestration stack, but every reading stays marked `simulated` with `evidence: "none"`.

For `real_hardware`, callers must provide concrete device adapters.

## Candidate provenance

Admission is an allowlist. Every candidate record must carry, as nonempty strings:

| Field | Meaning |
|---|---|
| `source_db` | the external database the record came from |
| `accession` | that database's identifier for it |
| `retrieved_at` | ISO 8601 timestamp of retrieval |
| `source_uri` | a URI the record can be traced back to |

The previous denylist rejected `SIM-` prefixes and a `synthetic_fixture` source label. That only stops fixtures that label themselves honestly — a hand-written record with an invented `source` string passed it. Positive provenance is the invariant; naming conventions are not.

Records produced from a pinned snapshot additionally carry `snapshot_version` and `snapshot_sha256`. Both or neither — half a reference is not traceable — and `require_snapshot` makes the pair mandatory for a run. They are not required of every candidate: an isolate from a lab's own collection has a real source and no snapshot.

`--candidates` reads records someone else retrieved, so without a provider its provenance is only as honest as the file's author; `--require-snapshot` is what rules out hand-written records.

## Snapshots

A snapshot is one upstream file, downloaded once, hashed, and described by a `manifest.json` beside it. Loading one re-hashes the data file and refuses it if the digest moved, so a local copy that was edited, truncated or swapped fails closed rather than quietly changing what a run sees.

Downloading is a separate command from running: the orchestrator never reaches the network mid-run. `--from-file` registers a file fetched by hand, for networks that cannot reach the source; `--source-uri` still records where the data came from upstream.

## Providers

A provider turns a host description into candidate records and stamps each with the snapshot's provenance. It reports what the source database records and nothing more: no score, no ranking, no infection probability.

`InpharedProvider` reads an INPHARED metadata export. INPHARED's column spellings have shifted between releases, so columns resolve by alias against normalized headers, and a missing required column raises with the headers that were actually present rather than silently yielding nothing.

Its host field is the depositor's annotation. Records expose it as `recorded_host` with `host_annotation_source: depositor_metadata`, because an annotation of where a phage was found is not a measurement of what it can infect. Ranking by predicted host range is a separate piece of work against independently validated tools.

## Ranking

Candidate order comes from a named external tool or it does not exist.

`PhistRanker` shells out to PHIST, which counts exact k-mer matches between each candidate phage genome and the host genome. Ranking therefore needs sequences, which metadata snapshots do not carry, so it reads a second snapshot: an upstream multi-FASTA, pinned the same way, indexed by accession into byte offsets cached beside it.

If the tool is missing or fails, ranking raises. There is no heuristic fallback, because an ordering presented as a ranking while nothing ranked it is worse than no ordering at all. `report["candidate_ranking"]` states which case a run was in, naming the tool, version, parameters and host genome digest, or saying `source_order` with an explicit note that the order carries no biological meaning.

### What a ranking block may and may not say

A statistic is not a probability. Shared k-mers correlate with host range without measuring it, so every block carries that caveat in `interpretation`, and validation rejects any field in the block whose name reads as a probability, likelihood, success, efficacy or infectivity. Nothing converts a p-value into a success probability.

A tool that reports no match for a candidate has found no signal, which is not evidence that infection cannot occur. Such candidates keep a block with `reported: false` and no rank. `report["plan_ranking"]` lists any selected candidate the tool did not support, so a reader can tell a top-ranked pick from one that merely sat near the top.

Ranks from different tools or different host genomes are refused together, and so is a partly ranked set: ordering some candidates and not others makes the unranked ones look worse than the tool actually said.

## Selection size

How many candidates a plan may select is part of the experiment spec (`selection_size`, default 1–3), not a constant. A single phage and a six-member cocktail are both legitimate experiments, and the bound is passed to both the plan validator and the planning context so the agent sees the same rule the validator enforces.

## DeviceDriver

The shared contract is transport-neutral:

| Method | Meaning |
|---|---|
| `describe()` | identity, operations, state/capabilities, explicit simulated flag |
| `read(job_id=None)` | authoritative device/job state |
| `write(Command)` | submit one asynchronous command |
| `wait(job_id)` | wait for completion without implying cancellation on timeout |
| `cancel(job_id)` | confirm cancellation where supported |
| `enter_safe_state(reason)` | bring the apparatus to its declared safe state and report whether it confirmed |
| `close()` | release local driver resources |
| `quarantine()` | optional, advisory: stop routing new work here after a failover |

A future Computer Use adapter can implement the same boundary for software-controlled instruments or services. Its UI actions are still an execution transport; they do not by themselves make a virtual measurement physical evidence.

## Apparatus safety

Halting the orchestrator does not make the bench safe, so the contract separates the two.

Every non-simulated driver declares a `safe_state` block: a `policy` (`park_and_release`, `contained_hold` or `operator_required`), an explicit `retains_hazard` boolean, and a description written for whoever walks up to the apparatus. `real_hardware` refuses a driver without it, and the hazard-retaining policies cannot claim to retain none.

The controller requests `enter_safe_state()` on every abandoned step and records what each device confirmed in `report["physical_state"]`. A device that cannot be asked, does not answer, or raises is recorded as `unknown` rather than assumed safe, and the overall status is the worst device's: a person approaching the bench meets all of it, not the average. Virtual twins declare and implement the same thing, so the path is exercised before hardware exists.

This is auditability, not certification. It forces "what happens physically when this fails" to be answered and written down; it does not replace containment, a real emergency stop or institutional approval. `docs/hardware.md` carries the integration guide.

## Recovery invariant

1. Submit a stable logical command ID.
2. On timeout, query original job state.
3. Reuse completed results.
4. If still running, obtain a bounded recovery decision.
5. Require authoritative cancellation before retry/failover.
6. Stop when state is unknown rather than duplicate an irreversible action.

Virtual hardware exercises these invariants before physical equipment exists. Fault injection lives in `tests/support.py`: the control plane needs to be tested against hangs, lost responses and unreachable devices, but the shipped system has no reason to contain the means of breaking itself.

## Evidence boundary

The orchestration layer distinguishes:

- **candidate/evidence provenance** — where biological knowledge came from;
- **execution provenance** — physical hardware vs device twin;
- **result interpretation** — never inferred automatically from workflow success.

A virtual readout may be useful for UI, scheduler or model-interface testing, but it stays labeled synthetic and cannot support a biological conclusion. `evaluate()` decides which case it is from the device's own `simulated` / `physical_execution` flags, never by recognizing a unit string — a provenance check that depends on a naming convention is a lint rule, not an invariant.

## Persistence

Current artifacts are file-backed. The next infrastructure milestone is durable storage of experiment IDs, logical command IDs, remote/virtual job IDs, attempts, result provenance and reconciliation state. SQLite is sufficient for the first implementation.

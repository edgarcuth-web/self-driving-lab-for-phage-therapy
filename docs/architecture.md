# Architecture

## System boundary

项目把“科学输入是否真实”和“硬件是否真实”分开处理。

实验路径中的 candidate records 必须来自外部、可追溯的数据源；旧黑客松的 synthetic candidate fixtures 不进入这一层。硬件执行则有两个显式模式：

- **`real_hardware`**：真实设备 adapter，manifest 必须声明 `simulated=false`。
- **`virtual_hardware`**：软件 device twin，manifest 必须声明 `simulated=true`。没有物理动作，输出不构成实验数据。

另外保留 **`legacy_demo`**，其中候选、设备和读数全部模拟，只用于旧 dashboard 与回归测试。

任何模式切换都必须显式发生；系统不会从 real hardware 静默 fallback 到 virtual hardware。

## Components

| Component | Responsibility |
|---|---|
| `biology.py` | FASTA validation and privacy-preserving input summary |
| `devices.py` | Generic command/device contract |
| `workflow.py` | Candidate validation, execution-mode validation, scheduling and reconciliation |
| `simulation.py` | Virtual device twins plus isolated legacy all-synthetic demo |
| `agents.py` | Bounded structured planning/recovery proposals |
| `records.py` | Append-only events, reports and execution-mode disclosure |
| `provenance.py` | Runtime source identity |
| `dashboard.py` | Legacy demo UI during migration |

## Experiment path

`run_experiment()` requires:

- FASTA/input reference;
- caller-owned sample ID;
- externally supplied candidate records;
- workflow/dependency definition;
- planner;
- an explicit execution mode.

For `virtual_hardware`, callers may pass `devices=None`; the workflow then creates no-fault software twins for the declared operations. These twins can carry real candidate IDs through the orchestration stack, but any generated reading remains marked as simulated and `evidence=none`.

For `real_hardware`, callers must provide concrete device adapters.

## DeviceDriver

The shared contract is transport-neutral:

| Method | Meaning |
|---|---|
| `describe()` | identity, operations, state/capabilities, explicit simulated flag |
| `read(job_id=None)` | authoritative device/job state |
| `write(Command)` | submit one asynchronous command |
| `wait(job_id)` | wait for completion without implying cancellation on timeout |
| `cancel(job_id)` | confirm cancellation where supported |
| `close()` | release local driver resources |

A future Computer Use adapter can implement the same boundary for software-controlled instruments or services. Its UI actions are still an execution transport; they do not by themselves make a virtual measurement physical evidence.

## Recovery invariant

1. Submit a stable logical command ID.
2. On timeout, query original job state.
3. Reuse completed results.
4. If still running, obtain a bounded recovery decision.
5. Require authoritative cancellation before retry/failover.
6. Stop when state is unknown rather than duplicate an irreversible action.

Virtual hardware exercises these invariants before physical equipment exists.

## Evidence boundary

The orchestration layer distinguishes:

- **candidate/evidence provenance** — where biological knowledge came from;
- **execution provenance** — physical hardware vs device twin;
- **result interpretation** — never inferred automatically from workflow success.

A virtual readout may be useful for UI, scheduler or model-interface testing, but it must remain labeled synthetic and cannot support a biological conclusion.

## Persistence

Current artifacts are file-backed. The next infrastructure milestone is durable storage of experiment IDs, logical command IDs, remote/virtual job IDs, attempts, result provenance and reconciliation state. SQLite is sufficient for the first implementation.

## Legacy simulation

`simulation.run_demo()` remains intentionally all-synthetic for deterministic regression and fault-injection tests. It is separate from the hybrid experiment path even though both can reuse the same `SimulatedDevice` implementation.

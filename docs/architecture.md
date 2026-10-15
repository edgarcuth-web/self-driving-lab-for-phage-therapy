# Architecture

## System boundary

仓库有两条明确分开的执行路径：

- **Production path**: `workflow.run_experiment()`。只接受调用方提供的真实候选记录和真实设备 driver。
- **Simulation path**: `simulation.run_demo()`。仅用于测试、回归和旧 dashboard 演示。

Production path 不会发现、创建或回退到 simulator。任何带有已知 simulation 标记的输入都会在创建物理 job 之前被拒绝。

## Components

| Component | Responsibility |
|---|---|
| `biology.py` | FASTA validation and privacy-preserving sequence summary only |
| `devices.py` | Generic command and device-driver contract |
| `workflow.py` | Real-run validation, planning validation, scheduling and reconciliation |
| `simulation.py` | Synthetic candidates, virtual devices and fault injection for tests only |
| `agents.py` | Structured bounded planning / recovery proposals |
| `records.py` | Append-only event stream and final artifacts |
| `provenance.py` | Runtime source identity |
| `dashboard.py` | Legacy local simulation dashboard during migration |

## Real execution contract

`run_experiment()` requires these inputs explicitly:

- a FASTA path;
- a caller-owned `sample_id`;
- candidate records with real provenance;
- a set of device drivers;
- an ordered workflow/dependency mapping;
- a planner implementing `plan()` and `recover()`.

A real device manifest must identify itself and must include `simulated: false`. A candidate is rejected from the production path when it carries known simulation markers such as `SIM-*`, `source=synthetic_fixture` or `simulated=true`.

This negative check is not a substitute for scientific validation. It exists to prevent the old hackathon fixtures from silently entering production execution.

## DeviceDriver

`DeviceDriver` is the local adapter contract:

| Method | Meaning |
|---|---|
| `describe()` | Stable device identity, operations, state/capabilities, and `simulated` flag |
| `read(job_id=None)` | Authoritative device/job state |
| `write(Command)` | Submit one validated asynchronous command and return a job ID |
| `wait(job_id)` | Wait for completion/acknowledgment; timeout must not imply cancellation |
| `cancel(job_id)` | Confirm cancellation when the hardware can actually guarantee it |
| `close()` | Release driver resources without inventing remote acknowledgments |

The interface is transport-neutral. Vendor SDK, REST, serial, OPC-UA or another transport belongs inside a concrete adapter.

## Recovery invariant

The useful part of the hackathon prototype is retained: a timeout is an observation, not a result.

1. Submit a command with a stable logical command ID.
2. If waiting times out, query the original job.
3. Reuse a completed result instead of duplicating the action.
4. If still running, obtain a bounded recovery decision.
5. Require authoritative cancellation before retry/failover.
6. If device state becomes unknown, stop rather than duplicate a potentially irreversible operation.

Real instrument adapters may need richer sample-disposition and partial-effect semantics before a step can safely support automatic retry.

## Planning boundary

The planner can choose only among candidate IDs and device IDs supplied in context. Its output is validated as structured data. The orchestration layer never executes model-generated code and does not treat model prose as device state or biological evidence.

The current generic validator still selects 2-3 candidates because that constraint is inherited from the first prototype. This should become protocol-specific as the real experimental protocol is defined.

## Persistence

Current run artifacts remain file-backed (`events.jsonl`, `report.json`, `report.md`). This is sufficient for audit during the first refactor, but not sufficient for reliable real hardware recovery across process crashes.

The next persistence milestone should store command IDs, remote job IDs, attempts, resource/sample disposition and reconciliation state durably (SQLite is sufficient for the first implementation).

## Simulation isolation

`simulation.py` contains all old synthetic behavior: generated candidate scores, virtual devices, random readouts and fault injection. Compatibility imports remain temporarily so the existing test suite and dashboard keep working, but new production code must import only the generic contracts.

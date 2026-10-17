# Contract: Event Stream

**Status**: FROZEN — only the integrator may change this file.

**Producer**: a run writes `runs/<run-id>/events.jsonl`.

**Consumer**: the live dashboard and any audit tool.

## Record shape

Each line is one JSON object:

```json
{"seq": 1, "at": "2026-10-16T16:44:44Z", "run_id": "20261016T164444Z-e48fb36143",
 "event": "run_started", "details": {"agent": "rule", "execution_mode": "virtual_hardware",
 "physical_execution": false, "sample_id": "smoke-001"}}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `seq` | integer | Monotonic sequence within the run |
| `at` | ISO-8601 UTC string | Event timestamp |
| `run_id` | string | Run identifier |
| `event` | string | Frozen event name (below) |
| `details` | object | Event-specific payload |

## Frozen event names

A `virtual_hardware` run produced exactly these 16 events:

```
run_started → source_identified → input_validated → devices_discovered
→ planning_requested → plan_accepted
→ (job_submitted → device_job_completed → step_completed) × N
→ run_finished
```

Field names and event names MUST NOT change. The dashboard switches on `event` and does no fuzzy matching.

## Unknown-event rule

Any event name not listed above MUST be **ignored**, not treated as an error. Adding a backend event must never break the dashboard.

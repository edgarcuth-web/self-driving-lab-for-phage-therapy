# Contract: Dashboard SSE

**Status**: FROZEN — only the integrator may change this file.

**Producer**: `phage_lab/server.py` (dashboard frontend owns the implementation).

## Endpoints

```
GET  /                 → single-page dashboard
GET  /api/events       → SSE stream, event name fixed as `run_event`
GET  /api/report       → current report.json
GET  /api/round1       → round-one plan (for delta highlighting)
```

## Frame format (frozen)

```
event: run_event
data: {"seq":7,"event":"plan_accepted","details":{...}}

```

- The **first frame MUST be a complete snapshot**, not empty. A cold-starting dashboard must never begin blank.
- Subsequent frames are incremental.
- Unknown event names are ignored (see `events.md`).

## Port conflict

Not decided here. The behavior when the requested port is already in use is an open edge case in `spec.md`; resolve it via `/speckit.clarify` before freezing it into this contract.

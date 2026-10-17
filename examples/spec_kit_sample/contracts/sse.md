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

If the requested port is already in use, the server MUST either select a free port or fail with a readable message. Silent binding failure is not acceptable (see `spec.md` edge cases).

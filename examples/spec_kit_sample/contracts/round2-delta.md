# Contract: Round-Two Selection Delta

**Status**: FROZEN — only the integrator may change this file.

This is the data source for the dashboard's "money shot": the visible proof that round two changed because of round one.

## Shape

The round-two plan MUST carry:

```json
{
  "round": 2,
  "based_on_run": "<round-one run_id>",
  "selection": ["MF000003.1"],
  "rationale": "第一轮 MF000002.1 信号最低（0.0862），本轮剔除并补入互补候选",
  "delta_from_previous": {
    "added":   ["MF000003.1"],
    "removed": ["MF000002.1"],
    "reason_field": "results.measure.readings[2]"
  }
}
```

## Requirements

- `based_on_run` MUST reference a real prior run.
- `delta_from_previous.added` and `.removed` MUST be present (may be empty arrays, but must exist).
- `reason_field` MUST point at the concrete evidence used for the decision.
- When no candidate can be added, the behavior is **deferred to clarification**: see the `spec.md` edge cases. Do not freeze it here until `/speckit.clarify` decides.

Without `delta_from_previous`, round two is indistinguishable from a pipeline and the closed loop is not demonstrated.

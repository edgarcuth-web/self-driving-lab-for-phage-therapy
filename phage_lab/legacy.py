"""Candidate-based planning compatibility.

New integrations pass a frozen ExperimentSpec. This module keeps historical
candidate selection outside the spec-bound device assignment path. Both paths
feed the same scheduler; it contains no device execution or evidence admission.
"""


def offline_candidate_selection(context):
    """Preserve the historical offered-order/PHIST selection policy."""
    from .agents import AgentError, _selection_size

    low, high = _selection_size(context)
    candidates = context["candidates"]
    reported = [item["id"] for item in candidates
                if isinstance(item.get("ranking"), dict) and item["ranking"].get("reported")]
    reported_ids = set(reported)
    rest = [item["id"] for item in candidates if item["id"] not in reported_ids]
    offered = reported + rest if reported else [item["id"] for item in candidates]
    if len(offered) < low:
        raise AgentError("Fewer candidates were offered than the plan requires.")
    want = max(low, min(high, len(reported))) if reported else max(low, min(high, 2))
    chosen = offered[:want]
    return {
        "candidate_ids": chosen,
        "reason": (f"Offline policy: take {len(chosen)} candidate(s)"
                   + (" the host-range tool reported" if reported else " in offered order")
                   + ", and a compatible device per operation."),
    }


async def request_candidate_plan(agent, *, genome, candidates, devices, workflow,
                                 execution_mode, selection_size, records):
    # Import at the boundary to avoid a module-load cycle with the executor.
    from .workflow import validate_plan

    records.emit("planning_requested", agent=getattr(agent, "name", type(agent).__name__))
    plan = await agent.plan({
        "genome": genome.public_metadata(), "candidates": candidates,
        "devices": [device.describe() for device in devices.values()],
        "workflow": workflow, "execution_mode": execution_mode,
        "physical_execution": execution_mode == "real_hardware",
        "selection_size": list(selection_size),
    })
    validate_plan(plan, candidates, devices, operations=tuple(workflow),
                  selection_size=selection_size)
    records.emit("plan_accepted", agent=getattr(agent, "name", type(agent).__name__), **plan)
    return plan

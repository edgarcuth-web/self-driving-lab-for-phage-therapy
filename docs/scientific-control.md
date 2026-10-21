# Scientific control v1

Scientific control coordinates scientific decisions. It is deliberately separate
from workflow/device orchestration and from the scientific models it calls.

The first implemented vertical slice is intentionally narrow:

```text
ScientificObjective
        │
        ▼
ScientificOrchestrator
        │
        │ explicitly trusted module only
        ▼
natural_phage_recommender v1
        │
        ▼
CandidateSet
        │
        ▼
ScientificProposal
        │
        ▼
ScientificReviewer
        │
        ├─ approved
        ├─ revision_required
        └─ abstained
```

## What the orchestrator does

`ScientificOrchestrator.prioritize_natural_phages()` accepts an exact
`ScientificObjective`, `HostState`, supplied `PhageProfile` records and supplied
`InteractionPrediction` records. It resolves the natural-phage recommender from
an explicit internal trusted-module registry rather than accepting arbitrary
callables.

The proposal records:

- the exact objective revision;
- the trusted module ID and version;
- exact HostState, PhageProfile and InteractionPrediction input references;
- the exact output CandidateSet reference;
- selected phage profile IDs;
- whether the selected evidence is prediction-based, mixed, exploration-only or empty;
- a typed `screening_priority` claim and the source limitations.

The orchestrator does not generate a new biological probability and does not
reinterpret `not_estimated` as a negative result.

## What the reviewer does

`ScientificReviewer` independently checks the proposal against the supplied
objective and CandidateSet. It verifies exact lineage, trusted-module identity,
selection identity and evidence-state consistency.

A claim outside `screening_priority` is a semantic upgrade and produces
`revision_required`. For example, a screening decision cannot be relabelled as
therapeutic efficacy. Exploration-only selections may be approved for screening,
but the review records that productive infection remains unresolved. An empty
eligible selection yields `abstained`.

Review is read-only: source scientific artifacts are frozen dataclasses and the
review emits a new content-addressed `ScientificReview`.

## Hard boundary

The package has no dependency on:

- `workflow.py`;
- `devices.py`;
- workflow `agents.py`;
- `virtual_hardware.py`;
- `material_batch.py`.

Tests enforce this import boundary.

Scientific review approval is therefore **not execution approval**. v1 does not
create or modify an ExperimentSpec, assign devices, dispatch hardware, define a
wet-lab procedure, ingest measurements or update a model. Existing
`ExperimentSpec → workflow → DeviceDriver` execution remains a separate frozen
path.

## Why v1 is deterministic

No LLM is required for this slice. The goal is to establish auditable scientific
control contracts and reviewer semantics before adding model-driven decomposition
or tool selection. A future LLM-facing planner can propose bounded tasks, but the
same trusted-module registry, artifact lineage and reviewer gate should remain the
authority boundary.

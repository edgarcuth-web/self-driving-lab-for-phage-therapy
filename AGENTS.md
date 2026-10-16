# Working agreements

## Goal and scope

Build a real autonomous phage R&D platform. A human supplies a target bacterial isolate/genome and research objective; the system characterizes the host, evaluates phage-host evidence, proposes natural-phage or cocktail designs, escalates to engineering only when justified, executes validated experiments, and feeds measured outcomes into the next design cycle.

The deliverable is a traceable Design–Build/Acquire–Test–Learn loop. The self-driving lab is the execution subsystem of that loop, not the whole source of scientific intelligence.

Software twins and test doubles are development tools. They are never evidence of biological efficacy or physical execution.

## Architecture invariants

Keep these boundaries explicit.

### Scientific intelligence != lab orchestration

Scientific components decide what should be tested and why. They may produce:

- host characterization;
- phage characterization;
- interaction evidence and predictions;
- cocktail designs;
- uncertainty or coverage gaps;
- failure-attribution hypotheses;
- engineering escalation proposals.

The orchestration layer decides how an already validated experiment is executed:

- task dependencies;
- device assignment;
- dispatch;
- timeout reconciliation;
- cancellation;
- recovery;
- safe-state handling;
- execution records.

Do not make the lab-orchestration agent responsible for biological truth. Do not let a scientific model bypass the validated ExperimentSpec/device boundary.

### First-class domain objects

Treat these as durable, versioned concepts rather than anonymous dictionaries as the system evolves:

- `HostProfile`
- `PhageProfile`
- `InteractionEvidence`
- `CocktailDesign`
- `ExperimentSpec`
- `MaterialBatch`
- `Measurement`
- `Phenotype`
- `FailureAttribution`
- model/analysis versions and feedback decisions

Preserve lineage between them. A design used in a build or experiment is immutable; a change creates a new version.

### Natural-first escalation

Prefer the least invasive path that addresses the research objective:

1. retrieve/evaluate natural phages;
2. optimize cocktail composition;
3. identify remaining coverage or resistance gaps;
4. consider host-range engineering when a mechanistic gap is supported;
5. consider deeper defense/counter-defense or genome-level design only after lower-level paths are inadequate.

Engineering is an escalation path, not a default parallel route.

### Virtual hardware simulates devices, not biology

Virtual devices may model:

- submission;
- running/completion;
- timeout;
- unreachable state;
- cancellation;
- recovery;
- safe-state;
- artifact handoff.

Do not use synthetic device output as biological evidence. Prefer replay of historical real measurements or explicit test fixtures when a measurement-shaped payload is needed for development.

### PHIST is one evidence source

PHIST is a current external analysis component. Its shared-k-mer statistics are not infection probabilities and must not become the permanent definition of host-range prediction.

Future interaction models may combine host features, phage features, receptor/RBP evidence, surface structures, defense/counter-defense context and measured phenotypes. Every tool/model has its own provenance, evaluation and output semantics.

## Subsystem responsibilities

### Host characterization

Turn a target genome/isolate into a versioned `HostProfile`.

The profile may eventually include taxonomy, strain identity, receptors, capsule/LPS or other surface structures, anti-phage defense systems, AMR, virulence context and prior susceptibility observations.

Unknown means unknown. Do not fill missing fields with guessed biology. An empty or negative result is allowed only when an identified analysis actually assessed that feature class.

Raw FASTA should not be sent to external LLMs by default. Local analyzers may consume sequence; external reasoning components should receive structured, policy-approved representations.

### Phage characterization

Turn natural or engineered phage candidates into versioned `PhageProfile` records with sequence/design identity, provenance and characterized features.

Retrieved natural phages and generated/engineered designs are different provenance classes. Never fabricate database accessions for generated designs.

### Interaction evidence and design

Keep evidence, prediction and decision separate.

An interaction predictor may estimate compatibility or rank candidates. A `CocktailDesign` should record which evidence/model versions support each member and what design objective it addresses.

LLMs may explain or coordinate bounded scientific decisions, but validated optimizers/models should own numerical or mechanistic claims when such models exist.

### Synbio and material delivery

Manage design handoff, acquisition/build planning, external services, internal device tasks, inventory, quality confirmation and material delivery.

Designs, synthesis products, build batches, inventory materials and final tested materials are distinct objects.

Device-task completion alone does not release material for testing. Material must have identity, quality evidence and sufficient availability for the intended experiment, or an explicit incomplete outcome.

### Automated testing

Consume identified physical material plus a versioned `ExperimentSpec`.

Link actual device execution and measurements to the exact input material batches and specification version.

A successful workflow run is a control-plane result. It is not itself a successful biological result.

### Analysis and learning

Convert valid measurements into explicit phenotype/analysis records and use them to inform the next design cycle.

Build failures, device failures, invalid measurements and biological negative results are separate classes. Missing material or failed measurement must never become an automatic biological negative.

## Current implementation and direction

Implemented:

- HostProfile v1 schema, unknown/assessed semantics and local serialization;
- pinned reference snapshots and candidate retrieval;
- sequence indexing;
- PHIST ranking with provenance;
- structured planning;
- scheduling, reconciliation and recovery;
- execution records;
- device contracts;
- explicit real/virtual execution modes;
- safe-state handling;
- runnable HTTP adapter example.

Near-term direction:

1. add real host-characterization analyzers that contribute versioned evidence to `HostProfile`;
2. establish `PhageProfile`;
3. add an `InteractionEvidence` interface;
4. add `CocktailDesign`;
5. connect `ExperimentSpec` to the existing orchestrator;
6. ingest real measurements/phenotypes;
7. add failure attribution and active learning;
8. add engineering escalation.

Do not spend major effort expanding robot simulators while these scientific interfaces are missing.

## Code map

- `biology.py`: FASTA validation and sequence summaries.
- `host_profile.py`: host-domain schema and local profile serialization.
- `snapshots.py`, `candidates.py`, `sequences.py`: pinned reference data, sourced candidates and accession-indexed sequences.
- `ranking.py`: external-tool ranking and provenance.
- `agents.py`: bounded orchestration decisions; it is not the scientific design layer.
- `workflow.py`: validation, scheduling and reconciliation.
- `devices.py`, `virtual_hardware.py`: device contract and development twins.
- `records.py`, `provenance.py`: append-only events, reports and code identity.
- `docs/hardware.md`, `examples/adapters/http_instrument.py`: integration guide and adapter example.

Module paths are relative to `phage_lab/` unless stated otherwise.

## Hardware execution

Require an explicit `execution_mode`.

- `real_hardware` requires supplied devices with `simulated=False`.
- `virtual_hardware` requires `simulated=True`.
- Never silently fall back or mix modes.

Agents propose structured actions. The controller validates candidate IDs, capabilities, assignments and recovery actions before dispatch through device drivers. Never execute model-generated code.

Physical execution requires confirmation from the connected system, not merely a successful API call or GUI click.

A timeout means outcome unknown. Query the original job before retrying. Retry or fail over only after cancellation is acknowledged, or reuse the confirmed completed result. Unknown device/job state stops execution.

Real drivers declare `safe_state`: `policy`, boolean `retains_hazard`, and an operator-readable description. Request `enter_safe_state()` on abandoned steps and unsuccessful runs. Missing/invalid confirmation is `unknown`.

## Data and evidence

Preserve provenance for:

- genome/profile inputs;
- candidates and designs;
- model/tool versions and parameters;
- experiment specifications;
- materials;
- execution mode and devices;
- raw/processed measurements;
- phenotype analyses;
- feedback decisions;
- code and artifacts.

Distinguish predictions, simulated readouts and physical measurements in stored results.

Current sourced candidates require nonempty `source_db`, `accession`, ISO-8601 `retrieved_at` and `source_uri`.

Snapshot candidates carry both `snapshot_version` and `snapshot_sha256`, or neither. `require_snapshot` makes both mandatory.

Providers report source annotations, not experimental host-range measurements.

For PHIST, shared k-mers and p-values are tool statistics, not infection probabilities. No-match means no signal from that tool, not evidence that infection is impossible.

Do not commit credentials, raw user genomes or generated run directories. Do not send raw FASTA content or headers to external models by default.

## Development

Python 3.11+.

Run:

```bash
python -m unittest discover -s tests -v
```

Keep `README.md` (purpose/current status), `docs/architecture.md` (target architecture/contracts) and this file (development rules) consistent.

Tests should cover provenance, schema validation, versioning, execution-mode boundaries, adapter contracts, reconciliation, cancellation and safe-state behavior. As scientific domain objects arrive, add lineage and unknown-vs-assessed semantics tests.

For GitHub changes, inspect the current branch head and diff before updating it. Preserve concurrent work and never force-push over another contributor's changes.

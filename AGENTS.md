# Working agreements

## Goal and scope

Build a real AI-driven laboratory for phage research: AI proposes phage designs and experiments, connected instruments perform physical tests, and measured results feed the next design cycle.

The deliverable is a traceable design–build–test–learn loop on real hardware. Candidate retrieval and ranking support that loop; they are not the full design capability. Software twins and test doubles are development tools, not the project endpoint or evidence of physical execution.

## Current implementation and direction

- Implemented: reference snapshots, candidate retrieval, PHIST ranking, structured planning, scheduling, reconciliation, execution records and device contracts.
- Hardware integration currently has a runnable HTTP adapter example; instrument-specific drivers and confirmed physical runs remain work to deliver.
- Autonomous phage design, experimental result feedback and model evaluation are development goals, not existing capabilities. Describe their implementation status accurately.
- Prioritize real device integration, durable experiment state and measured-result ingestion. Connect design and learning components through explicit, versioned interfaces.
- The existing external-ranker implementation is a starting point, not a permanent restriction on future models. New models need their own provenance, evaluation and documented output semantics.

## Code map

- `biology.py`: FASTA validation and privacy-preserving input summaries.
- `snapshots.py`, `candidates.py`, `sequences.py`: pinned reference data, sourced candidates and accession-indexed sequences.
- `ranking.py`: external-tool ranking and tool provenance.
- `agents.py`: structured proposals; `workflow.py`: validation, scheduling and reconciliation.
- `devices.py`, `virtual_hardware.py`: device contract and development twins.
- `records.py`, `provenance.py`: append-only events, artifacts and code identity.
- `docs/hardware.md`, `examples/adapters/http_instrument.py`: integration guide and adapter example; keep them current with contract changes.
- `tests/support.py`: test doubles and fault injection; production code does not inject faults into itself.

Module paths above are relative to `phage_lab/` unless stated otherwise.

## Hardware execution

- Require an explicit `execution_mode`. `real_hardware` requires supplied devices with `simulated=False`; `virtual_hardware` requires `simulated=True` and may create twins. Never silently fall back or mix modes.
- Agents propose structured actions. The controller validates candidate IDs, capabilities, assignments and recovery actions before dispatch through device drivers. Never execute model-generated code.
- Adapters may use SDKs, REST, serial, OPC-UA or controlled GUI interfaces. Physical execution requires confirmation from the connected system, not merely a successful API call or GUI click.
- A timeout means outcome unknown. Query the original job before retrying; retry/fail over only after cancellation is acknowledged, or reuse its confirmed completed result. Unknown device/job state stops execution.
- Real drivers declare `safe_state`: `policy`, boolean `retains_hazard` and an operator-readable `description`. Policies are `park_and_release`, `contained_hold` or `operator_required`; the latter two cannot claim `retains_hazard=False`.
- Request `enter_safe_state()` on abandoned steps and unsuccessful runs. Missing or invalid confirmation, including driver errors, is `unknown`. `report["physical_state"]` reflects the worst device status.
- Exercise the same reconciliation and stop semantics with test doubles before integrating a driver.

## Data and evidence

- Preserve provenance for inputs, candidates or designs, model/tool versions and parameters, execution mode, devices, code and artifacts. Link physical results to the actual experiment and tested material.
- Existing sourced candidates require nonempty `source_db`, `accession`, ISO 8601 `retrieved_at` and `source_uri`. Validate provenance explicitly, not through ID naming conventions.
- Before admitting generated designs, add an explicit design-provenance schema and validation path. Do not fabricate database accessions or pass designs off as retrieved reference records.
- Snapshot candidates carry both `snapshot_version` and `snapshot_sha256`, or neither; `require_snapshot` makes both mandatory. Re-hash pinned files on load. Reference acquisition is separate from experiment execution.
- Providers report database annotations, not experimental host-range measurements. Ranking records identify their tool/model and input; missing or failed ranking never silently becomes a heuristic or source-order ranking.
- For the current PHIST integration, shared k-mers and p-values are tool statistics, not infection probabilities. Preserve the existing validation of `ranking` fields. No-match rows remain `reported: false`; do not mix tools, host genomes or partially ranked sets.
- Distinguish predictions, simulated readouts and physical measurements in stored results. Workflow completion is a control-plane result; biological outcomes come from measured data.
- Selection size belongs to the experiment specification (`selection_size`), not hardcoded cocktail bounds.
- Do not commit credentials, raw user genomes or generated run directories. Do not send raw FASTA content or headers to external models by default.

## Development

Python 3.11+. Run:

```bash
python -m unittest discover -s tests -v
```

Use `PHIST_PATH` for the opt-in real-tool integration test. CLI usage belongs in `README.md`; architecture details belong in `docs/architecture.md`.

Maintain coverage for provenance and checksum validation, sequence indexing, ranking/no-match behavior, selection bounds, explicit execution modes, adapter contracts, reconciliation, cancellation and safe-state handling. Tests with twins verify software behavior; physical integration checks record the actual device and result artifacts.

For GitHub changes, inspect the current branch head and diff before updating it. Preserve concurrent work and never force-push over another contributor's changes.

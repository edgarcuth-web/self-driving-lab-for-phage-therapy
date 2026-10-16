# Working agreements

## Goal and scope

Build an auditable self-driving-lab orchestration system for phage research under current resource constraints.

The scientific/data layer should become real and traceable wherever possible. Missing robotics or lab instruments may be represented by explicit software device twins. Never represent virtual hardware output as physical experimental evidence.

## Architecture

- `phage_lab/biology.py`: validate FASTA and compute privacy-preserving summaries.
- `phage_lab/devices.py`: transport-neutral device contract.
- `phage_lab/workflow.py`: candidate validation, execution-mode validation, scheduler and reconciliation.
- `phage_lab/virtual_hardware.py`: software device twins.
- `phage_lab/agents.py`: bounded structured proposals; no direct hardware authority.
- `phage_lab/records.py`: append-only events and explicit execution provenance.
- `phage_lab/provenance.py`: source fingerprint and optional Git metadata.
- `tests/support.py`: test doubles, including fault injection. Production code never injects faults into itself.

## Execution modes

`execution_mode` is a required argument with no default. A caller that did not state which kind of hardware it expects does not get either.

`real_hardware` requires every device to declare `simulated=False`. With no devices supplied it refuses to run; it never falls back to twins.

`virtual_hardware` requires every device to declare `simulated=True`. When explicitly selected, the workflow may create software device twins automatically if no devices were supplied.

Never silently switch between execution modes.

## Evidence invariants

- Experiment-path candidates are admitted by an allowlist, not a denylist. Every record must carry `source_db`, `accession`, `retrieved_at` (ISO 8601) and `source_uri` as nonempty strings. Rejecting by naming convention (`SIM-*` prefixes and the like) only catches fixtures that happen to be labelled honestly, so never rely on it.
- Report provenance from the data, never from a naming convention: whether a readout is synthetic is decided by the device's own `simulated` flag, not by recognizing a unit string.
- Virtual hardware may simulate task completion and readouts for scheduler/UI/interface testing, but those outputs must remain labeled simulated and cannot support biological claims.
- Orchestration success is not biological efficacy.
- Preserve provenance for input summary, candidate source, execution mode, device identity, code identity and resulting artifacts.
- Candidate selection size belongs to the experiment spec (`selection_size`), not to hardcoded bounds. One phage and a six-member cocktail are both legitimate.
- Do not commit credentials, raw user genomes or generated run directories.
- Do not send raw FASTA content or headers to external models by default.

## Control invariants

- Agent/model output is untrusted structured data.
- Validate candidate IDs, device capabilities, workflow assignments and recovery actions before execution.
- Never execute model-generated code.
- A timeout means outcome unknown. Query the original job before retry.
- Do not retry/fail over until cancellation is acknowledged, unless the original job is observed completed and its result is reused.
- Unknown physical device/job state stops execution.
- For virtual hardware, preserve the same reconciliation semantics so the control plane is exercised before real hardware exists.

## Future integrations

A concrete adapter may use vendor SDK, REST, serial, OPC-UA, cloud APIs, or a controlled Computer Use / GUI layer. The adapter must still expose clear device/job state and execution provenance.

Do not claim physical execution merely because Computer Use clicked a laboratory UI. Physical execution is true only when the connected external system actually caused and confirmed the physical action.

## Development

Python 3.11+.

Run:

```bash
python -m unittest discover -s tests -v
python -m phage_lab run --candidates candidates.json --sample-id sample-001 \
  --execution-mode virtual_hardware
```

Tests should cover: sourced candidates over virtual hardware, rejection of candidates without provenance, strict real-hardware mode matching, no implicit fallback, reconciliation and failover under injected faults, selection-size bounds, and explicit labeling of virtual outputs.

For GitHub changes, inspect the current branch head before updating it. Preserve concurrent work and never force-push over another contributor's changes.

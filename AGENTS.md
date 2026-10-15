# Working agreements

## Goal and scope

Build an auditable self-driving-lab orchestration system for phage research under current resource constraints.

The scientific/data layer should become real and traceable wherever possible. Missing robotics or lab instruments may be represented by explicit software device twins. Never represent virtual hardware output as physical experimental evidence.

## Architecture

- `phage_lab/biology.py`: validate FASTA and compute privacy-preserving summaries.
- `phage_lab/devices.py`: transport-neutral device contract.
- `phage_lab/workflow.py`: candidate validation, execution-mode validation, scheduler and reconciliation.
- `phage_lab/simulation.py`: software device twins and the isolated legacy all-synthetic demo.
- `phage_lab/agents.py`: bounded structured proposals; no direct hardware authority.
- `phage_lab/records.py`: append-only events and explicit execution provenance.
- `phage_lab/provenance.py`: source fingerprint and optional Git metadata.
- `phage_lab/dashboard.py` + `web/`: legacy simulation UI until migrated to the hybrid path.

## Execution modes

`real_hardware` requires every device to declare `simulated=False`.

`virtual_hardware` requires every device to declare `simulated=True`. When explicitly selected, the workflow may create software device twins automatically if no devices were supplied.

The old `legacy_demo` remains fully synthetic, including candidate generation. Do not confuse it with the hybrid experiment path.

Never silently switch between execution modes.

## Evidence invariants

- Experiment-path candidates must come from externally supplied records. Reject known `SIM-*`, `source=synthetic_fixture`, or `simulated=True` candidate fixtures.
- Virtual hardware may simulate task completion and readouts for scheduler/UI/interface testing, but those outputs must remain labeled simulated and cannot support biological claims.
- Orchestration success is not biological efficacy.
- Preserve provenance for input summary, candidate source, execution mode, device identity, code identity and resulting artifacts.
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
python -m phage_lab demo --seed 42 --time-scale 0.1
```

Tests should cover both hybrid modes and the legacy demo: real candidates over virtual hardware, strict real-hardware mode matching, no implicit fallback, reconciliation, and explicit labeling of synthetic outputs.

For GitHub changes, inspect the current branch head before updating it. Preserve concurrent work and never force-push over another contributor's changes.

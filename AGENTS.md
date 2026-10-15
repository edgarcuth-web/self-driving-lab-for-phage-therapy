# Working agreements

## Goal and scope

Build a real, auditable self-driving laboratory orchestration system for phage research. The hackathon simulator is no longer the product; it is only a test harness.

The production path must accept real candidate records and real instrument adapters explicitly. Never fill missing real integrations with synthetic data.

## Architecture

- `phage_lab/biology.py`: validate FASTA and compute privacy-preserving summaries. No synthetic candidate generation in the core implementation.
- `phage_lab/devices.py`: transport-neutral device contract only.
- `phage_lab/workflow.py`: production validation, scheduler and reconciliation.
- `phage_lab/simulation.py`: all synthetic candidates, virtual devices, seeded readouts and fault injection.
- `phage_lab/agents.py`: bounded structured proposals; no direct hardware authority.
- `phage_lab/records.py`: append-only events and run reports.
- `phage_lab/provenance.py`: source fingerprint and optional Git metadata.
- `phage_lab/dashboard.py` + `web/`: legacy simulation UI until a real operations UI is designed.

## Production invariants

- Real execution must never silently fall back to simulation.
- Reject known simulation fixtures before submitting any physical job.
- A real driver must explicitly declare `simulated=False`; absence of the flag is not enough.
- Agent/model output is untrusted structured data. Validate candidate IDs, device capabilities, workflow assignments and recovery actions before execution.
- Never execute model-generated code.
- A timeout means outcome unknown. Query the original job before any retry.
- Do not retry or fail over until cancellation is authoritatively acknowledged, unless the original job is observed completed and its result is reused.
- Unknown device/job state stops execution. Do not duplicate a potentially irreversible physical action.
- Do not infer biological efficacy from orchestration success or raw measurement presence.
- Preserve provenance for input summary, candidate source, device identity, code identity and resulting artifacts.
- Do not commit credentials, raw user genomes or generated run directories.
- Do not send raw FASTA content or headers to external models by default.

## Simulation rules

Simulation remains valuable for tests, CI and failure semantics. Keep it explicit:

```bash
python -m phage_lab demo
python -m phage_lab dashboard
```

Simulation code belongs in `phage_lab/simulation.py` or test doubles. Do not add new `SIM-*`, random biological scores/readouts or fault injection to the production workflow.

## Real integrations

Each concrete instrument adapter should live behind `DeviceDriver`. Before enabling automatic retry on a real operation, document what partial execution means and how sample disposition is reconciled.

The first real milestone should be deliberately narrow: one real adapter, one versioned protocol, real sample IDs, real measurement ingestion and durable job reconciliation. Do not expand biological autonomy before execution state is trustworthy.

## Development

Python 3.11+.

Run:

```bash
python -m unittest discover -s tests -v
python -m phage_lab demo --seed 42 --time-scale 0.1
```

Test both sides of the boundary: simulation remains deterministic enough for regression, while production validation must reject synthetic candidates/devices and must not create a run through an implicit fallback.

For GitHub changes, inspect the current branch head before updating it. Preserve concurrent work and never force-push over another contributor's changes.

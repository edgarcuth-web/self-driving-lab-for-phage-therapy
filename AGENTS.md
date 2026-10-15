# Working agreements

## Goal and scope

Build a hackathon prototype that runs a simulated phage-screening workflow,
encounters an instrument fault, recovers when the state permits, and reports
the outcome. Keep the one-command offline demo working.

## Architecture

- `phage_lab/biology.py`: FASTA validation and explicitly synthetic candidates.
- `phage_lab/agents.py`: offline policy and optional Claude API decisions.
- `phage_lab/devices.py`: device contract, manifests, asynchronous simulators.
- `phage_lab/workflow.py`: fixed task template, validation, scheduler, recovery.
- `phage_lab/records.py`: append-only events and final JSON/Markdown reports.
- `phage_lab/__main__.py`: command-line entry point.

## Invariants

- All instruments, synthesis requests, candidates and assay results are simulated.
  Never present synthetic scores as infection probabilities or efficacy evidence.
- Label the interface **MHS-inspired**, not an implementation of the official
  unpublished specification. Keep the local contract documented.
- Agent output is untrusted structured data. Validate device capabilities,
  candidate IDs and recovery actions before execution; never execute model code.
- A timeout means the outcome is unknown. Reconcile the job first. Reuse a
  completed result; require acknowledged cancellation before retry/failover.
- Unknown/unreachable state must produce a failure report, not duplicate work.
- Keep a stable logical command ID across attempts. Reject conflicting payloads
  for the same ID. Bound retries and preserve dependency order.
- The default is offline and needs no API key. API mode must be explicitly
  selected, must fail clearly on configuration/API errors, and must never
  silently fall back to the offline policy.
- Do not store credentials, raw user genomes, or generated run data in Git.
  Claude receives summary metadata only, not FASTA contents or headers.
- Simulation determinism concerns decisions and generated values, not run IDs,
  event timestamps or wall-clock timing. Live model decisions can vary.

## Development

Python 3.11+; standard library only for the first milestone. Avoid new services,
frameworks or dependencies unless the task needs them. Keep user instructions
short, in Chinese, and separate offline setup from API setup.

Run from repository root:

```bash
python -m unittest discover -s tests -v
python -m phage_lab demo --seed 42 --time-scale 0.1
```

Test failure semantics and public behavior: hanging tasks, lost acknowledgments,
unreachable devices, idempotency, malformed model output, and report integrity.
Do not claim live API verification unless an actual authorized request succeeded.

For GitHub changes, inspect the current branch head before updating it. Preserve
other contributors' work and never force-push over concurrent changes.

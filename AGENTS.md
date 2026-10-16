# Working agreements

## Goal and scope

Build an auditable self-driving-lab orchestration system for phage research under current resource constraints.

The scientific/data layer should become real and traceable wherever possible. Missing robotics or lab instruments may be represented by explicit software device twins. Never represent virtual hardware output as physical experimental evidence.

## Architecture

- `phage_lab/biology.py`: validate FASTA and compute privacy-preserving summaries.
- `phage_lab/devices.py`: transport-neutral device contract.
- `phage_lab/workflow.py`: candidate validation, execution-mode validation, scheduler and reconciliation.
- `phage_lab/snapshots.py`: pinned local copies of external reference data, with checksum manifests.
- `phage_lab/candidates.py`: candidate providers that read a snapshot and stamp provenance.
- `phage_lab/sequences.py`: accession-indexed genome sequences from a pinned FASTA snapshot.
- `phage_lab/ranking.py`: host-range ranking by external tools; no built-in ordering.
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
- Candidates that came from a reference snapshot carry `snapshot_version` and `snapshot_sha256`. Both or neither: half a snapshot reference is not traceable. `require_snapshot` makes them mandatory for a run. They are not required of every candidate, because a lab's own isolate has a real source and no snapshot.
- Reference data is pinned, not fetched per run. The orchestrator never reaches the network mid-run; downloading a snapshot is its own command, and a snapshot is re-hashed against its manifest when loaded.
- A provider reports what a source database records. It does not score, rank or predict infection, and a depositor's host annotation is not an experimental host-range result. Never present one as the other.
- Ordering comes from a named external tool or it does not exist. If the configured ranker is missing or fails, ranking raises; never fall back to a heuristic, alphabetical or source order and call the result a ranking. `report["candidate_ranking"]` always says which it was.
- A tool statistic is not a probability of infection. Shared k-mers correlate with host range; they do not measure it. Never add a field to a `ranking` block whose name reads as a probability, likelihood, success, efficacy or infectivity — validation rejects those.
- A tool reporting no match is an absence of that signal, not evidence that infection cannot occur. Unreported candidates keep a `ranking` block with `reported: false` and no rank, and `report["plan_ranking"]` names any selected candidate the tool did not support.
- Ranks from different tools or different host genomes cannot be mixed, and a partly ranked candidate set is refused: it would make the unranked ones look worse than the tool actually said.
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
python -m phage_lab fetch-snapshot --snapshot data/snapshots/inphared-1Oct2026 \
  --version 1Oct2026 --url https://.../1Oct2026_data.tsv
python -m phage_lab candidates --snapshot data/snapshots/inphared-1Oct2026 \
  --host "Escherichia coli" --out candidates.json
python -m phage_lab rank --candidates candidates.json \
  --sequences data/snapshots/inphared-genomes-1Oct2026 \
  --host-genome host.fasta --phist /path/to/phist.py --out ranked.json
python -m phage_lab run --candidates ranked.json --sample-id sample-001 \
  --execution-mode virtual_hardware --require-snapshot
```

The ranking tests use a stub `phist.py`; set `PHIST_PATH` to a real install to also run the opt-in integration test.

Tests should cover: sequence indexing and duplicate/missing accessions, ranking provenance and the no-fallback rule, tool rows that report no match, snapshot identity and checksum failure, provider column resolution and no-match handling, snapshot-provenance pairing, sourced candidates over virtual hardware, rejection of candidates without provenance, strict real-hardware mode matching, no implicit fallback, reconciliation and failover under injected faults, selection-size bounds, and explicit labeling of virtual outputs.

For GitHub changes, inspect the current branch head before updating it. Preserve concurrent work and never force-push over another contributor's changes.

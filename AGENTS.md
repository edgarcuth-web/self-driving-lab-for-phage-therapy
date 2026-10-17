# Working agreements

Build a traceable Design–Build/Acquire–Test–Learn loop for phage R&D.
Read [docs/architecture.md](docs/architecture.md) for the domain contracts and
[docs/usage.md](docs/usage.md) for CLI inputs. Keep those contracts when refactoring.

## Required boundaries

- Scientific components choose what to test; orchestration assigns devices and executes frozen intent. Never change ExperimentSpec arms, membership or workflow during execution/recovery.
- Preserve versioned artifact IDs, hashes, provenance and time ordering. Changes to built/tested designs create new versions; do not silently replace same-ID content.
- Keep source annotation, prediction, physical measurement and assessor interpretation distinct. Unknown is not negative; workflow success is not biological success; PHIST statistics are not infection probabilities.
- Missing calibrated predictions remain `not_estimated`. Estimated probabilities require uncertainty bounds/method and exact model/input provenance.
- Preserve CandidateSet exclusions, deferred candidates, prediction snapshots and selection reasons. Do not compare incompatible model cohorts or assign efficacy meaning to profile-ID ordering.
- HostState components require explicit evidence. New states never inherit dynamic components implicitly; lineage adapters do not infer biological state.
- Physical execution requires test-ready MaterialBatch binding. QC admission is explicit, independent of execution success. Phenotype requires physical, QC-valid, same-arm/spec/material Measurements.
- Failure review remains arm-scoped and criterion-based. Mechanism hypotheses are not confirmed causes; cocktail outcomes are not member outcomes.
- Feedback screening preserves its fixed campaign/context, criterion and history. Conflicts/inconclusive reviews require review; empty selection abstains. No automatic model, probability or HostState update.
- Prefer evaluating natural phages, then cocktails; engineering requires an explicit evidence gap. Retrieved record provenance alone does not establish natural origin.

## Execution and data

- Require explicit `real_hardware` or `virtual_hardware`; never mix or silently fall back. Driver `simulated` flags must match.
- Virtual hardware tests lifecycle and lineage only: `evidence_class=none`, no material consumption, no Phenotype support.
- Reconcile timed-out jobs before retrying. Retry/fail over only after confirmed cancellation or completion. Record unconfirmed physical state as unknown and preserve safe-state handling.
- Never execute model-generated code directly on devices. Raw FASTA and headers stay local by default; external reasoning receives structured data.
- Keep legacy candidate selection isolated from spec execution. New execution integrations use ExperimentSpec.
- Do not commit credentials, raw user genomes or generated run directories.

## Development

Python 3.11+, standard library. Run from the repository root:

```bash
python -m unittest discover -s tests -v
```

Keep shared mechanics small; retain domain validation in domain modules. Do not add
new frameworks, schema migrations or compatibility aliases without a concrete need.

README owns current capability/status and a runnable local check. Architecture owns
domain contracts and module relationships. Usage owns command examples. This file
owns development constraints; do not duplicate the other documents here.

Freeze material/provenance/device/simulator scope unless a scientific requirement
forces a change. Before GitHub writes, inspect the current branch head and diff.
Preserve concurrent work and never force-push over another contributor's changes.

# Clinical workflow presentation — Refs #28

Base: main at dad81da. Visual reference: 过家家演示版, dark buildless workflow cards.

## Scope and contract

An offline presentation, with synthetic fixture metadata and synthetic matching
catalogs. It does not invoke scientific modules, issue instrument commands, produce
physical evidence, or serialize mock objects as versioned domain artifacts.

Patient sampling → sample metadata / simulated isolation library → every isolate
in that fixture. Isolation completion releases phage matching and antibiotic
matching together. Preparation follows phage matching and takes seven scenario
days; antibiotic matching completes independently. No candidate means an explicit
unresolved result, not an invented match or negative finding.

After preparation, show the existing main concepts: CandidateSet, frozen
ExperimentSpec, virtual test, review and next screening. These are illustrative
stages, not backend integration. All biological probabilities remain not_estimated;
synthetic outputs are never QC-valid physical Measurement or Phenotype.

## Acceptance

1. `python -m phage_lab dashboard --no-browser --port 8765` serves only the UI on
   loopback, without dependencies, API keys, directory listing or run mutations.
2. Three built-in scenarios (mixed, single, unmatched) preserve all fixture
   isolates and sample metadata. Empty lookup is visibly unresolved.
3. At the isolation boundary both match branches are running. Antibiotic matching
   finishes before the day-seven preparation. Pausing stops scenario time;
   reset/case change clears statuses, events and report state.
4. Clicking each node reveals inputs, outputs and its evidence boundary. Metadata
   editing updates the sample and a downloaded JSON report preserves it.
5. Persistent simulation banner and textual state labels; usable keyboard focus,
   readable narrow layout and no external asset requests.
6. Named manual checks: desktop overview, simultaneous branches, completed report,
   unmatched sample, narrow layout. Archive screenshots under `verification/`.

## Explicit assumptions

Seven days is the user's scenario assumption, not a validated turnaround estimate.
Antibiotic catalog entries are opaque demo identifiers, without dosing, efficacy or
susceptibility claims. The isolation library returns the entire known fixture set;
it does not claim to identify every organism in a real clinical sample.

## Follow-up: Kimi K3 clinical report draft

On a terminal run (completed or stopped for review), submit the structured snapshot
to the local server once per run. The server validates and minimizes the payload,
then calls the official Kimi Code OpenAI-compatible endpoint with model `k3`.
No model fallback; show authentication, quota, network and response-validation errors.
No simulated local report may be labeled as a successful live-model response.

API keys stay only in server-process memory, never in files, browser storage,
responses or report exports. Host/Origin checks, per-session mutation tokens,
bounded bodies and one active report job protect the local API. GET requests never
dispatch paid model calls. Concurrent retries for an identical run reuse one job;
uncertain outcomes do not silently retry. Reset/sample changes must detach stale
responses from the new run. API configuration changes invalidate cached reports.

The report section shows local sample facts alongside model-generated Chinese
clinical draft sections. Label simulation/evidence boundaries and clinician review
throughout, including exports. Treat metadata/model output as text, never HTML.
Only metadata, isolate/match summaries, node states and limitations are transmitted;
never arbitrary extra fields, raw FASTA, API keys or hidden browser state.

Acceptance: automatic terminal-run generation, explicit unconfigured/pending/error
states, retry, Markdown download, report provenance (model/time/input hash), and no
stale report after reset. Offline workflow must work without configured credentials.

## Report UI follow-up

Separate isolate, phage-candidate and antibiotic-candidate modules with semantic
tables derived from the structured source snapshot. Keep all isolates, expand
multiple candidates and retain explicit unmatched rows. Group the corresponding
AI narrative with its table rather than duplicating sections. Each module has a
top-right copy action (tab-separated rows plus its explanatory text); the complete
report has its own top-right copy action including all tables and other sections.
Show successful/failed clipboard feedback. Render copied data as text, preserve
simulation labels, and use the same table content in Markdown downloads.

## Fragment-based detection simulation

Model the mNGS identification path, not a universal clinical diagnostic method.
Use deterministic short artificial DNA fragments against artificial reference
windows (not real species genomes, primers or validated marker sequences).
Display unique read count, toy-reference coverage, identity and sample/control
ratio. A documented weighted support score (0–100) is explicitly synthetic,
uncalibrated and not a diagnostic probability or confidence interval.

Keep species identification separate from bacterial-like signal detection.
The default mixed sample includes an unresolved bacterial-like signal, shown
under the detection node and below the detection result panel. It has no species
assignment or automatic phage/antibiotic candidates; it is not a confirmed novel
species. The single-sample case has no unresolved signal; the unmatched case
remains unresolved. Hide all detection results until the detection step ends.

Preserve eight core workflow tasks; the unknown-signal card is a review branch.
Reports/export/copy retain the detection summaries and unknowns, while the Kimi
request excludes all fragment bases. Frozen scientific modules are unchanged.

Score fixture model: 35% capped unique-read support (500 reads), 30% artificial
reference-window coverage, 25% scaled identity (85–100%), 10% capped sample/control
ratio (20). These weights/caps and >=85/>=60 display bands are demonstration
choices, not published laboratory cutoffs. Phage probabilities stay not_estimated.
# Demonstration follow-up — Refs #28

Acceptance: a presentation toggle hides configuration and fits the workflow to
the viewport; one click starts the selected fictional case with a roughly two
minute narrated tour, automatic section focus, pause/resume and chapter stepping.
Reset, case changes and exit must cancel the tour without stale advancement.
The tour preserves the existing scenario clock, unknown-signal review, blocked
paths and terminal report API behavior. The timeline shows independent D+3
antibiotic candidates alongside D+3–10 preparation. Completed main workflows
still display every low-support/unnamed review item. Report latency must remain
visible; autoplay never claims an unfinished report is ready.

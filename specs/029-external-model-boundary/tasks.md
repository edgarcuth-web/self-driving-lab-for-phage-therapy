# Tasks: External Model Boundary v1

- [x] Keep model fitting/training/evaluation outside this repository.
- [x] Define content-addressed ModelRequest and ModelResult exchange artifacts.
- [x] Add strict admission into the existing InteractionPrediction contract.
- [x] Document repository ownership and file-based transport.
- [x] Add contract tests for hashes, lineage, requested targets and model artifact provenance.
- [x] Implement the same v1 wire schema in the separate model repository and mirror it here with shared conformance fixtures.
- [ ] Add a future export contract for curated LearningObservation training datasets.

## Source-endpoint input extension

- [x] Define first-task endpoint semantics and ownership in both repositories.
- [x] Export full snapshots and verified, portable sequence/annotation payloads.
- [x] Add consumer validation and source-endpoint score/abstention/probability semantics.
- [x] Add shared fixtures and a cross-repository CLI round trip.
- [x] Run the full regression gate and smoke check for this extension.

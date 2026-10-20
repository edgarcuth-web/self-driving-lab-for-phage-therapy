# External Model Boundary v1

## Goal

Keep model development in a separate repository while preserving exact, auditable
scientific lineage in the self-driving lab.

## Requirements

- The lab MUST NOT contain model training, model-specific embeddings/transforms or calibration code. Shared scientific characterization remains in SDL.
- ModelRequest MUST bind an exact HostState content hash and PhageProfile fingerprint.
- ModelResult MUST bind the exact ModelRequest ID and content hash.
- Estimated outputs MUST name an immutable model artifact SHA-256.
- Unrequested targets MUST remain not_estimated.
- ModelResult MUST NOT become InteractionPrediction until admitted by the lab.
- Admission MUST reject mismatched host/phage lineage and time-travelled results.
- Admission success MUST NOT be described as scientific validation or calibration.
- The exchange MUST work as versioned JSON without requiring a network service.
- LearningObservation export for model training remains a separate future interface.

## Non-goals

- No model fitting, sequence embedding, calibration, active-learning acquisition,
  cocktail optimization or model-serving implementation in this repository.
- No bundled synthetic training set presented as scientific data.
- No automatic execution triggered by a model result.

## Acceptance

- Request and result artifacts round-trip with content-hash integrity.
- Wrong request hash, host/phage binding, target scope or timestamp fails closed.
- Estimated output without a model artifact digest fails closed.
- A valid result can be converted into the existing InteractionPrediction contract.
- Full repository unit tests pass.

## Source-endpoint input extension

Refs #35. The first model task predicts a pinned source-defined pair label, whose
assay mapping is currently unverified. Preserve the legacy contracts above for
their existing consumers and add a separate ModelInputBundle v1 / PairPrediction
v1 path; do not map source labels to their mechanistic targets implicitly.

- Export full pair snapshots, explicit endpoint/context and missingness, and
  opted-in sequence/annotation payloads into a new portable local directory.
- Verify raw bytes, normalized sequence identity, source bindings, annotation
  provenance and chronology; reject escapes, missing required inputs and tampering.
- Preserve partial annotation and natural/retrieved/engineered provenance.
- Bind each response to the entire bundle; distinguish abstention, score and
  calibrated probability with model/preprocessing/calibration artifact references.
- Keep source-endpoint outputs outside the productive-infection CandidateSet
  policy until a scientific endpoint mapping and selection policy are reviewed.
- Acceptance: `python tests/integration/check_model_bundle.py --model-repo ../model`
  verifies shared schemas/fixtures and fresh export → relocated model input →
  unresolved response → SDL admission without source registry access.

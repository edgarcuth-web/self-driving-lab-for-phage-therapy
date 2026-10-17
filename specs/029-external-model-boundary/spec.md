# External Model Boundary v1

## Goal

Keep model development in a separate repository while preserving exact, auditable
scientific lineage in the self-driving lab.

## Requirements

- The lab MUST NOT contain model training, feature extraction or calibration code.
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

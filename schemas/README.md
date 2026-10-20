# Scientific and model-boundary schemas

This repository owns the schemas for scientific characterization and its provenance:

- `sequence-registry-v1.schema.json`: exact local FASTA assets with raw-byte and normalized-sequence fingerprints.
- `feature-artifact-v1.schema.json`: provenance and output-integrity manifest for computed feature analyses.
- `padloc-host-defense-result-v1.schema.json`: structured result from the pinned PADLOC host-defense adapter.

The ModelRequest v1 and ModelResult v1 schemas are mirrored with
`ai-design-phage-cocktail` because both repositories validate the exchange.
Biological analyzer outputs, source registries and FeatureArtifact records remain
SDL-owned; model-specific embeddings, tensors, preprocessing and checkpoints do
not belong in this directory.


`model-input-bundle-v1.schema.json` and `pair-prediction-v1.schema.json` define
the current source-endpoint exchange. Bundle resources carry readable payloads;
legacy request hashes alone do not. These schemas and
`tests/fixtures/input_bundle/` are mirrored in both repositories. Embedded
FeatureArtifact definitions mirror SDL's owned v1 schema; no analyzer code moves
into the model repository. The cross-repository check is documented in
`docs/model-interface.md`.

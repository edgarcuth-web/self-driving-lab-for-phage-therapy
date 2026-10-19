# External model boundary

The interaction model is developed in a separate repository. This repository owns
experimental state, evidence, sequence identity, biological characterization,
execution and prediction admission. The model repository owns model-specific
representations, datasets, training, evaluation, calibration and inference.

## Ownership

| SDL repository | Model repository |
| --- | --- |
| HostProfile / HostState identity | model-ready datasets and versioning |
| PhageProfile identity and provenance | model-specific embeddings and encodings |
| Sequence registry and raw sequence fingerprints | tokenizers, feature transforms and tensors |
| PADLOC, receptor/surface annotation and FeatureArtifact provenance | architecture, training and checkpoints |
| InteractionEvidence and physical Phenotype | held-out evaluation, calibration and model cards |
| ModelRequest / ModelResult exchange | inference implementation |
| InteractionPrediction admission | model artifacts and uncertainty estimation |
| CandidateSet / ExperimentSpec / execution | no laboratory state ownership |

Neither repository imports the other's private Python modules. The boundary is
versioned data. Scientific annotations describe biological objects and remain
useful independently of any one model. Embeddings, tensor layouts, normalizers
and other model-specific representations belong with the model that consumes them.

## Machine-readable v1 schemas

The ModelRequest and ModelResult v1 schemas are mirrored byte-for-byte in both
repositories because both sides validate the exchange. They are wire contracts,
not a place to store analyzer implementations or model-specific feature tensors:

- [ModelRequest v1 JSON Schema](../schemas/model-request-v1.schema.json)
- [ModelResult v1 JSON Schema](../schemas/model-result-v1.schema.json)
- [Shared request fixture](../tests/fixtures/model_request_v1.json)
- [Shared result fixture](../tests/fixtures/model_result_v1.json)

Schema changes must be coordinated across both repositories. JSON Schema checks
the wire shape; the Python contract additionally checks content hashes, record-ID
equality, exact request/result lineage, timestamp ordering and requested-target
admission.

## Current v1 exchange

ModelRequest v1 binds one exact HostState content hash, one exact PhageProfile
content fingerprint and the prediction targets being requested. ModelResult v1
echoes the exact request ID and SHA-256, the same host/phage fingerprints, all
three target slots, producer identity, immutable model artifact SHA-256,
limitations, explanation and prediction time. Targets that were not requested
must remain `not_estimated`.

This is a transitional interface. The next boundary revision should be
`ModelInputBundle v1`: an immutable, content-addressed export produced by SDL
that contains admitted scientific annotations, screening/missingness states and
field-level provenance. The model repository should not resolve HostState,
PhageProfile or raw FASTA paths and should not run PADLOC or other biological
annotation tools. It should transform the frozen bundle into model-specific
representations and return a result tied to the exact bundle digest.

## Sequence fingerprint semantics

The HostState `host_genome_sha256` and a PhageProfile `sequence.sha256`, when
present, use the normalized-contig digest implemented by
`phage_lab.biology.read_fasta`: uppercase IUPAC DNA bases, FASTA headers and
whitespace omitted, and a NUL byte before each contig. This is distinct from the
raw FASTA file-byte SHA-256. SDL sequence registries retain both values.

A retrieved PhageProfile may carry an accession and pinned
`provenance.snapshot_sha256` without a sequence digest. Resolving that accession
against an exact source snapshot and FASTA asset is an SDL ingestion task. The
model-side contract receives stable identifiers and fingerprints, not paths into
the lab's local registry.

## Admission and transport

SDL re-admits ModelResult before it becomes InteractionPrediction. Admission
rejects request/result hash mismatch, different host/phage lineage, results
timestamped before the request, estimated unrequested targets, and estimated
outputs without a model artifact digest.

Passing admission means only that the exchange is internally consistent. It does
not establish biological validity, calibration, assay comparability or clinical
utility.

Start with files and CLI orchestration rather than a service:

1. SDL writes a versioned model-input exchange artifact.
2. The model repository applies its own versioned preprocessing and model.
3. The model repository writes a ModelResult bound to the exact input digest.
4. SDL validates and admits that result.
5. Only the admitted InteractionPrediction may enter CandidateSet.

LearningObservation remains the SDL-side record of an explicit label tied to an
exact prediction, ExperimentSpec and physical QC-admitted Phenotype. Exporting
curated training datasets is a separate interface. The model repository must not
interpret missing observations as negative labels or treat virtual-hardware output
as biological evidence.

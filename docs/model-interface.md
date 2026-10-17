# External model boundary

The interaction model is developed in a separate repository. This repository owns
experimental state, evidence, execution and the admission boundary. It does not
own feature extraction, training, model selection or calibration.

## Ownership

| This repository | Model repository |
| --- | --- |
| HostProfile / HostState identity | datasets and dataset versioning |
| PhageProfile identity and provenance | biological feature extraction |
| InteractionEvidence | training and model architecture |
| ModelRequest / ModelResult exchange | train/validation/test splitting |
| InteractionPrediction admission | calibration and uncertainty estimation |
| CandidateSet / ExperimentSpec | model artifacts and inference implementation |
| Measurement / Phenotype / LearningObservation | offline evaluation and model cards |

Neither repository imports the other's private Python modules. The boundary is
versioned JSON.

## v1 exchange

A ModelRequest binds one exact HostState content hash, one exact PhageProfile
content fingerprint and the prediction targets being requested.

A ModelResult echoes the exact request ID and SHA-256, the same host/phage
fingerprints, all three prediction target slots, producer identity, immutable model
artifact SHA-256, limitations, explanation and prediction time. Targets that were
not requested must remain not_estimated.

The lab repository re-admits ModelResult before it becomes InteractionPrediction.
Admission rejects request/result hash mismatch, different host/phage lineage,
results timestamped before the request, estimated unrequested targets, and
estimated outputs without a model artifact digest.

Passing admission means only that the exchange is internally consistent. It does
not establish biological validity, calibration, assay comparability or clinical
utility.

## Initial transport

Start with files and CLI orchestration rather than a service:

1. the lab writes ModelRequest JSON;
2. the model repository consumes it plus its own versioned data/resources;
3. the model repository writes ModelResult JSON;
4. the lab loads and admits that result;
5. only the admitted InteractionPrediction may enter CandidateSet.

A network service can be added later without changing scientific ownership.

## Returning experimental learning data

LearningObservation remains the lab-side record of an explicit label tied to an
exact prediction, ExperimentSpec and physical QC-admitted Phenotype. Exporting
curated training datasets is a separate future interface. The model repository
must not interpret missing observations as negative labels or treat virtual
hardware output as biological evidence.

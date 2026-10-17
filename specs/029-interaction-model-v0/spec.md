# Feature Specification: InteractionModel v0

**Feature Branch**: feat/interaction-model-v0

**Created**: 2026-10-17

**Status**: Draft

**Input**: User direction: build the scientific-modeling engine before expanding presentation work.

## User Scenarios & Testing

### User Story 1 — Admit a provenance-bound feature vector (Priority: P1)

A researcher packages numeric features produced by an identified upstream analysis for one exact HostState and PhageProfile. Each feature records where it came from and how it was computed.

**Why this priority**: Training is meaningless if feature identity, missingness, or lineage can drift between training and inference.

**Independent Test**: Round-trip a feature vector; reject non-finite values, missing feature provenance, changed hashes, or a vector whose host/phage lineage does not match its LearningObservation.

**Acceptance Scenarios**:

1. Given a valid HostState, PhageProfile, feature mapping, and per-feature source records, when a vector is created, then its exact state/profile fingerprints and content hash are retained.
2. Given an unknown feature, when its value is null, then it remains missing and is not silently converted to zero.
3. Given a non-finite value or missing provenance, when a vector is loaded, then admission fails.

### User Story 2 — Train a reproducible baseline from explicit labels (Priority: P1)

A researcher supplies feature vectors paired with validated LearningObservation records and trains a research-only supervised baseline for productive_infection.

**Why this priority**: It is the first real path from the existing physical-label contract to a fitted model, without inventing biological outcomes.

**Independent Test**: A deterministic software fixture trains twice with the same data and seed and yields identical coefficients, split membership, and metrics.

**Acceptance Scenarios**:

1. Given matching feature vectors and explicit LearningObservation labels, when training runs, then the model binds to their exact dataset digest and lineage.
2. Given a vector and label whose HostState, PhageProfile fingerprint, or target differs, when training runs, then it fails closed.
3. Given insufficient host groups or a train/test partition missing either class, when training runs, then it reports an actionable error rather than fitting a misleading model.

### User Story 3 — Evaluate on unseen host groups and score new vectors (Priority: P1)

A researcher evaluates a baseline on held-out host-genome groups and obtains a clearly marked uncalibrated research score for a compatible new vector.

**Why this priority**: A random row split can leak nearly identical host observations into both partitions and overstate generalization.

**Independent Test**: Verify train/test host groups are disjoint, metrics use only held-out rows, and score output cannot be mistaken for an admitted InteractionPrediction.

**Acceptance Scenarios**:

1. Given multiple host groups, when the dataset is split, then every observation for a host genome belongs to exactly one partition.
2. Given a trained model, when a compatible feature vector is scored, then the output records model/vector hashes and says uncalibrated_research_score.
3. Given a feature vector with a different feature schema, when scoring is requested, then it fails instead of guessing feature order or imputing an absent column.

## Requirements

- **FR-001**: The system MUST bind each feature vector to one exact HostState reference and one exact PhageProfile content fingerprint.
- **FR-002**: Every feature MUST have explicit source, method, version, input digest, source-availability time, and optional source-record references.
- **FR-003**: Missing feature values MUST remain distinguishable from measured zero values; preprocessing parameters MUST be fit on training rows only.
- **FR-013**: Training vectors MUST share the same feature names, per-feature source/method versions, and feature-producer configuration; inference MUST reject semantic schema drift even when feature names match.
- **FR-014**: A feature source MUST have been available no later than the prediction being labeled; future feature sources MUST be rejected to prevent temporal leakage.
- **FR-015**: A training cohort MUST share one assay/label-context signature (arm conditions, readouts, workflow, phenotype type/unit, and assessor protocol); mixed contexts MUST be rejected.
- **FR-004**: Training labels MUST come from admitted LearningObservation records with target productive_infection; labels MUST NOT be inferred from phenotype polarity.
- **FR-005**: The training dataset MUST reject duplicate host-genome/phage pairs and mismatched feature/observation lineage.
- **FR-006**: The split MUST be deterministic and grouped by host genome digest, with disjoint train and test groups.
- **FR-007**: The baseline MUST be reproducible and use no mandatory third-party dependency in the core package.
- **FR-008**: The model artifact MUST retain algorithm/version, parameters, training data digest, feature schema, preprocessing, coefficients, split membership, held-out metrics, and limitations.
- **FR-009**: Evaluation MUST report sample counts, class prevalence, AUROC and average precision when defined, Brier score, and log loss.
- **FR-010**: Raw model scores MUST be clearly labeled uncalibrated and research-only; they MUST NOT be serialized as calibrated InteractionPrediction estimates.
- **FR-011**: v0 MUST model only productive infection. Adsorption and resistance emergence remain not-estimated.
- **FR-012**: The system MUST NOT automatically promote, recalibrate, retrain, update HostState, or trigger execution.

## Key Entities

- **InteractionFeatureVector**: exact HostState/PhageProfile lineage, numeric feature values, explicit missingness, per-feature source records, and feature-producer provenance.
- **ModelTrainingExample**: one feature vector joined to one validated LearningObservation for the same host/phage pair and target.
- **InteractionModelArtifact**: deterministic fitted coefficients and train-only preprocessing plus dataset/split lineage and held-out metrics.
- **ResearchPrediction**: an uncalibrated model score linked to exact model and feature-vector hashes; not a biological verdict or InteractionPrediction.

## Success Criteria

- **SC-001**: Invalid provenance, malformed feature values, mismatched targets, duplicate pairs, and leakage-prone split configurations are rejected by tests.
- **SC-002**: The same admitted input dataset and seed produce identical coefficients, split membership, and metric values.
- **SC-003**: The held-out test set contains no host-genome group present in training.
- **SC-004**: No output is represented as a calibrated infection probability or clinical recommendation.
- **SC-005**: The full repository unittest gate passes.

## Assumptions and Boundaries

- v0 consumes feature vectors emitted by an upstream scientific feature extractor. It does not claim to annotate raw genomes, identify receptors/RBPs, or infer defense-counterdefense mechanisms.
- Test fixtures are software-contract fixtures only; they are not biological evidence and must not be bundled as a training dataset.
- The first model is a research baseline, not a clinically validated model. External validation and probability calibration are separate gates.

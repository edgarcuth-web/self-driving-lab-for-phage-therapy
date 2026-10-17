# Implementation Plan: InteractionModel v0

## Approach

Keep the core dependency-free. Add one domain module that admits provenance-bound numeric feature vectors, joins them to existing LearningObservation records, fits a small L2-regularized logistic baseline, and records a deterministic host-grouped holdout evaluation. A separate research-score artifact prevents raw model output from entering the calibrated InteractionPrediction contract by accident.

## Workstreams

1. **Feature contract**
   - Define FeatureProducer and FeatureSource.
   - Define content-addressed InteractionFeatureVector with exact HostState and PhageProfile lineage.
   - Validate missingness, finite numeric values, source provenance, and serialization integrity.

2. **Training admission and split**
   - Join feature vectors to LearningObservation labels.
   - Require the productive_infection target and exact host/phage lineage.
   - Reject duplicate host-genome/phage pairs.
   - Select a deterministic grouped holdout split by host genome digest; fit all imputation/scaling parameters from training rows only.

3. **Baseline model and evaluation**
   - Fit an L2-regularized logistic model with deterministic optimization.
   - Evaluate held-out AUROC, average precision, Brier score, log loss, and prevalence.
   - Persist a content-addressed research-only model artifact.

4. **Inference boundary**
   - Score compatible feature vectors with a raw, uncalibrated research score.
   - Do not generate InteractionPrediction or claim calibration in this feature slice.

5. **CLI, tests, documentation**
   - Add vector creation, model training, and raw-score commands.
   - Add focused contract, integrity, split, metrics, and CLI tests.
   - Update README, architecture, usage, and AGENTS with the research-only boundary.

## Verification

- First commit the failing tests and confirm CI fails for the missing implementation.
- Implement the smallest slice that satisfies the tests.
- Run python -m unittest discover -s tests -v through GitHub Actions.
- Review the final diff and CI before opening a PR with Refs #33.

import json
from pathlib import Path
import tempfile
import unittest

from phage_lab.biology import GenomeSummary
from phage_lab.host_profile import new_host_profile
from phage_lab.host_state import (
    host_state_reference,
    new_host_state,
    write_host_state,
)
from phage_lab.interaction_evidence import (
    EvidenceProducer,
    HostReference,
    InteractionEvidence,
)
from phage_lab.interaction_prediction import (
    InteractionPrediction,
    PredictionProducer,
    ProbabilityEstimate,
    evidence_only_unresolved_prediction,
    interaction_prediction_from_dict,
    load_interaction_prediction,
    new_interaction_prediction,
    phage_profile_sha256,
    write_interaction_prediction,
)
from phage_lab.interaction_evidence import write_interaction_evidence
from phage_lab.phage_profile import (
    SequenceRef,
    new_natural_phage_profile,
    write_phage_profile,
)


T0 = "2026-10-16T12:00:00+00:00"
T1 = "2026-10-16T13:00:00+00:00"
T2 = "2026-10-16T14:00:00+00:00"
T3 = "2026-10-16T15:00:00+00:00"
HOST_SHA = "a" * 64
PHAGE_SHA = "b" * 64


def host_state():
    profile = new_host_profile(
        "isolate-001",
        GenomeSummary(sha256=HOST_SHA, bases=5_000_000, contigs=1),
        created_at=T0,
    )
    return new_host_state(
        profile,
        host_state_id="host-state-001",
        as_of=T2,
        created_at=T2,
    )


def phage(phage_id="phage-001"):
    return new_natural_phage_profile(
        phage_id,
        collection_id="collection-001",
        isolate_id=f"{phage_id}-isolate",
        recorded_at=T0,
        source_description="Tracked natural isolate.",
        sequence=SequenceRef(sha256=PHAGE_SHA, length=42000),
        created_at=T0,
    )


def evidence(
    *,
    phage_profile_id="phage-001:v1",
    host_profile_id="isolate-001:v1",
    host_genome_sha256=HOST_SHA,
    observed_at=T1,
):
    return InteractionEvidence(
        host=HostReference(
            genome_sha256=host_genome_sha256,
            profile_id=host_profile_id,
        ),
        phage_profile_id=phage_profile_id,
        kind="computational",
        signal="shared_kmer_similarity",
        result={"status": "reported_signal", "value": 17},
        interpretation="Source signal only; not an infection probability.",
        observed_at=observed_at,
        producer=EvidenceProducer(
            name="phist",
            version="1.2.1",
            parameters={"k": 25},
        ),
    )


def estimate(probability):
    return ProbabilityEstimate(
        status="estimated",
        probability=probability,
        uncertainty_lower=max(0.0, probability - 0.1),
        uncertainty_upper=min(1.0, probability + 0.1),
        uncertainty_method="example_interval",
    )


def prediction():
    return new_interaction_prediction(
        host_state(),
        phage(),
        [evidence()],
        prediction_id="prediction-001",
        adsorption=estimate(0.8),
        productive_infection=estimate(0.6),
        resistance_emergence=estimate(0.3),
        mechanistic_explanation=(
            "Example model output for contract testing only."
        ),
        limitations=("Fixture probabilities are not biological claims.",),
        producer=PredictionProducer(
            name="fixture-model",
            version="1.0",
            parameters={"threshold": 0.5},
            artifact_sha256="c" * 64,
        ),
        predicted_at=T3,
    )


class ProbabilityEstimateTests(unittest.TestCase):
    def test_estimated_probability_requires_uncertainty_interval(self):
        with self.assertRaisesRegex(ValueError, "uncertainty_lower"):
            ProbabilityEstimate(
                status="estimated",
                probability=0.5,
            )

    def test_probability_and_interval_are_bounded(self):
        with self.assertRaisesRegex(ValueError, r"\[0, 1\]"):
            ProbabilityEstimate(
                status="estimated",
                probability=1.2,
                uncertainty_lower=0.8,
                uncertainty_upper=1.0,
                uncertainty_method="test",
            )
        with self.assertRaisesRegex(ValueError, "must contain"):
            ProbabilityEstimate(
                status="estimated",
                probability=0.8,
                uncertainty_lower=0.1,
                uncertainty_upper=0.5,
                uncertainty_method="test",
            )

    def test_not_estimated_cannot_hide_placeholder_probability(self):
        with self.assertRaisesRegex(ValueError, "must not contain"):
            ProbabilityEstimate(
                status="not_estimated",
                probability=0.5,
            )


class InteractionPredictionTests(unittest.TestCase):
    def test_prediction_locks_exact_host_state_phage_and_evidence(self):
        state = host_state()
        profile = phage()
        pair_evidence = evidence()
        item = new_interaction_prediction(
            state,
            profile,
            [pair_evidence],
            prediction_id="prediction-001",
            adsorption=estimate(0.8),
            productive_infection=estimate(0.6),
            resistance_emergence=estimate(0.3),
            mechanistic_explanation="Fixture model explanation.",
            limitations=("Fixture only.",),
            producer=PredictionProducer(name="fixture", version="1"),
            predicted_at=T3,
        )

        self.assertEqual(item.host_state.record_id, state.record_id)
        self.assertEqual(item.host_state.content_sha256, state.content_sha256)
        self.assertEqual(item.phage_profile_id, profile.profile_id)
        self.assertEqual(
            item.phage_profile_sha256,
            phage_profile_sha256(profile),
        )
        self.assertEqual(
            item.supporting_evidence_ids,
            (pair_evidence.evidence_id,),
        )

    def test_prediction_rejects_evidence_for_other_phage(self):
        with self.assertRaisesRegex(ValueError, "phage_profile_id"):
            new_interaction_prediction(
                host_state(),
                phage(),
                [evidence(phage_profile_id="other:v1")],
                prediction_id="bad",
                adsorption=estimate(0.8),
                productive_infection=estimate(0.6),
                resistance_emergence=estimate(0.3),
                mechanistic_explanation="Invalid fixture.",
                limitations=("Invalid fixture.",),
                producer=PredictionProducer(name="fixture", version="1"),
                predicted_at=T3,
            )

    def test_prediction_rejects_evidence_for_other_host(self):
        with self.assertRaisesRegex(ValueError, "HostProfile"):
            new_interaction_prediction(
                host_state(),
                phage(),
                [evidence(host_profile_id="other:v1")],
                prediction_id="bad",
                adsorption=estimate(0.8),
                productive_infection=estimate(0.6),
                resistance_emergence=estimate(0.3),
                mechanistic_explanation="Invalid fixture.",
                limitations=("Invalid fixture.",),
                producer=PredictionProducer(name="fixture", version="1"),
                predicted_at=T3,
            )

        with self.assertRaisesRegex(ValueError, "host genome"):
            new_interaction_prediction(
                host_state(),
                phage(),
                [evidence(host_genome_sha256="d" * 64)],
                prediction_id="bad-genome",
                adsorption=estimate(0.8),
                productive_infection=estimate(0.6),
                resistance_emergence=estimate(0.3),
                mechanistic_explanation="Invalid fixture.",
                limitations=("Invalid fixture.",),
                producer=PredictionProducer(name="fixture", version="1"),
                predicted_at=T3,
            )

    def test_prediction_rejects_future_pair_evidence(self):
        with self.assertRaisesRegex(ValueError, "leak future"):
            new_interaction_prediction(
                host_state(),
                phage(),
                [evidence(observed_at=T3)],
                prediction_id="bad",
                adsorption=estimate(0.8),
                productive_infection=estimate(0.6),
                resistance_emergence=estimate(0.3),
                mechanistic_explanation="Invalid fixture.",
                limitations=("Invalid fixture.",),
                producer=PredictionProducer(name="fixture", version="1"),
                predicted_at=T3,
            )

    def test_prediction_time_cannot_precede_host_state(self):
        with self.assertRaisesRegex(ValueError, "must not be earlier"):
            new_interaction_prediction(
                host_state(),
                phage(),
                [evidence()],
                prediction_id="bad-time",
                adsorption=estimate(0.8),
                productive_infection=estimate(0.6),
                resistance_emergence=estimate(0.3),
                mechanistic_explanation="Invalid fixture.",
                limitations=("Invalid fixture.",),
                producer=PredictionProducer(name="fixture", version="1"),
                predicted_at=T1,
            )

    def test_unseen_pair_may_have_no_pairwise_evidence(self):
        item = new_interaction_prediction(
            host_state(),
            phage(),
            [],
            prediction_id="unseen-pair",
            adsorption=estimate(0.7),
            productive_infection=estimate(0.4),
            resistance_emergence=estimate(0.2),
            mechanistic_explanation=(
                "A future feature-based model may predict an unseen pair."
            ),
            limitations=("No pair-specific InteractionEvidence was available.",),
            producer=PredictionProducer(name="future-model", version="1"),
            predicted_at=T3,
        )
        self.assertEqual(item.supporting_evidence_ids, ())

    def test_evidence_only_baseline_does_not_invent_probabilities(self):
        item = evidence_only_unresolved_prediction(
            host_state(),
            phage(),
            [evidence()],
            prediction_id="unresolved-001",
            predicted_at=T3,
        )
        payload = item.to_dict()
        for target in (
            "adsorption",
            "productive_infection",
            "resistance_emergence",
        ):
            self.assertEqual(
                payload["probabilities"][target]["status"],
                "not_estimated",
            )
            self.assertIsNone(
                payload["probabilities"][target]["probability"]
            )
        self.assertIn(
            "No calibrated interaction model",
            item.mechanistic_explanation,
        )

    def test_entirely_unestimated_record_requires_limitation(self):
        unknown = ProbabilityEstimate(status="not_estimated")
        with self.assertRaisesRegex(ValueError, "requires at least one limitation"):
            InteractionPrediction(
                prediction_id="bad",
                revision=1,
                host_state=host_state_reference(host_state()),
                phage_profile_id=phage().profile_id,
                phage_profile_sha256=phage_profile_sha256(phage()),
                supporting_evidence_ids=(),
                adsorption=unknown,
                productive_infection=unknown,
                resistance_emergence=unknown,
                mechanistic_explanation="Nothing estimated.",
                limitations=(),
                producer=PredictionProducer(name="fixture", version="1"),
                predicted_at=T3,
            )

    def test_content_hash_detects_tampering(self):
        item = prediction()
        payload = item.to_dict()
        rebuilt = interaction_prediction_from_dict(payload)
        self.assertEqual(rebuilt.content_sha256, item.content_sha256)

        tampered = json.loads(json.dumps(payload))
        tampered["probabilities"]["adsorption"]["probability"] = 0.7
        with self.assertRaisesRegex(ValueError, "content_sha256"):
            interaction_prediction_from_dict(tampered)

    def test_file_round_trip(self):
        item = prediction()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "prediction.json"
            write_interaction_prediction(item, path)
            loaded = load_interaction_prediction(path)
        self.assertEqual(loaded.to_dict(), item.to_dict())


class InteractionPredictionCliTests(unittest.TestCase):
    def test_cli_creates_evidence_only_unresolved_prediction(self):
        from phage_lab.__main__ import main

        state = host_state()
        profile = phage()
        pair_evidence = evidence()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_path = root / "host-state.json"
            phage_path = root / "phage.json"
            evidence_path = root / "evidence.json"
            out = root / "prediction.json"
            write_host_state(state, state_path)
            write_phage_profile(profile, phage_path)
            write_interaction_evidence(pair_evidence, evidence_path)

            self.assertEqual(
                0,
                main([
                    "interaction-prediction",
                    "--host-state", str(state_path),
                    "--phage-profile", str(phage_path),
                    "--interaction-evidence", str(evidence_path),
                    "--prediction-id", "prediction-cli",
                    "--evidence-only-unresolved",
                    "--predicted-at", T3,
                    "--out", str(out),
                ]),
            )
            loaded = load_interaction_prediction(out)
            self.assertEqual(loaded.adsorption.status, "not_estimated")
            self.assertEqual(
                loaded.supporting_evidence_ids,
                (pair_evidence.evidence_id,),
            )

    def test_cli_ingests_explicit_model_output_with_uncertainty(self):
        from phage_lab.__main__ import main

        state = host_state()
        profile = phage()
        pair_evidence = evidence()
        model_output = {
            "probabilities": {
                "adsorption": estimate(0.8).to_dict(),
                "productive_infection": estimate(0.6).to_dict(),
                "resistance_emergence": estimate(0.3).to_dict(),
            },
            "mechanistic_explanation": "Explicit fixture model output.",
            "limitations": ["Fixture only."],
            "producer": PredictionProducer(
                name="fixture-model",
                version="1.0",
                parameters={"feature_set": "test"},
                artifact_sha256="c" * 64,
            ).to_dict(),
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_path = root / "host-state.json"
            phage_path = root / "phage.json"
            evidence_path = root / "evidence.json"
            model_path = root / "model-output.json"
            out = root / "prediction.json"
            write_host_state(state, state_path)
            write_phage_profile(profile, phage_path)
            write_interaction_evidence(pair_evidence, evidence_path)
            model_path.write_text(json.dumps(model_output), encoding="utf-8")

            self.assertEqual(
                0,
                main([
                    "interaction-prediction",
                    "--host-state", str(state_path),
                    "--phage-profile", str(phage_path),
                    "--interaction-evidence", str(evidence_path),
                    "--prediction-id", "prediction-cli",
                    "--prediction-input", str(model_path),
                    "--predicted-at", T3,
                    "--out", str(out),
                ]),
            )
            loaded = load_interaction_prediction(out)
            self.assertEqual(loaded.adsorption.probability, 0.8)
            self.assertEqual(
                loaded.productive_infection.uncertainty_method,
                "example_interval",
            )
            self.assertEqual(
                loaded.producer.artifact_sha256,
                "c" * 64,
            )

    def test_cli_refuses_probability_without_uncertainty(self):
        from phage_lab.__main__ import main

        state = host_state()
        profile = phage()
        model_output = {
            "probabilities": {
                "adsorption": {
                    "status": "estimated",
                    "probability": 0.8,
                    "uncertainty_lower": None,
                    "uncertainty_upper": None,
                    "uncertainty_method": None,
                },
                "productive_infection": ProbabilityEstimate(
                    status="not_estimated"
                ).to_dict(),
                "resistance_emergence": ProbabilityEstimate(
                    status="not_estimated"
                ).to_dict(),
            },
            "mechanistic_explanation": "Invalid model output.",
            "limitations": ["Invalid fixture."],
            "producer": PredictionProducer(
                name="fixture-model",
                version="1.0",
            ).to_dict(),
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_path = root / "host-state.json"
            phage_path = root / "phage.json"
            model_path = root / "model-output.json"
            out = root / "prediction.json"
            write_host_state(state, state_path)
            write_phage_profile(profile, phage_path)
            model_path.write_text(json.dumps(model_output), encoding="utf-8")

            self.assertEqual(
                2,
                main([
                    "interaction-prediction",
                    "--host-state", str(state_path),
                    "--phage-profile", str(phage_path),
                    "--prediction-id", "bad-cli",
                    "--prediction-input", str(model_path),
                    "--predicted-at", T3,
                    "--out", str(out),
                ]),
            )
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()

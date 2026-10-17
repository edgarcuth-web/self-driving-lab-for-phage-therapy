"""Cross-repository model exchange contract tests; no biological claims."""

from dataclasses import replace
import unittest

from phage_lab.model_contract import (
    ModelResult,
    admit_model_result,
    model_request_from_dict,
    model_result_from_dict,
    new_model_request,
)
from phage_lab.interaction_prediction import PredictionProducer, ProbabilityEstimate
from fixtures_screening import T2, T3, phage, state

UNKNOWN = ProbabilityEstimate(status="not_estimated")


def make_request(profile=None, targets=("productive_infection",)):
    return new_model_request(
        state(),
        profile or phage("model-contract-phage"),
        request_id="model-request-001",
        requested_targets=targets,
        created_at=T2,
    )


def make_result(req, *, profile=None, producer=None, predicted_at=T3):
    profile = profile or phage("model-contract-phage")
    return ModelResult(
        result_id="model-result-001",
        request_id=req.request_id,
        request_sha256=req.content_sha256,
        host_state=req.host_state,
        phage_profile_id=profile.profile_id,
        phage_profile_sha256=req.phage_profile_sha256,
        adsorption=UNKNOWN,
        productive_infection=ProbabilityEstimate(
            status="estimated",
            probability=0.7,
            uncertainty_lower=0.6,
            uncertainty_upper=0.8,
            uncertainty_method="external-validation-placeholder",
        ),
        resistance_emergence=UNKNOWN,
        mechanistic_explanation="Software contract fixture only.",
        limitations=("No biological claim; fixture only.",),
        producer=producer or PredictionProducer(
            name="external-fixture-model",
            version="1",
            parameters={"contract_fixture": True},
            artifact_sha256="c" * 64,
        ),
        predicted_at=predicted_at,
    )


class ModelContractTests(unittest.TestCase):
    def test_request_round_trip_is_content_addressed(self):
        item = make_request()
        self.assertEqual(model_request_from_dict(item.to_dict()), item)
        tampered = item.to_dict()
        tampered["phage_profile_id"] = "wrong:v1"
        with self.assertRaisesRegex(ValueError, "hash|derived"):
            model_request_from_dict(tampered)

    def test_result_round_trip_is_content_addressed(self):
        req = make_request()
        item = make_result(req)
        self.assertEqual(model_result_from_dict(item.to_dict()), item)
        tampered = item.to_dict()
        tampered["mechanistic_explanation"] = "tampered"
        with self.assertRaisesRegex(ValueError, "hash|derived"):
            model_result_from_dict(tampered)

    def test_admission_creates_exact_interaction_prediction(self):
        host = state()
        profile = phage("model-contract-phage")
        req = new_model_request(
            host,
            profile,
            request_id="model-request-001",
            requested_targets=("productive_infection",),
            created_at=T2,
        )
        item = make_result(req, profile=profile)
        prediction = admit_model_result(
            req,
            item,
            host,
            profile,
            prediction_id="prediction-from-external-model",
        )
        self.assertEqual(prediction.host_state, req.host_state)
        self.assertEqual(prediction.phage_profile_id, profile.profile_id)
        self.assertEqual(prediction.producer.artifact_sha256, "c" * 64)
        self.assertEqual(prediction.productive_infection.probability, 0.7)

    def test_result_must_bind_exact_request_hash(self):
        host = state()
        profile = phage("model-contract-phage")
        req = new_model_request(
            host, profile, request_id="model-request-001", created_at=T2
        )
        item = replace(make_result(req, profile=profile), request_sha256="d" * 64)
        with self.assertRaisesRegex(ValueError, "exact ModelRequest"):
            admit_model_result(
                req, item, host, profile, prediction_id="prediction-001"
            )

    def test_result_must_bind_exact_phage(self):
        host = state()
        profile = phage("model-contract-phage")
        req = new_model_request(
            host, profile, request_id="model-request-001", created_at=T2
        )
        item = replace(make_result(req, profile=profile), phage_profile_id="other:v1")
        with self.assertRaisesRegex(ValueError, "PhageProfile"):
            admit_model_result(
                req, item, host, profile, prediction_id="prediction-001"
            )

    def test_unrequested_target_cannot_be_estimated(self):
        host = state()
        profile = phage("model-contract-phage")
        req = new_model_request(
            host,
            profile,
            request_id="model-request-001",
            requested_targets=("productive_infection",),
            created_at=T2,
        )
        item = replace(
            make_result(req, profile=profile),
            adsorption=ProbabilityEstimate(
                status="estimated",
                probability=0.5,
                uncertainty_lower=0.4,
                uncertainty_upper=0.6,
                uncertainty_method="fixture",
            ),
        )
        with self.assertRaisesRegex(ValueError, "unrequested target"):
            admit_model_result(
                req, item, host, profile, prediction_id="prediction-001"
            )

    def test_estimated_output_requires_model_artifact_digest(self):
        req = make_request()
        with self.assertRaisesRegex(ValueError, "artifact_sha256"):
            make_result(
                req,
                producer=PredictionProducer(name="external-fixture-model", version="1"),
            )

    def test_result_cannot_predate_request(self):
        host = state()
        profile = phage("model-contract-phage")
        req = new_model_request(
            host, profile, request_id="model-request-001", created_at=T3
        )
        item = make_result(req, profile=profile, predicted_at=T2)
        with self.assertRaisesRegex(ValueError, "predate"):
            admit_model_result(
                req, item, host, profile, prediction_id="prediction-001"
            )


if __name__ == "__main__":
    unittest.main()

"""Ensure the shared wire fixtures match the lab's semantic v1 contract."""

import json
from pathlib import Path
import unittest

from phage_lab.model_contract import model_request_from_dict, model_result_from_dict

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"
FIXTURE_DIR = ROOT / "tests" / "fixtures"
TARGETS = ["adsorption", "productive_infection", "resistance_emergence"]


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


class ModelWireSchemaFixtureTests(unittest.TestCase):
    def test_shared_request_fixture_round_trips_through_lab_contract(self):
        fixture = load_json(FIXTURE_DIR / "model_request_v1.json")
        request = model_request_from_dict(fixture)
        self.assertEqual(request.to_dict(), fixture)
        self.assertEqual(request.request_id, fixture["record_id"])

    def test_shared_result_fixture_round_trips_through_lab_contract(self):
        fixture = load_json(FIXTURE_DIR / "model_result_v1.json")
        result = model_result_from_dict(fixture)
        self.assertEqual(result.to_dict(), fixture)
        self.assertEqual(result.result_id, fixture["record_id"])

    def test_model_side_unresolved_output_round_trips_through_lab_contract(self):
        request_data = load_json(FIXTURE_DIR / "model_request_v1.json")
        result_data = load_json(FIXTURE_DIR / "model_result_unresolved_v1.json")
        request = model_request_from_dict(request_data)
        result = model_result_from_dict(result_data)

        self.assertEqual(result.to_dict(), result_data)
        self.assertEqual(result.request_id, request.request_id)
        self.assertEqual(result.request_sha256, request.content_sha256)
        self.assertEqual(result.host_state, request.host_state)
        self.assertEqual(result.phage_profile_id, request.phage_profile_id)
        self.assertEqual(
            result.phage_profile_sha256, request.phage_profile_sha256
        )
        self.assertIsNone(result.producer.artifact_sha256)
        for target in TARGETS:
            self.assertEqual(getattr(result, target).status, "not_estimated")

    def test_request_and_result_fixtures_bind_exact_same_lineage(self):
        request = load_json(FIXTURE_DIR / "model_request_v1.json")
        result = load_json(FIXTURE_DIR / "model_result_v1.json")
        self.assertEqual(result["request_id"], request["request_id"])
        self.assertEqual(result["request_sha256"], request["content_sha256"])
        self.assertEqual(result["host_state"], request["host_state"])
        self.assertEqual(
            result["phage_profile_id"], request["phage_profile_id"]
        )
        self.assertEqual(
            result["phage_profile_sha256"], request["phage_profile_sha256"]
        )
        self.assertEqual(
            set(result["probabilities"]),
            set(TARGETS),
        )

    def test_schema_files_declare_v1_and_exact_prediction_targets(self):
        request_schema = load_json(SCHEMA_DIR / "model-request-v1.schema.json")
        result_schema = load_json(SCHEMA_DIR / "model-result-v1.schema.json")
        self.assertEqual(request_schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(result_schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(request_schema["properties"]["schema_version"]["const"], 1)
        self.assertEqual(result_schema["properties"]["schema_version"]["const"], 1)
        self.assertEqual(
            request_schema["properties"]["requested_targets"]["items"]["enum"],
            TARGETS,
        )
        self.assertEqual(
            result_schema["properties"]["probabilities"]["required"],
            TARGETS,
        )


if __name__ == "__main__":
    unittest.main()

from dataclasses import replace
import unittest

from fixtures_screening import T0, T1, T2, T3, phage, prediction, state

from phage_lab.host_state import host_state_reference
from phage_lab.phage_profile import new_engineered_phage_profile
from phage_lab.scientific_control import ScientificObjective, ScientificOrchestrator


class ScientificTaskDecompositionTests(unittest.TestCase):
    def objective(self):
        return ScientificObjective(
            objective_id="fixture-objective",
            revision=1,
            kind="prioritize_natural_phages",
            statement="Prioritize existing natural phages for screening.",
            host_state=host_state_reference(state()),
            created_at=T1,
        )

    def decompose(self, profiles, predictions):
        return ScientificOrchestrator().decompose_natural_phage_screening(
            self.objective(),
            state(),
            profiles,
            predictions,
            plan_id="fixture-plan",
            created_at=T3,
        )

    def test_missing_pair_prediction_creates_exact_model_request_handoff(self):
        a, b = phage("a"), phage("b")
        plan, requests = self.decompose([b, a], [prediction(a, 0.4, 0.6, 0.8)])

        self.assertEqual([request.phage_profile_id for request in requests], [b.profile_id])
        request = requests[0]
        self.assertEqual(request.host_state, host_state_reference(state()))
        self.assertEqual(request.requested_targets,
                         ("adsorption", "productive_infection", "resistance_emergence"))

        handoff = next(task for task in plan.tasks if task.kind == "obtain_pair_prediction")
        self.assertEqual(handoff.state, "handoff_required")
        self.assertEqual(handoff.subject_phage_profile_id, b.profile_id)
        self.assertEqual(handoff.module_id, "model_request_builder")
        self.assertEqual(handoff.module_version, "1")
        self.assertEqual(handoff.outputs[0].artifact_type, "ModelRequest")
        self.assertEqual(handoff.outputs[0].artifact_id, request.record_id)
        self.assertEqual(handoff.outputs[0].content_sha256, request.content_sha256)

        recommendation = next(task for task in plan.tasks if task.kind == "prioritize_natural_phages")
        self.assertEqual(recommendation.state, "blocked")
        self.assertEqual(recommendation.depends_on, (handoff.task_id,))
        self.assertIn("missing", recommendation.reason.lower())

    def test_all_explicit_predictions_make_recommendation_ready(self):
        a, b = phage("a"), phage("b")
        plan, requests = self.decompose(
            [a, b],
            [prediction(a, 0.4, 0.6, 0.8), prediction(b)],
        )

        self.assertEqual(requests, ())
        self.assertEqual(
            [(task.kind, task.state) for task in plan.tasks],
            [("prioritize_natural_phages", "ready")],
        )
        self.assertEqual(plan.tasks[0].depends_on, ())

    def test_not_estimated_is_explicit_pair_state_not_missing(self):
        a = phage("a")
        plan, requests = self.decompose([a], [prediction(a)])
        self.assertEqual(requests, ())
        self.assertEqual(plan.tasks[0].state, "ready")

    def test_engineered_phage_does_not_create_natural_screening_handoff(self):
        natural = phage("natural")
        engineered = new_engineered_phage_profile(
            "engineered",
            design_id="fixture-design",
            parent_profile_ids=(natural.profile_id,),
            designed_at=T0,
            created_at=T0,
        )

        plan, requests = self.decompose([engineered, natural], [prediction(natural)])

        self.assertEqual(requests, ())
        self.assertEqual(len(plan.tasks), 1)
        self.assertEqual(plan.tasks[0].kind, "prioritize_natural_phages")
        self.assertEqual(plan.tasks[0].state, "ready")
        self.assertNotIn(engineered.profile_id, plan.required_pair_profile_ids)

    def test_decomposition_is_input_order_independent(self):
        profiles = [phage(name) for name in "cba"]
        predictions = [prediction(profiles[0]), prediction(profiles[2], 0.4, 0.6, 0.8)]

        left, left_requests = self.decompose(profiles, predictions)
        right, right_requests = self.decompose(
            list(reversed(profiles)), list(reversed(predictions))
        )

        self.assertEqual(left.content_sha256, right.content_sha256)
        self.assertEqual(
            [request.content_sha256 for request in left_requests],
            [request.content_sha256 for request in right_requests],
        )

    def test_duplicate_or_mismatched_predictions_fail_closed(self):
        a, b = phage("a"), phage("b")
        pa = prediction(a)

        with self.assertRaisesRegex(ValueError, "one prediction per phage"):
            self.decompose([a], [pa, replace(pa, revision=2)])

        with self.assertRaisesRegex(ValueError, "outside the supplied pool"):
            self.decompose([a], [prediction(b)])

        changed = replace(a, source_annotations={"changed": "content"})
        with self.assertRaisesRegex(ValueError, "exact PhageProfile"):
            self.decompose([changed], [pa])

        other_state = replace(state(), revision=2)
        wrong_host = replace(pa, host_state=host_state_reference(other_state))
        with self.assertRaisesRegex(ValueError, "exact HostState"):
            self.decompose([a], [wrong_host])


if __name__ == "__main__":
    unittest.main()

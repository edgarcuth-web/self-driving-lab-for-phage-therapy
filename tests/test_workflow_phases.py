"""Pure phase helpers extracted from workflow.run_experiment."""

from types import SimpleNamespace
import unittest

from phage_lab.workflow import _execution_payload, _new_report


class Agent:
    name = "rule"


def spec(*, design=True):
    arm = SimpleNamespace(to_dict=lambda: {"arm_id": "treatment"})
    return SimpleNamespace(
        spec_id="spec-1:v1",
        content_sha256="a" * 64,
        member_phage_profile_ids=("phage-a", "phage-b"),
        arms=(arm,),
        source_design=SimpleNamespace(design_id="design-1") if design else None,
    )


class NewReportTests(unittest.TestCase):
    def test_virtual_run_states_its_limitations(self):
        report = _new_report(agent=Agent(), execution_mode="virtual_hardware", sample_id="s1",
                             experiment_spec=None, bound_materials=None)
        self.assertEqual(report["status"], "running")
        self.assertTrue(report["simulated"])
        self.assertFalse(report["physical_execution"])
        self.assertFalse(report["scientific_membership_locked"])
        self.assertEqual(report["agent"], "rule")
        self.assertEqual(len(report["limitations"]), 2)

    def test_virtual_run_with_materials_adds_lineage_only_limitation(self):
        report = _new_report(agent=object(), execution_mode="virtual_hardware", sample_id="s1",
                             experiment_spec=spec(), bound_materials=object())
        self.assertEqual(report["agent"], "object")
        self.assertTrue(report["scientific_membership_locked"])
        self.assertIn("lineage only", report["limitations"][-1])

    def test_physical_run_has_only_the_efficacy_limitation(self):
        report = _new_report(agent=Agent(), execution_mode="real_hardware", sample_id="s1",
                             experiment_spec=spec(), bound_materials=object())
        self.assertFalse(report["simulated"])
        self.assertEqual(report["limitations"],
                         ["Biological efficacy is not inferred by the orchestration layer."])


class ExecutionPayloadTests(unittest.TestCase):
    def test_legacy_payload_carries_only_sample_and_candidates(self):
        payload = _execution_payload("s1", {"candidate_ids": ("a", "b")}, None, None)
        self.assertEqual(payload, {"sample_id": "s1", "candidate_ids": ["a", "b"]})

    def test_spec_payload_carries_full_lineage(self):
        materials = SimpleNamespace(batch_ids=("host-batch", "phage-batch"))
        payload = _execution_payload("s1", {"candidate_ids": ["a"]}, spec(), materials)
        self.assertEqual(payload, {
            "sample_id": "s1",
            "candidate_ids": ["a"],
            "experiment_spec_id": "spec-1:v1",
            "experiment_spec_sha256": "a" * 64,
            "phage_profile_ids": ["phage-a", "phage-b"],
            "experiment_arms": [{"arm_id": "treatment"}],
            "cocktail_design_id": "design-1",
            "material_batch_ids": ["host-batch", "phage-batch"],
        })

    def test_spec_without_design_or_materials_omits_those_fields(self):
        payload = _execution_payload("s1", {"candidate_ids": ["a"]}, spec(design=False), None)
        self.assertNotIn("cocktail_design_id", payload)
        self.assertNotIn("material_batch_ids", payload)


if __name__ == "__main__":
    unittest.main()

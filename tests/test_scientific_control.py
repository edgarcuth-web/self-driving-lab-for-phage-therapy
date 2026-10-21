import ast
from dataclasses import replace
from pathlib import Path
import unittest

from fixtures_screening import T1, T3, phage, prediction, state

from phage_lab.scientific_control import (
    ScientificClaim,
    ScientificObjective,
    ScientificOrchestrator,
    ScientificReviewer,
)


class ScientificControlVerticalSliceTests(unittest.TestCase):
    def objective(self):
        return ScientificObjective(
            objective_id="fixture-objective",
            revision=1,
            kind="prioritize_natural_phages",
            statement="Prioritize existing natural phages for the next screening experiment.",
            host_state=host_state_reference(state()),
            created_at=T1,
        )

    def test_orchestrator_invokes_only_registered_recommender_and_records_lineage(self):
        profiles = [phage("a"), phage("b")]
        predictions = [prediction(profiles[0], 0.4, 0.6, 0.8), prediction(profiles[1])]

        candidate_set, proposal = ScientificOrchestrator().prioritize_natural_phages(
            self.objective(),
            state(),
            profiles,
            predictions,
            candidate_set_id="fixture-candidates",
            proposal_id="fixture-proposal",
            created_at=T3,
        )

        self.assertEqual(proposal.claim.kind, "screening_priority")
        self.assertEqual(proposal.candidate_set.artifact_id, candidate_set.record_id)
        self.assertEqual(proposal.candidate_set.content_sha256, candidate_set.content_sha256)
        self.assertEqual(proposal.selected_phage_profile_ids, candidate_set.selected_phage_profile_ids)
        self.assertEqual(proposal.invocation.module_id, "natural_phage_recommender")
        self.assertEqual(proposal.invocation.module_version, "1")
        self.assertEqual(proposal.invocation.output, proposal.candidate_set)
        self.assertEqual(proposal.evidence_state, "mixed")
        self.assertIn("screening", proposal.claim.statement.lower())

    def test_exploration_only_stays_explicitly_unresolved_but_can_be_approved_for_screening(self):
        profiles = [phage("a"), phage("b")]
        candidate_set, proposal = ScientificOrchestrator().prioritize_natural_phages(
            self.objective(),
            state(),
            profiles,
            [prediction(p) for p in profiles],
            candidate_set_id="fixture-candidates",
            proposal_id="fixture-proposal",
            created_at=T3,
        )

        self.assertEqual(proposal.evidence_state, "exploration_only")
        self.assertNotIn("efficacy", proposal.claim.statement.lower())
        before = candidate_set.content_sha256
        review = ScientificReviewer().review(
            self.objective(),
            proposal,
            candidate_set,
            review_id="fixture-review",
            reviewed_at=T3,
        )
        self.assertEqual(review.decision, "approved")
        self.assertEqual(candidate_set.content_sha256, before)
        self.assertIn("exploration_only", {finding.code for finding in review.findings})

    def test_reviewer_rejects_semantic_upgrade_to_efficacy(self):
        p = phage("a")
        candidate_set, proposal = ScientificOrchestrator().prioritize_natural_phages(
            self.objective(),
            state(),
            [p],
            [prediction(p, 0.4, 0.6, 0.8)],
            candidate_set_id="fixture-candidates",
            proposal_id="fixture-proposal",
            created_at=T3,
        )
        unsafe = replace(
            proposal,
            claim=ScientificClaim(
                kind="efficacy",
                statement="This phage is efficacious against the host.",
            ),
        )

        review = ScientificReviewer().review(
            self.objective(),
            unsafe,
            candidate_set,
            review_id="fixture-review",
            reviewed_at=T3,
        )

        self.assertEqual(review.decision, "revision_required")
        self.assertIn("unsupported_semantic_upgrade", {finding.code for finding in review.findings})

    def test_empty_selection_abstains(self):
        candidate_set, proposal = ScientificOrchestrator().prioritize_natural_phages(
            self.objective(),
            state(),
            [phage("a")],
            [],
            candidate_set_id="fixture-candidates",
            proposal_id="fixture-proposal",
            created_at=T3,
        )
        review = ScientificReviewer().review(
            self.objective(),
            proposal,
            candidate_set,
            review_id="fixture-review",
            reviewed_at=T3,
        )
        self.assertEqual(candidate_set.selected_phage_profile_ids, ())
        self.assertEqual(review.decision, "abstained")

    def test_scientific_control_package_has_no_execution_imports(self):
        package = Path(__file__).resolve().parents[1] / "phage_lab" / "scientific_control"
        forbidden = {"workflow", "devices", "agents", "virtual_hardware", "material_batch"}
        found = []
        for path in package.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                module = None
                if isinstance(node, ast.ImportFrom):
                    module = node.module
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        root = alias.name.split(".")[-1]
                        if root in forbidden:
                            found.append((path.name, alias.name))
                if module and module.split(".")[-1] in forbidden:
                    found.append((path.name, module))
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()

"""Pin pre-refactor content hashes so cleanup cannot silently rewrite lineage."""

import unittest

from fixtures_feedback import screen, review, CRITERION
from fixtures_screening import phage, prediction, recommend
from fixtures_results import STAMP
from phage_lab.active_learning import plan_next_screen, experiment_spec_from_active_learning
from phage_lab.natural_phage_recommender import RecommendationPolicy


class ArtifactCompatibilityTests(unittest.TestCase):
    def test_feedback_chain_keeps_pre_refactor_hashes(self):
        # Deterministic software fixtures exported by main@c55dd56 before refactoring.
        profiles = [phage(name) for name in "abcd"]
        pool = recommend(profiles, [prediction(p) for p in profiles],
                         policy=RecommendationPolicy(2, 1))
        spec = screen(pool)
        feedback = review(spec)
        decision = plan_next_screen(pool, spec, [feedback], decision_id="round-two",
                                    criterion=CRITERION, created_at=STAMP)
        next_spec = experiment_spec_from_active_learning(
            decision, experiment_id="next-contract-spec", created_at="2026-10-16T19:32:00+00:00",
        )
        expected = [
            (pool, "d36811c1a27f0bc4f1b5b427e98fe880e4de2522494366626b325ba3e1e5b332"),
            (spec, "9241f409fa01622f7450aa5fd5152ac24744d4ab2a64b6612243c1cca1714365"),
            (feedback, "c3c3ac75049376d1e1d18a73bc8b66d83c7f7b478cbf876329bb276b75aee492"),
            (decision, "3ff02c4cfe22361f0214c2fdcce7c681018463da8b29f0c4a82d037c00be9a28"),
            (next_spec, "2edd2a58abd9de757a059031d59a2573bf4528e0c09212d1017d446015a72872"),
        ]
        for artifact, digest in expected:
            with self.subTest(artifact=type(artifact).__name__):
                self.assertEqual(artifact.content_sha256, digest)
                self.assertEqual(artifact.to_dict()["content_sha256"], digest)

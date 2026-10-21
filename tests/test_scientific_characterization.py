from dataclasses import replace
import hashlib
import unittest
from unittest.mock import patch

from fixtures_screening import T0, T1, T2, T3, phage, prediction, state

from phage_lab.artifacts import canonical_content_sha256, canonical_json
from phage_lab.biology import GenomeSummary
from phage_lab.host_profile import (
    AnalysisRun,
    FeatureGroup,
    new_host_profile,
)
from phage_lab.padloc_adapter import PADLOC_VERSION, run_padloc_host_defense
from phage_lab.scientific_control import ScientificObjective, ScientificOrchestrator
from phage_lab.scientific_control.registry import (
    PADLOC_HOST_DEFENSE_ID,
    TRUSTED_MODULES,
)


def objective():
    item = state()
    return ScientificObjective(
        objective_id="fixture-objective",
        revision=1,
        kind="prioritize_natural_phages",
        statement="Prioritize existing natural phages for screening.",
        host_state=item.reference if hasattr(item, "reference") else None,
        created_at=T1,
    )


def exact_objective():
    from phage_lab.host_state import host_state_reference
    item = state()
    return ScientificObjective(
        objective_id="fixture-objective",
        revision=1,
        kind="prioritize_natural_phages",
        statement="Prioritize existing natural phages for screening.",
        host_state=host_state_reference(item),
        created_at=T1,
    )


def host_profile(*, assessed=False):
    profile = new_host_profile(
        "fixture-host",
        GenomeSummary(sha256="a" * 64, bases=100, contigs=1),
        created_at=T0,
    )
    if not assessed:
        return profile
    features = dict(profile.features)
    features["defense_systems"] = FeatureGroup(
        status="assessed",
        items=(),
        note="Explicit admitted assessment fixture.",
    )
    return replace(
        profile,
        features=features,
        analysis_runs=(
            AnalysisRun(
                analyzer="fixture-defense-admission",
                version="1",
                analyzed_at=T1,
                input_sha256=profile.genome.sha256,
            ),
        ),
    )


def padloc_artifact(*, source_record_sha256=None, sequence_sha256="a" * 64):
    source_record_sha256 = source_record_sha256 or state().content_sha256
    parameters = {}
    document = {
        "schema_version": 1,
        "artifact_id": "padloc-fixture",
        "created_at": T2,
        "feature_set": "host_defense_systems",
        "subject": {
            "kind": "host_genome",
            "id": state().record_id,
            "sequence_sha256": sequence_sha256,
            "input_file_sha256": "b" * 64,
            "length_bases": 100,
            "contigs": 1,
            "source_record_sha256": source_record_sha256,
            "source_record_file_sha256": "c" * 64,
        },
        "analysis": {
            "tool": {"name": "PADLOC", "version": PADLOC_VERSION},
            "started_at": T2,
            "finished_at": T2,
            "parameters": parameters,
            "parameters_sha256": hashlib.sha256(
                canonical_json(parameters).encode("utf-8")
            ).hexdigest(),
            "reference_data": [
                {
                    "name": "PADLOC-DB",
                    "version": "v2.0.0",
                    "sha256": "d" * 64,
                }
            ],
        },
        "outputs": [
            {
                "role": "primary",
                "path": "outputs/host-defense-summary.json",
                "format": "json",
                "media_type": "application/json",
                "sha256": "e" * 64,
                "size_bytes": 1,
            }
        ],
        "status": "complete",
        "limitations": ["Computational annotation fixture only."],
    }
    document["content_sha256"] = canonical_content_sha256(document)
    return document


class HostDefensePlanningTests(unittest.TestCase):
    def decompose(self, *, profile, artifacts=(), profiles=None, predictions=()):
        profiles = profiles if profiles is not None else [phage("a")]
        return ScientificOrchestrator().decompose_natural_phage_screening(
            exact_objective(),
            state(),
            profiles,
            list(predictions),
            plan_id="fixture-plan",
            created_at=T3,
            host_profile=profile,
            feature_artifacts=tuple(artifacts),
        )

    def test_unknown_defense_systems_gate_pair_model_handoffs(self):
        plan, requests = self.decompose(profile=host_profile())
        self.assertEqual(requests, ())
        self.assertEqual(
            [(task.kind, task.state) for task in plan.tasks],
            [
                ("characterize_host_defense", "ready"),
                ("prioritize_natural_phages", "blocked"),
            ],
        )
        characterization, recommendation = plan.tasks
        self.assertEqual(characterization.module_id, PADLOC_HOST_DEFENSE_ID)
        self.assertEqual(recommendation.depends_on, (characterization.task_id,))
        self.assertNotIn("obtain_pair_prediction", [task.kind for task in plan.tasks])

    def test_matching_padloc_artifact_requires_admission_not_silent_promotion(self):
        artifact = padloc_artifact()
        plan, requests = self.decompose(profile=host_profile(), artifacts=(artifact,))
        self.assertEqual(requests, ())
        admission, recommendation = plan.tasks
        self.assertEqual(admission.kind, "admit_host_defense_characterization")
        self.assertEqual(admission.state, "handoff_required")
        self.assertEqual(admission.inputs[-1].artifact_type, "FeatureArtifact")
        self.assertEqual(admission.inputs[-1].artifact_id, artifact["artifact_id"])
        self.assertEqual(admission.inputs[-1].content_sha256, artifact["content_sha256"])
        self.assertEqual(recommendation.state, "blocked")
        self.assertEqual(recommendation.depends_on, (admission.task_id,))

    def test_assessed_host_profile_releases_existing_prediction_planning(self):
        a = phage("a")
        plan, requests = self.decompose(
            profile=host_profile(assessed=True),
            profiles=[a],
            predictions=(),
        )
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].phage_profile_id, a.profile_id)
        self.assertEqual(
            [(task.kind, task.state) for task in plan.tasks],
            [
                ("obtain_pair_prediction", "handoff_required"),
                ("prioritize_natural_phages", "blocked"),
            ],
        )

    def test_explicit_prediction_and_assessed_profile_make_recommendation_ready(self):
        a = phage("a")
        plan, requests = self.decompose(
            profile=host_profile(assessed=True),
            profiles=[a],
            predictions=(prediction(a),),
        )
        self.assertEqual(requests, ())
        self.assertEqual([(task.kind, task.state) for task in plan.tasks],
                         [("prioritize_natural_phages", "ready")])

    def test_host_profile_must_match_exact_host_state(self):
        wrong = new_host_profile(
            "other-host",
            GenomeSummary(sha256="a" * 64, bases=100, contigs=1),
            created_at=T0,
        )
        with self.assertRaisesRegex(ValueError, "HostProfile"):
            self.decompose(profile=wrong)

    def test_mismatched_padloc_artifact_fails_closed(self):
        artifact = padloc_artifact(source_record_sha256="f" * 64)
        with self.assertRaisesRegex(ValueError, "PADLOC FeatureArtifact"):
            self.decompose(profile=host_profile(), artifacts=(artifact,))

    def test_padloc_is_explicitly_registered_trusted_module(self):
        module = TRUSTED_MODULES[PADLOC_HOST_DEFENSE_ID]
        self.assertIs(module.call, run_padloc_host_defense)


class HostDefenseExecutionTests(unittest.TestCase):
    def test_executor_only_runs_ready_registered_padloc_task_and_records_output(self):
        orchestrator = ScientificOrchestrator()
        plan, _ = orchestrator.decompose_natural_phage_screening(
            exact_objective(),
            state(),
            [phage("a")],
            [],
            plan_id="fixture-plan",
            created_at=T3,
            host_profile=host_profile(),
        )
        task = plan.tasks[0]
        artifact = padloc_artifact()

        class FakeModule:
            module_id = PADLOC_HOST_DEFENSE_ID
            version = "1"

            @staticmethod
            def call(**kwargs):
                return {"artifact": artifact, "manifest_path": "fixture-manifest"}

        with patch(
            "phage_lab.scientific_control.characterization.TRUSTED_MODULES",
            {PADLOC_HOST_DEFENSE_ID: FakeModule()},
        ):
            result, invocation = orchestrator.execute_host_defense_characterization(
                task,
                host_state_path="host-state.json",
                sequence_registry_path="sequence-registry.json",
                padloc_data_dir="padloc-db",
                output_dir="output",
            )

        self.assertEqual(result["artifact"]["artifact_id"], artifact["artifact_id"])
        self.assertEqual(invocation.module_id, PADLOC_HOST_DEFENSE_ID)
        self.assertEqual(invocation.inputs, task.inputs)
        self.assertEqual(invocation.output.artifact_type, "FeatureArtifact")
        self.assertEqual(invocation.output.content_sha256, artifact["content_sha256"])

    def test_executor_refuses_non_characterization_task(self):
        orchestrator = ScientificOrchestrator()
        plan, _ = orchestrator.decompose_natural_phage_screening(
            exact_objective(),
            state(),
            [phage("a")],
            [prediction(phage("a"))],
            plan_id="fixture-plan",
            created_at=T3,
            host_profile=host_profile(assessed=True),
        )
        with self.assertRaisesRegex(ValueError, "ready PADLOC"):
            orchestrator.execute_host_defense_characterization(
                plan.tasks[0],
                host_state_path="x",
                sequence_registry_path="y",
                padloc_data_dir="z",
                output_dir="out",
            )


if __name__ == "__main__":
    unittest.main()

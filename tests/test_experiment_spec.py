import json
from pathlib import Path
import tempfile
import unittest

from phage_lab.agents import RuleAgent
from phage_lab.biology import read_fasta
from phage_lab.cocktail_design import (
    CocktailDesign,
    CocktailMember,
    DesignObjective,
    DesignProducer,
    write_cocktail_design,
)
from phage_lab.experiment_spec import (
    ExperimentSpec,
    ExperimentStep,
    bind_candidates_to_spec,
    experiment_spec_from_cocktail,
    experiment_spec_from_dict,
    load_experiment_spec,
    write_experiment_spec,
)
from phage_lab.interaction_evidence import (
    EvidenceProducer,
    HostReference,
    InteractionEvidence,
)
from phage_lab.workflow import WorkflowError, run_experiment

from support import CANDIDATES, WORKFLOW


ROOT = Path(__file__).resolve().parent.parent
GENOME = ROOT / "examples" / "toy_genome.fasta"
STAMP = "2026-10-16T18:30:00+00:00"


def design(host_sha=None):
    host_sha = host_sha or read_fasta(GENOME).sha256
    host = HostReference(
        genome_sha256=host_sha,
        profile_id="isolate-001:v1",
    )
    evidences = []
    members = []
    for index, candidate in enumerate(CANDIDATES[:2], start=1):
        profile_id = f"{candidate['id']}:v1"
        evidence = InteractionEvidence(
            host=host,
            phage_profile_id=profile_id,
            kind="computational",
            signal="shared_kmer_similarity",
            result={"status": "reported_signal", "value": 20 - index},
            interpretation="Computational screening signal only.",
            observed_at=STAMP,
            producer=EvidenceProducer(
                name="phist",
                version="1.2.1",
                parameters={"k": 25, "threads": 2},
            ),
        )
        evidences.append(evidence)
        members.append(
            CocktailMember(
                phage_profile_id=profile_id,
                evidence_ids=(evidence.evidence_id,),
                selection_context={"phist_rank": index},
            )
        )
    return CocktailDesign(
        cocktail_id="cocktail-001",
        revision=1,
        target_host=host,
        members=tuple(members),
        supporting_evidence=tuple(evidences),
        objectives=(
            DesignObjective(
                name="experimental_screening",
                rationale="Generate experimental evidence for the locked members.",
            ),
        ),
        assumptions=("Computational signal is not efficacy.",),
        unresolved_gaps=("Physical phenotype remains unknown.",),
        rationale="Locked screening proposal.",
        designer=DesignProducer(name="test-designer", version="1"),
        created_at=STAMP,
    )


def spec(host_sha=None):
    return experiment_spec_from_cocktail(
        design(host_sha),
        experiment_id="experiment-001",
        workflow=WORKFLOW,
        created_at=STAMP,
    )


class ExperimentSpecTests(unittest.TestCase):
    def test_cocktail_becomes_locked_experiment_spec(self):
        source = design()
        result = experiment_spec_from_cocktail(
            source,
            experiment_id="experiment-001",
            workflow=WORKFLOW,
            created_at=STAMP,
        )
        payload = result.to_dict()

        self.assertEqual(result.spec_id, "experiment-001:v1")
        self.assertEqual(payload["source_design"]["design_id"], source.design_id)
        self.assertEqual(
            payload["source_design"]["content_sha256"],
            source.content_sha256,
        )
        self.assertEqual(
            list(result.member_phage_profile_ids),
            [member.phage_profile_id for member in source.members],
        )
        self.assertEqual(result.workflow_dict(), WORKFLOW)
        self.assertIn("locked", " ".join(result.execution_constraints).lower())

    def test_content_hash_detects_tampering(self):
        payload = spec().to_dict()
        rebuilt = experiment_spec_from_dict(payload)
        self.assertEqual(rebuilt.content_sha256, payload["content_sha256"])

        tampered = json.loads(json.dumps(payload))
        tampered["member_phage_profile_ids"].reverse()
        with self.assertRaisesRegex(ValueError, "content_sha256"):
            experiment_spec_from_dict(tampered)

    def test_workflow_rejects_later_dependencies(self):
        with self.assertRaisesRegex(ValueError, "missing or later"):
            ExperimentSpec(
                experiment_id="bad",
                revision=1,
                source_design=spec().source_design,
                target_host=spec().target_host,
                member_phage_profile_ids=spec().member_phage_profile_ids,
                workflow=(
                    ExperimentStep("measure", ("infect",)),
                    ExperimentStep("infect"),
                ),
                purpose="Invalid dependency order.",
                scientific_questions=("Can this run?",),
                execution_constraints=("Membership is locked.",),
                created_at=STAMP,
            )

    def test_file_round_trip(self):
        original = spec()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "experiment-spec.json"
            write_experiment_spec(original, path)
            loaded = load_experiment_spec(path)
        self.assertEqual(loaded.to_dict(), original.to_dict())

    def test_candidate_binding_uses_only_locked_members_in_spec_order(self):
        bound = bind_candidates_to_spec(
            spec(),
            [CANDIDATES[2], CANDIDATES[1], CANDIDATES[0]],
        )
        self.assertEqual(
            [candidate["id"] for candidate in bound],
            [CANDIDATES[0]["id"], CANDIDATES[1]["id"]],
        )

    def test_candidate_binding_refuses_missing_or_duplicate_member(self):
        with self.assertRaisesRegex(ValueError, "has no candidate record"):
            bind_candidates_to_spec(spec(), [CANDIDATES[0]])
        with self.assertRaisesRegex(ValueError, "multiple candidate records"):
            bind_candidates_to_spec(
                spec(),
                [CANDIDATES[0], dict(CANDIDATES[0]), CANDIDATES[1]],
            )


class SpecBoundRunTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.output = Path(self.temporary.name)

    async def test_spec_run_never_calls_legacy_plan_or_selects_extra_candidate(self):
        class DeviceOnlyAgent(RuleAgent):
            async def plan(self, context):
                raise AssertionError("legacy plan() must not run for ExperimentSpec")

        locked = spec()
        report, directory = await run_experiment(
            GENOME,
            self.output,
            sample_id="sample-001",
            candidates=[CANDIDATES[2], CANDIDATES[0], CANDIDATES[1]],
            devices=None,
            workflow=locked.workflow_dict(),
            agent=DeviceOnlyAgent(),
            execution_mode="virtual_hardware",
            timeout_seconds=0.2,
            echo=False,
            experiment_spec=locked,
        )

        self.assertEqual(report["status"], "succeeded")
        self.assertTrue(report["scientific_membership_locked"])
        self.assertEqual(
            report["plan"]["candidate_ids"],
            [CANDIDATES[0]["id"], CANDIDATES[1]["id"]],
        )
        self.assertEqual(len(report["candidates"]), 2)
        self.assertEqual(
            report["experiment_spec"]["content_sha256"],
            locked.content_sha256,
        )
        events = [
            json.loads(line)
            for line in (directory / "events.jsonl").read_text().splitlines()
        ]
        names = [event["event"] for event in events]
        self.assertIn("experiment_spec_bound", names)
        self.assertIn("device_assignment_requested", names)
        self.assertNotIn("planning_requested", names)

    async def test_assignment_cannot_smuggle_new_scientific_membership(self):
        class InvalidAgent(RuleAgent):
            async def assign_devices(self, context):
                result = await super().assign_devices(context)
                result["candidate_ids"] = [CANDIDATES[2]["id"]]
                return result

        locked = spec()
        report, _ = await run_experiment(
            GENOME,
            self.output,
            sample_id="sample-001",
            candidates=CANDIDATES,
            devices=None,
            workflow=locked.workflow_dict(),
            agent=InvalidAgent(),
            execution_mode="virtual_hardware",
            timeout_seconds=0.2,
            echo=False,
            experiment_spec=locked,
        )
        self.assertEqual(report["status"], "failed")
        self.assertIn("Device assignment must contain exactly", report["error"])
        self.assertEqual(report["results"], {})

    async def test_host_mismatch_blocks_execution(self):
        locked = spec("f" * 64)
        report, _ = await run_experiment(
            GENOME,
            self.output,
            sample_id="sample-001",
            candidates=CANDIDATES,
            devices=None,
            workflow=locked.workflow_dict(),
            agent=RuleAgent(),
            execution_mode="virtual_hardware",
            timeout_seconds=0.2,
            echo=False,
            experiment_spec=locked,
        )
        self.assertEqual(report["status"], "failed")
        self.assertIn("host genome does not match", report["error"])
        self.assertEqual(report["results"], {})

    async def test_runtime_workflow_cannot_override_spec(self):
        locked = spec()
        with self.assertRaisesRegex(WorkflowError, "does not match"):
            await run_experiment(
                GENOME,
                self.output,
                sample_id="sample-001",
                candidates=CANDIDATES,
                devices=None,
                workflow={"prepare": (), "measure": ("prepare",)},
                agent=RuleAgent(),
                execution_mode="virtual_hardware",
                echo=False,
                experiment_spec=locked,
            )


class ExperimentSpecCliTests(unittest.TestCase):
    def test_cli_creates_spec_from_cocktail(self):
        from phage_lab.__main__ import main

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            design_path = root / "cocktail.json"
            spec_path = root / "spec.json"
            write_cocktail_design(design(), design_path)

            self.assertEqual(
                0,
                main([
                    "experiment-spec",
                    "--cocktail-design", str(design_path),
                    "--experiment-id", "experiment-cli",
                    "--out", str(spec_path),
                ]),
            )
            loaded = load_experiment_spec(spec_path)
            self.assertEqual(loaded.spec_id, "experiment-cli:v1")
            self.assertEqual(loaded.workflow_dict(), WORKFLOW)

    def test_cli_spec_run_locks_members(self):
        from phage_lab.__main__ import main

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec_path = root / "spec.json"
            candidates_path = root / "candidates.json"
            runs = root / "runs"
            write_experiment_spec(spec(), spec_path)
            candidates_path.write_text(
                json.dumps([CANDIDATES[2], CANDIDATES[1], CANDIDATES[0]]),
                encoding="utf-8",
            )

            self.assertEqual(
                0,
                main([
                    "run",
                    "--experiment-spec", str(spec_path),
                    "--candidates", str(candidates_path),
                    "--genome", str(GENOME),
                    "--sample-id", "sample-cli",
                    "--execution-mode", "virtual_hardware",
                    "--output-dir", str(runs),
                    "--quiet",
                ]),
            )
            report = json.loads(
                next(runs.glob("*/report.json")).read_text(encoding="utf-8")
            )
            self.assertTrue(report["scientific_membership_locked"])
            self.assertEqual(
                report["plan"]["candidate_ids"],
                [CANDIDATES[0]["id"], CANDIDATES[1]["id"]],
            )


if __name__ == "__main__":
    unittest.main()

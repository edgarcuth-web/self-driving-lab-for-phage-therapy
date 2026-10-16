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
)
from phage_lab.experiment_spec import (
    experiment_spec_from_cocktail,
    write_experiment_spec,
)
from phage_lab.interaction_evidence import (
    EvidenceProducer,
    HostReference,
    InteractionEvidence,
)
from phage_lab.material_batch import (
    bind_material_batches_to_spec,
    material_batch_from_dict,
    new_material_batch,
)
from phage_lab.measurement import (
    Measurement,
    measurement_from_dict,
    measurement_from_run_report,
)
from phage_lab.phenotype import (
    phenotype_comparison_from_dict,
    phenotype_comparison_from_phenotypes,
    phenotype_from_dict,
    phenotype_from_measurements,
    write_phenotype,
)
from phage_lab.workflow import WorkflowError, run_experiment

from support import CANDIDATES, RealDeviceDouble, WORKFLOW


ROOT = Path(__file__).resolve().parent.parent
GENOME = ROOT / "examples" / "toy_genome.fasta"
STAMP = "2026-10-16T19:30:00+00:00"


def experiment_spec():
    host = HostReference(
        genome_sha256=read_fasta(GENOME).sha256,
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
            result={"status": "reported_signal", "value": 10 - index},
            interpretation="Computational screening signal only.",
            observed_at=STAMP,
            producer=EvidenceProducer(
                name="phist",
                version="1.2.1",
                parameters={"k": 25},
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
    design = CocktailDesign(
        cocktail_id="cocktail-001",
        revision=1,
        target_host=host,
        members=tuple(members),
        supporting_evidence=tuple(evidences),
        objectives=(
            DesignObjective(
                name="experimental_screening",
                rationale="Generate physical evidence for the locked members.",
            ),
        ),
        assumptions=("Computational signal is not efficacy.",),
        unresolved_gaps=("Physical phenotype remains unknown.",),
        rationale="Test design fixture.",
        designer=DesignProducer(name="test", version="1"),
        created_at=STAMP,
    )
    return experiment_spec_from_cocktail(
        design,
        experiment_id="experiment-001",
        workflow=WORKFLOW,
        created_at=STAMP,
    )


def arm(spec, arm_id):
    return next(item for item in spec.arms if item.arm_id == arm_id)


def material_batches(*, quality_status="released", availability="available"):
    spec = experiment_spec()
    evidence = ("qc-record-001",) if quality_status in {"released", "rejected"} else ()
    batches = [
        new_material_batch(
            "host-batch-001",
            material_type="host",
            profile_id=spec.target_host.profile_id,
            source_kind="local_collection",
            source_reference="LIMS:host-001",
            quality_status=quality_status,
            availability_status=availability,
            quality_evidence=evidence,
            created_at=STAMP,
        )
    ]
    for index, profile_id in enumerate(spec.member_phage_profile_ids, start=1):
        batches.append(
            new_material_batch(
                f"phage-batch-{index:03d}",
                material_type="phage",
                profile_id=profile_id,
                source_kind="acquired",
                source_reference=f"LIMS:phage-{index:03d}",
                quality_status=quality_status,
                availability_status=availability,
                quality_evidence=evidence,
                created_at=STAMP,
            )
        )
    return batches


def arm_batch_ids(spec, batches, arm_id):
    target = arm(spec, arm_id)
    host_batch = next(
        batch for batch in batches
        if batch.material_type == "host"
        and batch.profile_id == target.target_host.profile_id
    )
    ids = [host_batch.record_id]
    for profile_id in target.phage_profile_ids:
        ids.append(next(
            batch.record_id for batch in batches
            if batch.material_type == "phage"
            and batch.profile_id == profile_id
        ))
    return tuple(ids)


def virtual_report():
    spec = experiment_spec()
    return {
        "schema_version": 4,
        "run_id": "run-virtual-001",
        "started_at": STAMP,
        "finished_at": STAMP,
        "status": "succeeded",
        "execution_mode": "virtual_hardware",
        "physical_execution": False,
        "simulated": True,
        "experiment_spec": spec.to_dict(),
        "material_batch_ids": [],
        "plan": {
            "candidate_ids": [item["id"] for item in CANDIDATES[:2]],
            "device_assignments": {
                "prepare": "virtual-prepare-1",
                "infect": "virtual-infect-1",
                "measure": "virtual-measure-1",
            },
            "reason": "test",
        },
        "results": {
            "measure": {
                "simulated": True,
                "physical_execution": False,
                "evidence": "none",
                "arms": {
                    item.arm_id: {
                        "simulated": True,
                        "physical_execution": False,
                        "evidence": "none",
                        "arm_id": item.arm_id,
                        "readings": [0.1, 0.2],
                        "unit": "virtual",
                    }
                    for item in spec.arms
                },
            }
        },
    }


def physical_report():
    spec = experiment_spec()
    batches = material_batches()
    return spec, batches, {
        "schema_version": 4,
        "run_id": "run-physical-001",
        "started_at": STAMP,
        "finished_at": STAMP,
        "status": "succeeded",
        "execution_mode": "real_hardware",
        "physical_execution": True,
        "simulated": False,
        "experiment_spec": spec.to_dict(),
        "material_batch_ids": [batch.record_id for batch in batches],
        "material_batches": bind_material_batches_to_spec(spec, batches).to_dict(),
        "plan": {
            "candidate_ids": [item["id"] for item in CANDIDATES[:2]],
            "device_assignments": {"measure": "reader-001"},
            "reason": "test",
        },
        "results": {
            "measure": {
                "arms": {
                    "host-control": {
                        "signal": [1.0, 1.1],
                        "unit": "instrument_units",
                    },
                    "cocktail-treatment": {
                        "signal": [0.2, 0.3],
                        "unit": "instrument_units",
                    },
                }
            }
        },
    }


def physical_measurement(
    *,
    arm_id="cocktail-treatment",
    qc_status="valid",
    spec=None,
    batches=None,
    measurement_id=None,
):
    spec = spec or experiment_spec()
    batches = batches or material_batches()
    target = arm(spec, arm_id)
    return Measurement(
        measurement_id=measurement_id or f"measurement-{arm_id}",
        revision=1,
        run_id="run-physical-001",
        experiment_spec_id=spec.spec_id,
        experiment_spec_sha256=spec.content_sha256,
        experiment_arm_id=target.arm_id,
        target_host_profile_id=target.target_host.profile_id,
        phage_profile_ids=target.phage_profile_ids,
        source_step="measure",
        device_id="reader-001",
        material_batch_ids=arm_batch_ids(spec, batches, arm_id),
        origin="physical_run",
        physical_execution=True,
        qc_status=qc_status,
        qc_evidence=(f"qc:{qc_status}",) if qc_status in {"valid", "invalid"} else (),
        measurement_type="device_result",
        data={"signal": [0.1, 0.2, 0.3], "unit": "instrument_units"},
        recorded_at=STAMP,
        created_at=STAMP,
    )


def phenotype_for_arm(spec, arm_id, *, phenotype_id, phenotype_type="growth_response"):
    measurement = physical_measurement(
        arm_id=arm_id,
        spec=spec,
        measurement_id=f"measurement-{arm_id}",
    )
    return phenotype_from_measurements(
        spec,
        [measurement],
        arm_id=arm_id,
        phenotype_id=phenotype_id,
        phenotype_type=phenotype_type,
        outcome="graded",
        value=0.5,
        unit="assessor_units",
        interpretation=f"Explicit interpretation for {arm_id}.",
        assessor_name="manual-review",
        assessor_version="1",
        assessed_at=STAMP,
    )


class MaterialBatchTests(unittest.TestCase):
    def test_released_batch_requires_quality_evidence(self):
        with self.assertRaisesRegex(ValueError, "quality_evidence"):
            new_material_batch(
                "batch-001",
                material_type="phage",
                profile_id="PH-001:v1",
                source_kind="acquired",
                source_reference="LIMS:PH-001",
                quality_status="released",
                created_at=STAMP,
            )

    def test_pending_batch_exists_but_is_not_test_ready(self):
        batch = new_material_batch(
            "batch-001",
            material_type="phage",
            profile_id="PH-001:v1",
            source_kind="acquired",
            source_reference="LIMS:PH-001",
            quality_status="pending",
            created_at=STAMP,
        )
        self.assertFalse(batch.test_ready)

    def test_spec_binding_requires_exact_test_ready_materials(self):
        spec = experiment_spec()
        binding = bind_material_batches_to_spec(spec, material_batches())
        self.assertEqual(binding.host_batch.profile_id, spec.target_host.profile_id)
        self.assertEqual(
            [batch.profile_id for batch in binding.phage_batches],
            list(spec.member_phage_profile_ids),
        )
        with self.assertRaisesRegex(ValueError, "No test-ready"):
            bind_material_batches_to_spec(
                spec,
                material_batches(quality_status="pending"),
            )

    def test_content_hash_detects_tampering(self):
        payload = material_batches()[0].to_dict()
        rebuilt = material_batch_from_dict(payload)
        self.assertEqual(rebuilt.content_sha256, payload["content_sha256"])
        tampered = json.loads(json.dumps(payload))
        tampered["availability_status"] = "consumed"
        with self.assertRaisesRegex(ValueError, "content_sha256"):
            material_batch_from_dict(tampered)


class MeasurementTests(unittest.TestCase):
    def test_spec_bound_measurement_requires_arm_id(self):
        with self.assertRaisesRegex(ValueError, "requires arm_id"):
            measurement_from_run_report(
                virtual_report(),
                measurement_id="measurement-virtual",
                qc_status="valid",
                qc_evidence=("qc:virtual",),
                created_at=STAMP,
            )

    def test_virtual_arm_result_is_ingested_as_non_evidence(self):
        measurement = measurement_from_run_report(
            virtual_report(),
            measurement_id="measurement-control",
            arm_id="host-control",
            qc_status="valid",
            qc_evidence=("qc:virtual-control",),
            created_at=STAMP,
        )
        self.assertEqual(measurement.experiment_arm_id, "host-control")
        self.assertEqual(measurement.phage_profile_ids, ())
        self.assertEqual(measurement.origin, "virtual_run")
        self.assertFalse(measurement.physical_execution)
        self.assertEqual(measurement.evidence_class, "none")
        self.assertEqual(measurement.data["arm_id"], "host-control")

    def test_physical_arm_result_keeps_arm_specific_material_lineage(self):
        spec, batches, report = physical_report()
        control = measurement_from_run_report(
            report,
            measurement_id="measurement-control",
            arm_id="host-control",
            qc_status="valid",
            qc_evidence=("qc:control",),
            created_at=STAMP,
        )
        treatment = measurement_from_run_report(
            report,
            measurement_id="measurement-treatment",
            arm_id="cocktail-treatment",
            qc_status="valid",
            qc_evidence=("qc:treatment",),
            created_at=STAMP,
        )
        self.assertEqual(control.material_batch_ids, arm_batch_ids(spec, batches, "host-control"))
        self.assertEqual(
            treatment.material_batch_ids,
            arm_batch_ids(spec, batches, "cocktail-treatment"),
        )
        self.assertEqual(len(control.material_batch_ids), 1)
        self.assertEqual(len(treatment.material_batch_ids), 3)

    def test_spec_bound_result_without_arm_mapping_is_refused(self):
        report = virtual_report()
        report["results"]["measure"] = {"readings": [0.1]}
        with self.assertRaisesRegex(ValueError, "arm-scoped 'arms' mapping"):
            measurement_from_run_report(
                report,
                measurement_id="bad",
                arm_id="host-control",
                created_at=STAMP,
            )

    def test_physical_arm_cannot_wrap_simulated_result(self):
        _, _, report = physical_report()
        report["results"]["measure"]["arms"]["host-control"]["simulated"] = True
        with self.assertRaisesRegex(ValueError, "contradicts"):
            measurement_from_run_report(
                report,
                measurement_id="bad",
                arm_id="host-control",
                created_at=STAMP,
            )

    def test_measurement_hash_detects_tampering(self):
        payload = physical_measurement().to_dict()
        rebuilt = measurement_from_dict(payload)
        self.assertEqual(rebuilt.content_sha256, payload["content_sha256"])
        tampered = json.loads(json.dumps(payload))
        tampered["experiment_arm_id"] = "host-control"
        with self.assertRaisesRegex(ValueError, "content_sha256"):
            measurement_from_dict(tampered)


class PhenotypeTests(unittest.TestCase):
    def test_treatment_measurement_becomes_arm_scoped_phenotype(self):
        spec = experiment_spec()
        measurement = physical_measurement(spec=spec)
        phenotype = phenotype_from_measurements(
            spec,
            [measurement],
            arm_id="cocktail-treatment",
            phenotype_id="phenotype-treatment",
            phenotype_type="growth_response",
            outcome="negative",
            interpretation="Explicit treatment-arm interpretation.",
            assessor_name="manual-review",
            assessor_version="1",
            assessed_at=STAMP,
        )
        self.assertEqual(phenotype.experiment_arm_id, "cocktail-treatment")
        self.assertEqual(
            phenotype.phage_profile_ids,
            arm(spec, "cocktail-treatment").phage_profile_ids,
        )
        rebuilt = phenotype_from_dict(phenotype.to_dict())
        self.assertEqual(rebuilt.content_sha256, phenotype.content_sha256)

    def test_control_phenotype_allows_zero_phage(self):
        spec = experiment_spec()
        measurement = physical_measurement(arm_id="host-control", spec=spec)
        phenotype = phenotype_from_measurements(
            spec,
            [measurement],
            arm_id="host-control",
            phenotype_id="phenotype-control",
            phenotype_type="growth_response",
            outcome="graded",
            value=1.0,
            interpretation="Explicit host-control interpretation.",
            assessor_name="manual-review",
            assessor_version="1",
            assessed_at=STAMP,
        )
        self.assertEqual(phenotype.phage_profile_ids, ())
        self.assertEqual(len(phenotype.material_batch_ids), 1)

    def test_measurements_from_different_arms_cannot_be_collapsed(self):
        spec = experiment_spec()
        with self.assertRaisesRegex(ValueError, "ExperimentArm"):
            phenotype_from_measurements(
                spec,
                [
                    physical_measurement(arm_id="host-control", spec=spec),
                    physical_measurement(arm_id="cocktail-treatment", spec=spec),
                ],
                arm_id="host-control",
                phenotype_id="bad",
                phenotype_type="growth_response",
                outcome="negative",
                interpretation="Must remain arm-scoped.",
                assessor_name="manual-review",
                assessor_version="1",
                assessed_at=STAMP,
            )

    def test_virtual_measurement_cannot_support_phenotype(self):
        spec = experiment_spec()
        virtual = measurement_from_run_report(
            virtual_report(),
            measurement_id="virtual",
            arm_id="host-control",
            qc_status="valid",
            qc_evidence=("qc:virtual",),
            created_at=STAMP,
        )
        with self.assertRaisesRegex(ValueError, "non-physical"):
            phenotype_from_measurements(
                spec,
                [virtual],
                arm_id="host-control",
                phenotype_id="phenotype-001",
                phenotype_type="growth_response",
                outcome="negative",
                interpretation="Must not be admitted.",
                assessor_name="manual-review",
                assessor_version="1",
                assessed_at=STAMP,
            )

    def test_invalid_qc_cannot_become_negative_phenotype(self):
        spec = experiment_spec()
        with self.assertRaisesRegex(ValueError, "qc_status='valid'"):
            phenotype_from_measurements(
                spec,
                [physical_measurement(qc_status="invalid", spec=spec)],
                arm_id="cocktail-treatment",
                phenotype_id="phenotype-001",
                phenotype_type="growth_response",
                outcome="negative",
                interpretation="Invalid readout must not become biological negative.",
                assessor_name="manual-review",
                assessor_version="1",
                assessed_at=STAMP,
            )

    def test_graded_phenotype_requires_value(self):
        spec = experiment_spec()
        with self.assertRaisesRegex(ValueError, "graded phenotype requires"):
            phenotype_from_measurements(
                spec,
                [physical_measurement(spec=spec)],
                arm_id="cocktail-treatment",
                phenotype_id="phenotype-001",
                phenotype_type="growth_response",
                outcome="graded",
                interpretation="Explicit graded interpretation.",
                assessor_name="manual-review",
                assessor_version="1",
                assessed_at=STAMP,
            )

    def test_explicit_arm_comparison_preserves_both_phenotype_hashes(self):
        spec = experiment_spec()
        baseline = phenotype_for_arm(spec, "host-control", phenotype_id="baseline")
        comparator = phenotype_for_arm(spec, "cocktail-treatment", phenotype_id="treatment")
        comparison = phenotype_comparison_from_phenotypes(
            spec,
            baseline,
            comparator,
            comparison_id="comparison-001",
            comparison_type="treatment_vs_host_control",
            outcome="reduced_signal",
            value=-0.5,
            unit="assessor_units",
            interpretation="Assessor-stated comparison only.",
            assessor_name="manual-review",
            assessor_version="1",
            assessed_at=STAMP,
        )
        self.assertEqual(comparison.baseline_arm_id, "host-control")
        self.assertEqual(comparison.comparator_arm_id, "cocktail-treatment")
        self.assertEqual(
            comparison.baseline_phenotype_sha256,
            baseline.content_sha256,
        )
        rebuilt = phenotype_comparison_from_dict(comparison.to_dict())
        self.assertEqual(rebuilt.content_sha256, comparison.content_sha256)

    def test_comparison_refuses_same_arm_or_mismatched_type(self):
        spec = experiment_spec()
        baseline = phenotype_for_arm(spec, "host-control", phenotype_id="baseline")
        duplicate = phenotype_for_arm(spec, "host-control", phenotype_id="duplicate")
        with self.assertRaisesRegex(ValueError, "distinct arms"):
            phenotype_comparison_from_phenotypes(
                spec,
                baseline,
                duplicate,
                comparison_id="bad",
                comparison_type="same-arm",
                outcome="no_difference",
                interpretation="Invalid comparison.",
                assessor_name="manual-review",
                assessor_version="1",
                assessed_at=STAMP,
            )
        other_type = phenotype_for_arm(
            spec,
            "cocktail-treatment",
            phenotype_id="other",
            phenotype_type="adsorption",
        )
        with self.assertRaisesRegex(ValueError, "matching phenotype_type"):
            phenotype_comparison_from_phenotypes(
                spec,
                baseline,
                other_type,
                comparison_id="bad-type",
                comparison_type="mixed",
                outcome="unknown",
                interpretation="Invalid comparison.",
                assessor_name="manual-review",
                assessor_version="1",
                assessed_at=STAMP,
            )


class MaterialRunIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_spec_run_requires_material_batches(self):
        spec = experiment_spec()
        devices = {
            operation: RealDeviceDouble(operation, operation)
            for operation in WORKFLOW
        }
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(WorkflowError, "requires test-ready MaterialBatch"):
                await run_experiment(
                    GENOME,
                    Path(temporary) / "runs",
                    sample_id="sample-001",
                    candidates=CANDIDATES,
                    devices=devices,
                    workflow=spec.workflow_dict(),
                    agent=RuleAgent(),
                    execution_mode="real_hardware",
                    experiment_spec=spec,
                    echo=False,
                )

    async def test_real_run_flows_into_two_arm_phenotypes_and_comparison(self):
        spec = experiment_spec()
        batches = material_batches()
        devices = {
            operation: RealDeviceDouble(operation, operation)
            for operation in WORKFLOW
        }
        with tempfile.TemporaryDirectory() as temporary:
            report, directory = await run_experiment(
                GENOME,
                Path(temporary) / "runs",
                sample_id="sample-physical",
                candidates=CANDIDATES,
                devices=devices,
                workflow=spec.workflow_dict(),
                agent=RuleAgent(),
                execution_mode="real_hardware",
                experiment_spec=spec,
                material_batches=batches,
                echo=False,
            )
            self.assertEqual(report["status"], "succeeded")
            self.assertIn("arms", report["results"]["measure"])
            persisted = json.loads(
                (directory / "report.json").read_text(encoding="utf-8")
            )

            control_measurement = measurement_from_run_report(
                persisted,
                measurement_id="measurement-control",
                arm_id="host-control",
                qc_status="valid",
                qc_evidence=("qc:control",),
                created_at=STAMP,
            )
            treatment_measurement = measurement_from_run_report(
                persisted,
                measurement_id="measurement-treatment",
                arm_id="cocktail-treatment",
                qc_status="valid",
                qc_evidence=("qc:treatment",),
                created_at=STAMP,
            )
            control = phenotype_from_measurements(
                spec,
                [control_measurement],
                arm_id="host-control",
                phenotype_id="phenotype-control",
                phenotype_type="growth_response",
                outcome="graded",
                value=1.0,
                interpretation="Control phenotype.",
                assessor_name="test-assessor",
                assessor_version="1",
                assessed_at=STAMP,
            )
            treatment = phenotype_from_measurements(
                spec,
                [treatment_measurement],
                arm_id="cocktail-treatment",
                phenotype_id="phenotype-treatment",
                phenotype_type="growth_response",
                outcome="graded",
                value=0.5,
                interpretation="Treatment phenotype.",
                assessor_name="test-assessor",
                assessor_version="1",
                assessed_at=STAMP,
            )
            comparison = phenotype_comparison_from_phenotypes(
                spec,
                control,
                treatment,
                comparison_id="comparison-from-run",
                comparison_type="treatment_vs_host_control",
                outcome="different",
                value=-0.5,
                interpretation="Explicit end-to-end comparison.",
                assessor_name="test-assessor",
                assessor_version="1",
                assessed_at=STAMP,
            )
            self.assertEqual(comparison.baseline_arm_id, "host-control")
            self.assertEqual(comparison.comparator_arm_id, "cocktail-treatment")

    async def test_virtual_spec_run_emits_arm_scoped_non_evidence(self):
        spec = experiment_spec()
        batches = material_batches()
        with tempfile.TemporaryDirectory() as temporary:
            report, directory = await run_experiment(
                GENOME,
                Path(temporary) / "runs",
                sample_id="sample-001",
                candidates=CANDIDATES,
                devices=None,
                workflow=spec.workflow_dict(),
                agent=RuleAgent(),
                execution_mode="virtual_hardware",
                experiment_spec=spec,
                material_batches=batches,
                echo=False,
            )
            rendered = (directory / "report.md").read_text(encoding="utf-8")
        self.assertEqual(report["status"], "succeeded")
        self.assertEqual(
            set(report["results"]["measure"]["arms"]),
            {"host-control", "cocktail-treatment"},
        )
        self.assertEqual(
            report["evaluation"]["quality"],
            "virtual_arm_readouts_complete",
        )
        self.assertIn("MaterialBatch", rendered)
        self.assertTrue(
            any("did not consume physical material" in item for item in report["limitations"])
        )


class IngestionCliTests(unittest.TestCase):
    def test_material_batch_cli_registers_hashed_record(self):
        from phage_lab.__main__ import main

        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "batch.json"
            self.assertEqual(
                0,
                main([
                    "material-batch",
                    "--batch-id", "phage-batch-001",
                    "--material-type", "phage",
                    "--profile-id", "PH-001:v1",
                    "--material-source-kind", "acquired",
                    "--material-source-reference", "LIMS:PH-001",
                    "--quality-status", "released",
                    "--quality-evidence", "qc-001",
                    "--out", str(out),
                ]),
            )

    def test_virtual_measurement_cli_is_arm_scoped_and_cannot_be_phenotype(self):
        from phage_lab.__main__ import main

        spec = experiment_spec()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report_path = root / "report.json"
            measurement_path = root / "measurement.json"
            measurements_path = root / "measurements.json"
            spec_path = root / "spec.json"
            phenotype_path = root / "phenotype.json"

            report_path.write_text(json.dumps(virtual_report()), encoding="utf-8")
            write_experiment_spec(spec, spec_path)

            self.assertEqual(
                0,
                main([
                    "measurement",
                    "--run-report", str(report_path),
                    "--measurement-id", "measurement-virtual",
                    "--arm-id", "host-control",
                    "--qc-status", "valid",
                    "--qc-evidence", "qc:virtual-control",
                    "--out", str(measurement_path),
                ]),
            )
            payload = json.loads(measurement_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["experiment_arm_id"], "host-control")
            measurements_path.write_text(
                json.dumps([payload]),
                encoding="utf-8",
            )
            self.assertEqual(
                2,
                main([
                    "phenotype",
                    "--experiment-spec", str(spec_path),
                    "--measurements", str(measurements_path),
                    "--arm-id", "host-control",
                    "--phenotype-id", "phenotype-001",
                    "--phenotype-type", "growth_response",
                    "--phenotype-outcome", "negative",
                    "--interpretation", "Must remain non-evidence.",
                    "--assessor", "manual-review",
                    "--out", str(phenotype_path),
                ]),
            )
            self.assertFalse(phenotype_path.exists())

    def test_cli_creates_explicit_phenotype_comparison(self):
        from phage_lab.__main__ import main

        spec = experiment_spec()
        baseline = phenotype_for_arm(spec, "host-control", phenotype_id="baseline")
        comparator = phenotype_for_arm(
            spec,
            "cocktail-treatment",
            phenotype_id="treatment",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec_path = root / "spec.json"
            baseline_path = root / "baseline.json"
            comparator_path = root / "treatment.json"
            comparison_path = root / "comparison.json"
            write_experiment_spec(spec, spec_path)
            write_phenotype(baseline, baseline_path)
            write_phenotype(comparator, comparator_path)

            self.assertEqual(
                0,
                main([
                    "phenotype-comparison",
                    "--experiment-spec", str(spec_path),
                    "--baseline-phenotype", str(baseline_path),
                    "--comparator-phenotype", str(comparator_path),
                    "--comparison-id", "comparison-cli",
                    "--comparison-type", "treatment_vs_host_control",
                    "--comparison-outcome", "reduced_signal",
                    "--comparison-value", "-0.5",
                    "--interpretation", "Explicit CLI comparison.",
                    "--assessor", "manual-review",
                    "--out", str(comparison_path),
                ]),
            )
            payload = json.loads(comparison_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["baseline_arm_id"], "host-control")
            self.assertEqual(payload["comparator_arm_id"], "cocktail-treatment")


if __name__ == "__main__":
    unittest.main()

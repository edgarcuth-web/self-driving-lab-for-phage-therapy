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
    write_material_batch,
)
from phage_lab.measurement import (
    Measurement,
    measurement_from_dict,
    measurement_from_run_report,
    write_measurement,
)
from phage_lab.phenotype import (
    phenotype_from_dict,
    phenotype_from_measurements,
)
from phage_lab.workflow import WorkflowError, run_experiment

from support import CANDIDATES, RealDeviceDouble, WORKFLOW


ROOT = Path(__file__).resolve().parent.parent
GENOME = ROOT / "examples" / "toy_genome.fasta"
STAMP = "2026-10-16T19:00:00+00:00"


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


def physical_measurement(*, qc_status="valid", spec=None, batch_ids=None):
    spec = spec or experiment_spec()
    if batch_ids is None:
        batch_ids = tuple(batch.record_id for batch in material_batches())
    return Measurement(
        measurement_id="measurement-001",
        revision=1,
        run_id="run-physical-001",
        experiment_spec_id=spec.spec_id,
        experiment_spec_sha256=spec.content_sha256,
        source_step="measure",
        device_id="reader-001",
        material_batch_ids=tuple(batch_ids),
        origin="physical_run",
        physical_execution=True,
        qc_status=qc_status,
        qc_evidence=(f"qc:{qc_status}",) if qc_status in {"valid", "invalid"} else (),
        measurement_type="device_result",
        data={"signal": [0.1, 0.2, 0.3], "unit": "instrument_units"},
        recorded_at=STAMP,
        created_at=STAMP,
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
        self.assertEqual(
            binding.host_batch.profile_id,
            spec.target_host.profile_id,
        )
        self.assertEqual(
            [batch.profile_id for batch in binding.phage_batches],
            list(spec.member_phage_profile_ids),
        )
        self.assertEqual(len(binding.batch_ids), 3)

        with self.assertRaisesRegex(ValueError, "No test-ready"):
            bind_material_batches_to_spec(
                spec,
                material_batches(quality_status="pending"),
            )

    def test_ambiguous_batches_are_refused(self):
        spec = experiment_spec()
        batches = material_batches()
        duplicate = new_material_batch(
            "host-batch-002",
            material_type="host",
            profile_id=spec.target_host.profile_id,
            source_kind="local_collection",
            source_reference="LIMS:host-002",
            quality_status="released",
            quality_evidence=("qc-record-002",),
            created_at=STAMP,
        )
        with self.assertRaisesRegex(ValueError, "Multiple test-ready"):
            bind_material_batches_to_spec(spec, [*batches, duplicate])

    def test_content_hash_detects_tampering(self):
        payload = material_batches()[0].to_dict()
        rebuilt = material_batch_from_dict(payload)
        self.assertEqual(rebuilt.content_sha256, payload["content_sha256"])

        tampered = json.loads(json.dumps(payload))
        tampered["availability_status"] = "consumed"
        with self.assertRaisesRegex(ValueError, "content_sha256"):
            material_batch_from_dict(tampered)


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
                    "readings": [0.1, 0.2],
                    "unit": "virtual",
                }
            },
        }


class MeasurementTests(unittest.TestCase):
    def test_virtual_result_is_ingested_as_non_evidence(self):
        measurement = measurement_from_run_report(
            virtual_report(),
            measurement_id="measurement-virtual",
            qc_status="valid",
            qc_evidence=("qc:virtual-control",),
            created_at=STAMP,
        )
        self.assertEqual(measurement.origin, "virtual_run")
        self.assertFalse(measurement.physical_execution)
        self.assertEqual(measurement.evidence_class, "none")

    def test_admitted_qc_requires_evidence_reference(self):
        with self.assertRaisesRegex(ValueError, "requires qc_evidence"):
            measurement_from_run_report(
                virtual_report(),
                measurement_id="measurement-no-qc-lineage",
                qc_status="valid",
                created_at=STAMP,
            )

    def test_physical_result_keeps_material_and_spec_lineage(self):
        spec = experiment_spec()
        batches = material_batches()
        report = {
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
            "plan": {
                "candidate_ids": [item["id"] for item in CANDIDATES[:2]],
                "device_assignments": {"measure": "reader-001"},
                "reason": "test",
            },
            "results": {
                "measure": {
                    "signal": [1.0, 2.0],
                    "unit": "instrument_units",
                }
            },
        }
        measurement = measurement_from_run_report(
            report,
            measurement_id="measurement-physical",
            qc_status="valid",
            qc_evidence=("qc:physical",),
            created_at=STAMP,
        )
        self.assertTrue(measurement.physical_execution)
        self.assertEqual(measurement.evidence_class, "physical_measurement")
        self.assertEqual(
            measurement.material_batch_ids,
            tuple(batch.record_id for batch in batches),
        )
        self.assertEqual(measurement.experiment_spec_id, spec.spec_id)

    def test_physical_report_cannot_wrap_a_simulated_result(self):
        report = virtual_report()
        report["execution_mode"] = "real_hardware"
        report["physical_execution"] = True
        with self.assertRaisesRegex(ValueError, "contradicts"):
            measurement_from_run_report(
                report,
                measurement_id="bad",
                created_at=STAMP,
            )

    def test_measurement_hash_detects_tampering(self):
        payload = physical_measurement().to_dict()
        rebuilt = measurement_from_dict(payload)
        self.assertEqual(rebuilt.content_sha256, payload["content_sha256"])
        tampered = json.loads(json.dumps(payload))
        tampered["qc_status"] = "invalid"
        with self.assertRaisesRegex(ValueError, "content_sha256"):
            measurement_from_dict(tampered)


class PhenotypeTests(unittest.TestCase):
    def test_valid_physical_measurement_can_support_explicit_phenotype(self):
        spec = experiment_spec()
        measurement = physical_measurement(spec=spec)
        phenotype = phenotype_from_measurements(
            spec,
            [measurement],
            phenotype_id="phenotype-001",
            phenotype_type="growth_response",
            outcome="negative",
            interpretation="Manual review classified the admitted physical readout as a negative response.",
            assessor_name="manual-review",
            assessor_version="1",
            assessed_at=STAMP,
        )
        self.assertEqual(phenotype.outcome, "negative")
        self.assertEqual(
            phenotype.measurement_ids,
            (measurement.record_id,),
        )
        self.assertEqual(
            phenotype.material_batch_ids,
            measurement.material_batch_ids,
        )

        rebuilt = phenotype_from_dict(phenotype.to_dict())
        self.assertEqual(rebuilt.content_sha256, phenotype.content_sha256)

    def test_virtual_measurement_cannot_support_phenotype(self):
        spec = experiment_spec()
        virtual = Measurement(
            measurement_id="virtual",
            revision=1,
            run_id="run-virtual",
            experiment_spec_id=spec.spec_id,
            experiment_spec_sha256=spec.content_sha256,
            source_step="measure",
            device_id="virtual-measure-1",
            material_batch_ids=(),
            origin="virtual_run",
            physical_execution=False,
            qc_status="valid",
            qc_evidence=("qc:virtual-control",),
            measurement_type="device_result",
            data={"readings": [0.1]},
            recorded_at=STAMP,
            created_at=STAMP,
        )
        with self.assertRaisesRegex(ValueError, "non-physical"):
            phenotype_from_measurements(
                spec,
                [virtual],
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
                phenotype_id="phenotype-001",
                phenotype_type="growth_response",
                outcome="negative",
                interpretation="Invalid readout must not become biological negative.",
                assessor_name="manual-review",
                assessor_version="1",
                assessed_at=STAMP,
            )

    def test_measurement_from_other_spec_is_refused(self):
        spec = experiment_spec()
        other = physical_measurement(spec=spec)
        object.__setattr__(other, "experiment_spec_id", "other:v1")
        with self.assertRaisesRegex(ValueError, "does not match"):
            phenotype_from_measurements(
                spec,
                [other],
                phenotype_id="phenotype-001",
                phenotype_type="growth_response",
                outcome="positive",
                interpretation="Wrong lineage.",
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
                phenotype_id="phenotype-001",
                phenotype_type="growth_response",
                outcome="graded",
                interpretation="Explicit graded interpretation.",
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

    async def test_real_spec_run_flows_into_physical_measurement_and_phenotype(self):
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
            self.assertTrue(report["physical_execution"])
            self.assertEqual(
                report["material_batch_ids"],
                [batch.record_id for batch in batches],
            )

            persisted = json.loads(
                (directory / "report.json").read_text(encoding="utf-8")
            )
            measurement = measurement_from_run_report(
                persisted,
                measurement_id="measurement-from-run",
                qc_status="valid",
                qc_evidence=("qc:run",),
                created_at=STAMP,
            )
            self.assertEqual(
                measurement.evidence_class,
                "physical_measurement",
            )
            phenotype = phenotype_from_measurements(
                spec,
                [measurement],
                phenotype_id="phenotype-from-run",
                phenotype_type="manual_result_review",
                outcome="positive",
                interpretation=(
                    "Test assessor admitted the physical test-double result "
                    "for lineage validation only."
                ),
                assessor_name="test-assessor",
                assessor_version="1",
                assessed_at=STAMP,
            )
            self.assertEqual(
                phenotype.material_batch_ids,
                tuple(batch.record_id for batch in batches),
            )

    async def test_virtual_spec_run_can_bind_material_lineage_without_consumption_claim(self):
        spec = experiment_spec()
        batches = material_batches()
        with tempfile.TemporaryDirectory() as temporary:
            report, _ = await run_experiment(
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
        self.assertEqual(report["status"], "succeeded")
        self.assertEqual(
            report["material_batch_ids"],
            [batch.record_id for batch in batches],
        )
        self.assertTrue(
            any("did not consume physical material" in item for item in report["limitations"])
        )
        self.assertEqual(report["schema_version"], 4)


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
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(
                material_batch_from_dict(payload).record_id,
                "phage-batch-001:v1",
            )

    def test_virtual_measurement_cli_cannot_be_promoted_by_phenotype_cli(self):
        from phage_lab.__main__ import main

        spec = experiment_spec()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report_path = root / "report.json"
            measurement_path = root / "measurement.json"
            measurements_path = root / "measurements.json"
            spec_path = root / "spec.json"
            phenotype_path = root / "phenotype.json"

            report = virtual_report()
            report_path.write_text(json.dumps(report), encoding="utf-8")
            write_experiment_spec(spec, spec_path)

            self.assertEqual(
                0,
                main([
                    "measurement",
                    "--run-report", str(report_path),
                    "--measurement-id", "measurement-virtual",
                    "--qc-status", "valid",
                    "--qc-evidence", "qc:virtual-control",
                    "--out", str(measurement_path),
                ]),
            )
            measurements_path.write_text(
                json.dumps([
                    json.loads(measurement_path.read_text(encoding="utf-8"))
                ]),
                encoding="utf-8",
            )
            self.assertEqual(
                2,
                main([
                    "phenotype",
                    "--experiment-spec", str(spec_path),
                    "--measurements", str(measurements_path),
                    "--phenotype-id", "phenotype-001",
                    "--phenotype-type", "growth_response",
                    "--phenotype-outcome", "negative",
                    "--interpretation", "Must remain non-evidence.",
                    "--assessor", "manual-review",
                    "--out", str(phenotype_path),
                ]),
            )
            self.assertFalse(phenotype_path.exists())


if __name__ == "__main__":
    unittest.main()

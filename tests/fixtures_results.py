"""Shared software contract fixtures; never experimental evidence."""

from pathlib import Path

from phage_lab.biology import read_fasta
from phage_lab.cocktail_design import (
    CocktailDesign,
    CocktailMember,
    DesignObjective,
    DesignProducer,
)
from phage_lab.experiment_spec import experiment_spec_from_cocktail
from phage_lab.interaction_evidence import (
    EvidenceProducer,
    HostReference,
    InteractionEvidence,
)
from phage_lab.material_batch import bind_material_batches_to_spec, new_material_batch
from phage_lab.measurement import Measurement
from phage_lab.phenotype import phenotype_from_measurements

from support import CANDIDATES, WORKFLOW


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

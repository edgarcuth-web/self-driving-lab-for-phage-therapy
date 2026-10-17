"""Software contract fixtures only; these are not experimental evidence."""

from dataclasses import replace

from phage_lab.failure_attribution import failure_attribution_from_results
from phage_lab.material_batch import new_material_batch
from phage_lab.natural_phage_recommender import experiment_spec_from_candidate_set
from phage_lab.phenotype import phenotype_from_measurements, phenotype_comparison_from_phenotypes
from fixtures_results import physical_measurement, STAMP
from fixtures_screening import T3

LATER = "2026-10-16T19:31:00+00:00"
LATEST = "2026-10-16T19:32:00+00:00"
CRITERION = "Fixture criterion, explicitly assessed; no biological claim."


def screen(pool):
    return experiment_spec_from_candidate_set(
        pool, experiment_id="screen-one", workflow={"measure": ()},
        objective="Contract-path comparison only.", expected_readouts=("device_result",),
        conditions={"assay_context": "fixture"}, created_at=T3,
    )


def review(spec, arm_id="single-phage-1", outcome="failure_observed", *,
           name="review", timestamp=STAMP, comparison=True):
    """Fabricated test doubles, confined to tests and never delivered as evidence."""
    batches = [new_material_batch(
        "fixture-host-batch", material_type="host", profile_id=spec.target_host.profile_id,
        source_kind="local_collection", source_reference="fixture://host",
        quality_status="released", quality_evidence=("fixture-qc",), created_at=T3,
    )]
    batches += [new_material_batch(
        f"fixture-phage-{index}", material_type="phage", profile_id=profile_id,
        source_kind="acquired", source_reference="fixture://phage",
        quality_status="released", quality_evidence=("fixture-qc",), created_at=T3,
    ) for index, profile_id in enumerate(spec.member_phage_profile_ids)]
    arm_ids = ("host-control", arm_id) if comparison else (arm_id,)
    measurements = [replace(physical_measurement(
        spec=spec, batches=batches, arm_id=key, measurement_id=f"{name}-measurement-{key}",
    ), recorded_at=timestamp, created_at=timestamp) for key in arm_ids]
    phenotypes = [phenotype_from_measurements(
        spec, [measurement], arm_id=measurement.experiment_arm_id,
        phenotype_id=f"{name}-phenotype-{measurement.experiment_arm_id}",
        phenotype_type="declared-response", outcome="negative",
        interpretation="Test fixture only; polarity does not determine failure.",
        assessor_name="fixture-reviewer", assessor_version="1", assessed_at=timestamp,
    ) for measurement in measurements]
    comparisons = [phenotype_comparison_from_phenotypes(
        spec, *phenotypes, comparison_id=f"{name}-comparison",
        comparison_type="declared", outcome="fixture-comparison",
        interpretation="Test fixture only.", assessor_name="fixture-reviewer",
        assessor_version="1", assessed_at=timestamp,
    )] if comparison else []
    return failure_attribution_from_results(
        spec, measurements, phenotypes, comparisons=comparisons,
        attribution_id=name, target_arm_id=arm_id, outcome=outcome, criterion=CRITERION,
        interpretation="Explicit fixture review only.", assessor_name="fixture-reviewer",
        assessor_version="1", limitations=("Test fixture, no biological claim.",),
        assessed_at=timestamp,
    )

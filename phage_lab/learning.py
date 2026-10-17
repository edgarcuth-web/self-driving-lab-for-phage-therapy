"""Learning records that connect physical phenotypes back to predictions.

LearningObservation stores an assessor-declared binary label for one prediction
target. It never infers a label from phenotype polarity. CalibrationReport scores
only comparable estimated predictions; it does not fit or update a model.
"""

from dataclasses import dataclass
import math
from pathlib import Path

from .artifacts import (
    atomic_write_json,
    canonical_json,
    content_hash,
    parse_timestamp as _time,
    read_json,
    require_text as _text,
    utc_now,
    with_content_hash,
)
from .experiment_spec import ExperimentSpec, experiment_spec_from_dict
from .interaction_prediction import (
    InteractionPrediction,
    interaction_prediction_from_dict,
)
from .phenotype import Phenotype, PhenotypeAssessor, phenotype_from_dict

SCHEMA_VERSION = 1
CALIBRATION_SCHEMA_VERSION = 1
PREDICTION_TARGETS = (
    "adsorption",
    "productive_infection",
    "resistance_emergence",
)


def _texts(values, name, *, nonempty=False):
    if not isinstance(values, tuple) or (nonempty and not values):
        raise ValueError(f"{name} must be a {'nonempty ' if nonempty else ''}tuple.")
    for value in values:
        _text(value, name)
    if len(set(values)) != len(values):
        raise ValueError(f"{name} values must be unique.")


def _assessor_from_dict(data):
    if not isinstance(data, dict) or set(data) != {"name", "version", "parameters"}:
        raise ValueError("assessor has missing or unknown fields.")
    return PhenotypeAssessor(
        name=data["name"], version=data["version"], parameters=data["parameters"]
    )


@dataclass(frozen=True)
class LearningObservation:
    """One explicit label for one prediction target and physical phenotype."""

    observation_id: str
    revision: int
    prediction: InteractionPrediction
    experiment_spec: ExperimentSpec
    phenotype: Phenotype
    target: str
    observed: bool
    interpretation: str
    assessor: PhenotypeAssessor
    limitations: tuple[str, ...]
    assessed_at: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self):
        _text(self.observation_id, "observation_id")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("revision must be a positive integer.")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("Unsupported LearningObservation schema_version.")
        if not isinstance(self.prediction, InteractionPrediction):
            raise ValueError("prediction must be an InteractionPrediction.")
        if not isinstance(self.experiment_spec, ExperimentSpec):
            raise ValueError("experiment_spec must be an ExperimentSpec.")
        if not isinstance(self.phenotype, Phenotype):
            raise ValueError("phenotype must be a Phenotype.")
        if self.target not in PREDICTION_TARGETS:
            raise ValueError(f"target must be one of {PREDICTION_TARGETS}.")
        if type(self.observed) is not bool:
            raise ValueError("observed must be a boolean.")
        _text(self.interpretation, "interpretation")
        if not isinstance(self.assessor, PhenotypeAssessor):
            raise ValueError("assessor must be a PhenotypeAssessor.")
        _texts(self.limitations, "limitations", nonempty=True)

        # Re-admit nested artifacts before crossing the learning boundary.
        interaction_prediction_from_dict(self.prediction.to_dict())
        experiment_spec_from_dict(self.experiment_spec.to_dict())
        phenotype_from_dict(self.phenotype.to_dict())

        phenotype = self.phenotype
        spec = self.experiment_spec
        prediction = self.prediction
        if (
            phenotype.experiment_spec_id != spec.spec_id
            or phenotype.experiment_spec_sha256 != spec.content_sha256
        ):
            raise ValueError("Phenotype does not match the exact ExperimentSpec.")
        arm = next(
            (item for item in spec.arms if item.arm_id == phenotype.experiment_arm_id),
            None,
        )
        if arm is None:
            raise ValueError("Phenotype arm is unavailable in ExperimentSpec.")
        if arm.role != "treatment" or len(arm.phage_profile_ids) != 1:
            raise ValueError(
                "LearningObservation v1 requires a single-phage treatment arm."
            )
        if (
            phenotype.phage_profile_ids != arm.phage_profile_ids
            or phenotype.target_host_profile_id != arm.target_host.profile_id
        ):
            raise ValueError("Phenotype lineage does not match its ExperimentArm.")
        if arm.phage_profile_ids[0] != prediction.phage_profile_id:
            raise ValueError("Prediction phage does not match the treatment arm.")
        if (
            arm.target_host.profile_id != prediction.host_state.host_profile_id
            or arm.target_host.genome_sha256 != prediction.host_state.host_genome_sha256
        ):
            raise ValueError("Prediction HostState does not match the experiment host.")
        assessed = _time(self.assessed_at, "assessed_at")
        if assessed < _time(phenotype.assessed_at, "phenotype assessed_at"):
            raise ValueError("Learning assessment cannot precede its Phenotype.")
        if assessed < _time(prediction.predicted_at, "predicted_at"):
            raise ValueError("Learning assessment cannot precede its prediction.")

    @property
    def record_id(self):
        return f"{self.observation_id}:v{self.revision}"

    @property
    def estimate(self):
        return getattr(self.prediction, self.target)

    @property
    def predicted_probability(self):
        return self.estimate.probability if self.estimate.status == "estimated" else None

    @property
    def squared_error(self):
        if self.predicted_probability is None:
            return None
        return (float(self.predicted_probability) - float(self.observed)) ** 2

    @property
    def learning_status(self):
        return "scorable" if self.estimate.status == "estimated" else "label_only"

    def _content_dict(self):
        return {
            "schema_version": self.schema_version,
            "record_id": self.record_id,
            "observation_id": self.observation_id,
            "revision": self.revision,
            "prediction": self.prediction.to_dict(),
            "experiment_spec": self.experiment_spec.to_dict(),
            "phenotype": self.phenotype.to_dict(),
            "target": self.target,
            "observed": self.observed,
            "predicted_probability": self.predicted_probability,
            "squared_error": self.squared_error,
            "learning_status": self.learning_status,
            "interpretation": self.interpretation,
            "assessor": self.assessor.to_dict(),
            "limitations": list(self.limitations),
            "assessed_at": self.assessed_at,
        }

    @property
    def content_sha256(self):
        return content_hash(self._content_dict())

    def to_dict(self):
        return with_content_hash(self._content_dict())


def new_learning_observation(
    prediction,
    experiment_spec,
    phenotype,
    *,
    observation_id,
    target,
    observed,
    interpretation,
    assessor_name,
    assessor_version,
    limitations,
    assessor_parameters=None,
    revision=1,
    assessed_at=None,
):
    """Detach inputs and record an explicit outcome label; never infer one."""

    if not isinstance(prediction, InteractionPrediction):
        raise ValueError("prediction must be an InteractionPrediction.")
    if not isinstance(experiment_spec, ExperimentSpec):
        raise ValueError("experiment_spec must be an ExperimentSpec.")
    if not isinstance(phenotype, Phenotype):
        raise ValueError("phenotype must be a Phenotype.")
    return LearningObservation(
        observation_id=observation_id,
        revision=revision,
        prediction=interaction_prediction_from_dict(prediction.to_dict()),
        experiment_spec=experiment_spec_from_dict(experiment_spec.to_dict()),
        phenotype=phenotype_from_dict(phenotype.to_dict()),
        target=target,
        observed=observed,
        interpretation=interpretation,
        assessor=PhenotypeAssessor(
            name=assessor_name,
            version=assessor_version,
            parameters=dict(assessor_parameters or {}),
        ),
        limitations=tuple(limitations),
        assessed_at=assessed_at or utc_now(),
    )


def learning_observation_from_dict(data):
    expected = {
        "content_sha256", "schema_version", "record_id", "observation_id",
        "revision", "prediction", "experiment_spec", "phenotype", "target",
        "observed", "predicted_probability", "squared_error", "learning_status",
        "interpretation", "assessor", "limitations", "assessed_at",
    }
    if not isinstance(data, dict) or set(data) != expected:
        raise ValueError("LearningObservation has missing or unknown fields.")
    if not isinstance(data["limitations"], list):
        raise ValueError("limitations must be an array.")
    result = LearningObservation(
        observation_id=data["observation_id"],
        revision=data["revision"],
        prediction=interaction_prediction_from_dict(data["prediction"]),
        experiment_spec=experiment_spec_from_dict(data["experiment_spec"]),
        phenotype=phenotype_from_dict(data["phenotype"]),
        target=data["target"],
        observed=data["observed"],
        interpretation=data["interpretation"],
        assessor=_assessor_from_dict(data["assessor"]),
        limitations=tuple(data["limitations"]),
        assessed_at=data["assessed_at"],
        schema_version=data["schema_version"],
    )
    if result.to_dict() != data:
        raise ValueError("LearningObservation derived fields or hash mismatch.")
    return result


def write_learning_observation(observation, path: Path):
    if not isinstance(observation, LearningObservation):
        raise ValueError("observation must be a LearningObservation.")
    atomic_write_json(observation.to_dict(), path)


def load_learning_observation(path: Path):
    return learning_observation_from_dict(read_json(path, "LearningObservation"))


@dataclass(frozen=True)
class CalibrationReport:
    """Descriptive proper-scoring metrics for one exact prediction cohort."""

    report_id: str
    revision: int
    target: str
    observations: tuple[LearningObservation, ...]
    created_at: str
    schema_version: int = CALIBRATION_SCHEMA_VERSION

    def __post_init__(self):
        _text(self.report_id, "report_id")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("revision must be a positive integer.")
        if self.schema_version != CALIBRATION_SCHEMA_VERSION:
            raise ValueError("Unsupported CalibrationReport schema_version.")
        if self.target not in PREDICTION_TARGETS:
            raise ValueError(f"target must be one of {PREDICTION_TARGETS}.")
        if not isinstance(self.observations, tuple) or not self.observations:
            raise ValueError("observations must be a nonempty tuple.")
        if any(not isinstance(item, LearningObservation) for item in self.observations):
            raise ValueError("observations must contain LearningObservation objects.")
        if len({item.record_id for item in self.observations}) != len(self.observations):
            raise ValueError("Calibration observations must have unique record IDs.")

        first = self.observations[0]
        if first.estimate.status != "estimated":
            raise ValueError("CalibrationReport requires estimated predictions.")
        cohort = canonical_json(first.prediction.producer.to_dict())
        method = first.estimate.uncertainty_method
        for item in self.observations:
            learning_observation_from_dict(item.to_dict())
            if item.target != self.target or item.estimate.status != "estimated":
                raise ValueError(
                    "Calibration observations must share one estimated target."
                )
            if canonical_json(item.prediction.producer.to_dict()) != cohort:
                raise ValueError(
                    "Calibration observations must share exact producer provenance."
                )
            if item.estimate.uncertainty_method != method:
                raise ValueError(
                    "Calibration observations must share one uncertainty method."
                )
        created = _time(self.created_at, "created_at")
        if any(created < _time(item.assessed_at, "observation assessed_at")
               for item in self.observations):
            raise ValueError("CalibrationReport cannot precede its observations.")

    @property
    def record_id(self):
        return f"{self.report_id}:v{self.revision}"

    @property
    def producer(self):
        return self.observations[0].prediction.producer

    @property
    def uncertainty_method(self):
        return self.observations[0].estimate.uncertainty_method

    @property
    def metrics(self):
        probabilities = [float(item.predicted_probability) for item in self.observations]
        labels = [float(item.observed) for item in self.observations]
        count = len(probabilities)
        epsilon = 1e-15
        log_loss = 0.0
        for probability, label in zip(probabilities, labels):
            clipped = min(1.0 - epsilon, max(epsilon, probability))
            log_loss -= label * math.log(clipped) + (1.0 - label) * math.log(1.0 - clipped)
        mean_probability = sum(probabilities) / count
        observed_rate = sum(labels) / count
        return {
            "sample_count": count,
            "mean_predicted_probability": mean_probability,
            "observed_rate": observed_rate,
            "calibration_gap": mean_probability - observed_rate,
            "brier_score": sum(
                (probability - label) ** 2
                for probability, label in zip(probabilities, labels)
            ) / count,
            "log_loss": log_loss / count,
        }

    @property
    def limitations(self):
        return (
            "Descriptive evaluation only; this report does not fit, recalibrate or update a biological model.",
            "Observed labels are assessor-declared mappings from physical Phenotype evidence, not automatically inferred ground truth.",
            "Exact producer provenance is matched, but assay comparability and dataset independence remain caller responsibilities.",
            "Selected or small samples can make calibration metrics misleading; no external validation is implied.",
        )

    def _content_dict(self):
        return {
            "schema_version": self.schema_version,
            "record_id": self.record_id,
            "report_id": self.report_id,
            "revision": self.revision,
            "target": self.target,
            "observations": [item.to_dict() for item in self.observations],
            "cohort": {
                "producer": self.producer.to_dict(),
                "uncertainty_method": self.uncertainty_method,
            },
            "metrics": self.metrics,
            "limitations": list(self.limitations),
            "created_at": self.created_at,
        }

    @property
    def content_sha256(self):
        return content_hash(self._content_dict())

    def to_dict(self):
        return with_content_hash(self._content_dict())


def calibration_report_from_observations(
    observations, *, report_id, target, revision=1, created_at=None
):
    if not isinstance(observations, (list, tuple)) or not observations:
        raise ValueError("observations must be a nonempty list or tuple.")
    detached = tuple(
        learning_observation_from_dict(item.to_dict())
        if isinstance(item, LearningObservation)
        else None
        for item in observations
    )
    if any(item is None for item in detached):
        raise ValueError("observations must contain LearningObservation objects.")
    return CalibrationReport(
        report_id=report_id,
        revision=revision,
        target=target,
        observations=detached,
        created_at=created_at or utc_now(),
    )


def calibration_report_from_dict(data):
    expected = {
        "content_sha256", "schema_version", "record_id", "report_id", "revision",
        "target", "observations", "cohort", "metrics", "limitations", "created_at",
    }
    if not isinstance(data, dict) or set(data) != expected:
        raise ValueError("CalibrationReport has missing or unknown fields.")
    if not isinstance(data["observations"], list):
        raise ValueError("observations must be an array.")
    result = CalibrationReport(
        report_id=data["report_id"],
        revision=data["revision"],
        target=data["target"],
        observations=tuple(
            learning_observation_from_dict(item) for item in data["observations"]
        ),
        created_at=data["created_at"],
        schema_version=data["schema_version"],
    )
    if result.to_dict() != data:
        raise ValueError("CalibrationReport derived fields or hash mismatch.")
    return result


def write_calibration_report(report, path: Path):
    if not isinstance(report, CalibrationReport):
        raise ValueError("report must be a CalibrationReport.")
    atomic_write_json(report.to_dict(), path)


def load_calibration_report(path: Path):
    return calibration_report_from_dict(read_json(path, "CalibrationReport"))

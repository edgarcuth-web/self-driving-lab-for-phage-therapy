"""Research-only supervised baseline for phage-host interaction features.

This module fits a deterministic logistic model from explicit, provenance-bound
feature vectors and admitted LearningObservation labels. Raw scores remain
uncalibrated research artifacts; they are not InteractionPrediction records.
"""

from dataclasses import dataclass, field
from hashlib import sha256
import math
import random
from pathlib import Path

from .artifacts import (
    atomic_write_json,
    content_hash,
    parse_timestamp,
    read_json,
    require_text,
    utc_now,
    validate_digest,
    with_content_hash,
)
from .host_state import HostState, HostStateReference, host_state_reference
from .interaction_prediction import phage_profile_sha256
from .learning import LearningObservation, learning_observation_from_dict
from .phage_profile import PhageProfile

SCHEMA_VERSION = 1
MODEL_TARGET = "productive_infection"
MODEL_ALGORITHM = "l2-logistic-sgd"
MODEL_ALGORITHM_VERSION = "1"
RESEARCH_SCORE_STATUS = "uncalibrated_research_score"

_FEATURE_VECTOR_FIELDS = {
    "content_sha256", "schema_version", "record_id", "vector_id", "revision",
    "host_state", "phage_profile_id", "phage_profile_sha256", "features",
    "feature_sources", "producer", "created_at",
}
_MODEL_FIELDS = {
    "content_sha256", "schema_version", "record_id", "model_id", "revision",
    "target", "algorithm", "algorithm_version", "input_feature_names",
    "transformed_feature_names", "imputation_means", "scales", "coefficients",
    "intercept", "training_dataset_sha256", "train_example_ids", "test_example_ids",
    "training_host_groups", "test_host_groups", "seed", "test_fraction", "epochs",
    "learning_rate", "l2", "metrics", "model_status", "calibration_status",
    "limitations", "created_at",
}
_RESEARCH_PREDICTION_FIELDS = {
    "content_sha256", "schema_version", "record_id", "prediction_id", "target",
    "status", "model_id", "model_artifact_sha256", "feature_vector_id",
    "feature_vector_sha256", "host_state", "phage_profile_id",
    "phage_profile_sha256", "uncalibrated_probability", "limitations",
    "predicted_at",
}
_METRIC_FIELDS = {
    "train_sample_count", "test_sample_count", "train_host_group_count",
    "test_host_group_count", "train_positive_rate", "test_positive_rate",
    "auroc", "average_precision", "brier_score", "log_loss",
    "prevalence_baseline_brier_score", "prevalence_baseline_log_loss",
}


def _text_tuple(values, field_name, *, nonempty=False):
    if not isinstance(values, tuple) or (nonempty and not values):
        raise ValueError(
            f"{field_name} must be a {'nonempty ' if nonempty else ''}tuple."
        )
    for value in values:
        require_text(value, field_name)
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} values must be unique.")


def _scalar_mapping(value, field_name):
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object.")
    for key, item in value.items():
        require_text(key, f"{field_name} key")
        if item is None or isinstance(item, (str, int, bool)):
            continue
        if isinstance(item, float) and math.isfinite(item):
            continue
        raise ValueError(f"{field_name} values must be finite JSON scalars or null.")


def _finite_number(value, field_name, *, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field_name} must be a finite number.")
    if minimum is not None and value < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}.")
    if maximum is not None and value > maximum:
        raise ValueError(f"{field_name} must be at most {maximum}.")


@dataclass(frozen=True)
class FeatureSource:
    """Provenance for one derived feature; the source artifact is not embedded."""

    source: str
    version: str
    method: str
    input_sha256: str
    reference: str | None = None
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self):
        for name in ("source", "version", "method"):
            require_text(getattr(self, name), name)
        validate_digest(self.input_sha256, "feature source input_sha256")
        if self.reference is not None:
            require_text(self.reference, "feature source reference")
        _text_tuple(self.evidence_ids, "feature source evidence_id")

    def to_dict(self):
        return {
            "source": self.source,
            "version": self.version,
            "method": self.method,
            "input_sha256": self.input_sha256,
            "reference": self.reference,
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(frozen=True)
class FeatureProducer:
    """Identity of the process that emitted a feature vector."""

    name: str
    version: str
    parameters: dict = field(default_factory=dict)
    code_sha256: str | None = None

    def __post_init__(self):
        require_text(self.name, "feature producer name")
        require_text(self.version, "feature producer version")
        _scalar_mapping(self.parameters, "feature producer parameters")
        if self.code_sha256 is not None:
            validate_digest(self.code_sha256, "feature producer code_sha256")

    def to_dict(self):
        return {
            "name": self.name,
            "version": self.version,
            "parameters": dict(self.parameters),
            "code_sha256": self.code_sha256,
        }


@dataclass(frozen=True)
class InteractionFeatureVector:
    """Content-addressed numeric features for one exact host-state/phage pair."""

    vector_id: str
    revision: int
    host_state: HostStateReference
    phage_profile_id: str
    phage_profile_sha256: str
    features: dict
    feature_sources: dict[str, FeatureSource]
    producer: FeatureProducer
    created_at: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self):
        require_text(self.vector_id, "vector_id")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("feature vector revision must be a positive integer.")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"InteractionFeatureVector schema_version must be {SCHEMA_VERSION}.")
        if not isinstance(self.host_state, HostStateReference):
            raise ValueError("feature vector host_state must be a HostStateReference.")
        require_text(self.phage_profile_id, "phage_profile_id")
        validate_digest(self.phage_profile_sha256, "phage_profile_sha256")
        if not isinstance(self.features, dict) or not self.features:
            raise ValueError("features must be a nonempty object.")
        for name, value in self.features.items():
            require_text(name, "feature name")
            if value is not None:
                _finite_number(value, f"feature {name}")
        if not isinstance(self.feature_sources, dict):
            raise ValueError("feature_sources must be an object.")
        if set(self.feature_sources) != set(self.features):
            raise ValueError("feature_sources must provide provenance for every feature and no others.")
        if any(not isinstance(source, FeatureSource) for source in self.feature_sources.values()):
            raise ValueError("feature_sources values must be FeatureSource objects.")
        if not isinstance(self.producer, FeatureProducer):
            raise ValueError("producer must be a FeatureProducer.")
        parse_timestamp(self.created_at, "feature vector created_at")

    @property
    def record_id(self):
        return f"{self.vector_id}:v{self.revision}"

    @property
    def feature_schema_id(self):
        return content_hash(sorted(self.features))

    @property
    def content_sha256(self):
        return content_hash(self._content_dict())

    def _content_dict(self):
        return {
            "schema_version": self.schema_version,
            "record_id": self.record_id,
            "vector_id": self.vector_id,
            "revision": self.revision,
            "host_state": self.host_state.to_dict(),
            "phage_profile_id": self.phage_profile_id,
            "phage_profile_sha256": self.phage_profile_sha256,
            "features": {key: self.features[key] for key in sorted(self.features)},
            "feature_sources": {
                key: self.feature_sources[key].to_dict()
                for key in sorted(self.feature_sources)
            },
            "producer": self.producer.to_dict(),
            "created_at": self.created_at,
        }

    def to_dict(self):
        return with_content_hash(self._content_dict())


def new_interaction_feature_vector(
    host_state: HostState,
    phage_profile: PhageProfile,
    features: dict,
    feature_sources: dict[str, FeatureSource],
    producer: FeatureProducer,
    *,
    vector_id: str,
    revision: int = 1,
    created_at: str | None = None,
) -> InteractionFeatureVector:
    """Bind externally extracted features to exact domain artifacts."""

    if not isinstance(host_state, HostState):
        raise ValueError("host_state must be a HostState.")
    if not isinstance(phage_profile, PhageProfile):
        raise ValueError("phage_profile must be a PhageProfile.")
    if not isinstance(producer, FeatureProducer):
        raise ValueError("producer must be a FeatureProducer.")
    return InteractionFeatureVector(
        vector_id=vector_id,
        revision=revision,
        host_state=host_state_reference(host_state),
        phage_profile_id=phage_profile.profile_id,
        phage_profile_sha256=phage_profile_sha256(phage_profile),
        features=dict(features),
        feature_sources=dict(feature_sources),
        producer=producer,
        created_at=created_at or utc_now(),
    )


def feature_source_from_dict(data):
    expected = {"source", "version", "method", "input_sha256", "reference", "evidence_ids"}
    if not isinstance(data, dict) or set(data) != expected:
        raise ValueError("FeatureSource has missing or unknown fields.")
    if not isinstance(data["evidence_ids"], list):
        raise ValueError("FeatureSource evidence_ids must be an array.")
    return FeatureSource(
        source=data["source"],
        version=data["version"],
        method=data["method"],
        input_sha256=data["input_sha256"],
        reference=data["reference"],
        evidence_ids=tuple(data["evidence_ids"]),
    )


def feature_producer_from_dict(data):
    expected = {"name", "version", "parameters", "code_sha256"}
    if not isinstance(data, dict) or set(data) != expected:
        raise ValueError("FeatureProducer has missing or unknown fields.")
    return FeatureProducer(
        name=data["name"],
        version=data["version"],
        parameters=data["parameters"],
        code_sha256=data["code_sha256"],
    )


def interaction_feature_vector_from_dict(data):
    if not isinstance(data, dict) or set(data) != _FEATURE_VECTOR_FIELDS:
        raise ValueError("InteractionFeatureVector has missing or unknown fields.")
    if data["schema_version"] != SCHEMA_VERSION:
        raise ValueError("Unsupported InteractionFeatureVector schema_version.")
    if not isinstance(data["host_state"], dict) or set(data["host_state"]) != {
        "record_id", "content_sha256", "host_profile_id", "host_genome_sha256", "as_of"
    }:
        raise ValueError("feature vector host_state reference is malformed.")
    if not isinstance(data["feature_sources"], dict):
        raise ValueError("feature_sources must be an object.")
    vector = InteractionFeatureVector(
        vector_id=data["vector_id"],
        revision=data["revision"],
        host_state=HostStateReference(**data["host_state"]),
        phage_profile_id=data["phage_profile_id"],
        phage_profile_sha256=data["phage_profile_sha256"],
        features=data["features"],
        feature_sources={
            name: feature_source_from_dict(source)
            for name, source in data["feature_sources"].items()
        },
        producer=feature_producer_from_dict(data["producer"]),
        created_at=data["created_at"],
        schema_version=data["schema_version"],
    )
    if vector.to_dict() != data:
        raise ValueError("InteractionFeatureVector content hash or derived fields mismatch.")
    return vector


def write_interaction_feature_vector(vector: InteractionFeatureVector, path: Path):
    if not isinstance(vector, InteractionFeatureVector):
        raise ValueError("vector must be an InteractionFeatureVector.")
    atomic_write_json(vector.to_dict(), path)


def load_interaction_feature_vector(path: Path):
    return interaction_feature_vector_from_dict(read_json(path, "InteractionFeatureVector"))


@dataclass(frozen=True)
class ModelTrainingExample:
    """One explicit physical label joined to a matching feature vector."""

    feature_vector: InteractionFeatureVector
    observation: LearningObservation

    def __post_init__(self):
        if not isinstance(self.feature_vector, InteractionFeatureVector):
            raise ValueError("feature_vector must be an InteractionFeatureVector.")
        if not isinstance(self.observation, LearningObservation):
            raise ValueError("observation must be a LearningObservation.")
        # Re-admit nested artifacts at the model-training boundary.
        interaction_feature_vector_from_dict(self.feature_vector.to_dict())
        learning_observation_from_dict(self.observation.to_dict())
        if self.observation.target != MODEL_TARGET:
            raise ValueError(f"InteractionModel v0 only supports target {MODEL_TARGET}.")
        prediction = self.observation.prediction
        if self.feature_vector.host_state.to_dict() != prediction.host_state.to_dict():
            raise ValueError("feature vector HostState lineage does not match LearningObservation prediction.")
        if self.feature_vector.phage_profile_id != prediction.phage_profile_id:
            raise ValueError("feature vector PhageProfile ID does not match LearningObservation prediction.")
        if self.feature_vector.phage_profile_sha256 != prediction.phage_profile_sha256:
            raise ValueError("feature vector PhageProfile fingerprint does not match LearningObservation prediction.")

    @property
    def label(self):
        return 1 if self.observation.observed else 0

    @property
    def host_group(self):
        return self.feature_vector.host_state.host_genome_sha256

    @property
    def pair_key(self):
        return (self.host_group, self.feature_vector.phage_profile_sha256)

    def to_dict(self):
        return {
            "feature_vector": self.feature_vector.to_dict(),
            "observation": self.observation.to_dict(),
        }


def model_training_example_from_dict(data):
    if not isinstance(data, dict) or set(data) != {"feature_vector", "observation"}:
        raise ValueError("ModelTrainingExample must contain exactly feature_vector and observation.")
    return ModelTrainingExample(
        feature_vector=interaction_feature_vector_from_dict(data["feature_vector"]),
        observation=learning_observation_from_dict(data["observation"]),
    )


@dataclass(frozen=True)
class InteractionModelArtifact:
    """Research-only logistic model plus its complete split and evaluation lineage."""

    model_id: str
    revision: int
    target: str
    algorithm: str
    algorithm_version: str
    input_feature_names: tuple[str, ...]
    transformed_feature_names: tuple[str, ...]
    imputation_means: dict[str, float]
    scales: dict[str, float]
    coefficients: tuple[float, ...]
    intercept: float
    training_dataset_sha256: str
    train_example_ids: tuple[str, ...]
    test_example_ids: tuple[str, ...]
    training_host_groups: tuple[str, ...]
    test_host_groups: tuple[str, ...]
    seed: int
    test_fraction: float
    epochs: int
    learning_rate: float
    l2: float
    metrics: dict
    model_status: str
    calibration_status: str
    limitations: tuple[str, ...]
    created_at: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self):
        require_text(self.model_id, "model_id")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("model revision must be a positive integer.")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"InteractionModelArtifact schema_version must be {SCHEMA_VERSION}.")
        if self.target != MODEL_TARGET:
            raise ValueError(f"InteractionModel v0 target must be {MODEL_TARGET}.")
        if self.algorithm != MODEL_ALGORITHM or self.algorithm_version != MODEL_ALGORITHM_VERSION:
            raise ValueError("unsupported InteractionModel algorithm or version.")
        _text_tuple(self.input_feature_names, "input_feature_names", nonempty=True)
        _text_tuple(self.transformed_feature_names, "transformed_feature_names", nonempty=True)
        expected_transformed = tuple(
            [f"value:{name}" for name in self.input_feature_names]
            + [f"missing:{name}" for name in self.input_feature_names]
        )
        if self.transformed_feature_names != expected_transformed:
            raise ValueError("transformed_feature_names do not match the input feature schema.")
        if tuple(sorted(self.input_feature_names)) != self.input_feature_names:
            raise ValueError("input_feature_names must be sorted for reproducibility.")
        if set(self.imputation_means) != set(self.input_feature_names):
            raise ValueError("imputation_means must cover exactly the input features.")
        if set(self.scales) != set(self.input_feature_names):
            raise ValueError("scales must cover exactly the input features.")
        for name in self.input_feature_names:
            _finite_number(self.imputation_means[name], f"imputation mean {name}")
            _finite_number(self.scales[name], f"scale {name}", minimum=0.0)
            if self.scales[name] == 0:
                raise ValueError("feature scales must be positive.")
        _text_tuple(tuple(self.train_example_ids), "train_example_ids", nonempty=True)
        _text_tuple(tuple(self.test_example_ids), "test_example_ids", nonempty=True)
        if set(self.train_example_ids) & set(self.test_example_ids):
            raise ValueError("train and test example IDs must be disjoint.")
        if len(self.coefficients) != len(self.transformed_feature_names):
            raise ValueError("coefficient count does not match transformed features.")
        for index, value in enumerate(self.coefficients):
            _finite_number(value, f"coefficient {index}")
        _finite_number(self.intercept, "intercept")
        validate_digest(self.training_dataset_sha256, "training_dataset_sha256")
        _text_tuple(self.training_host_groups, "training_host_groups", nonempty=True)
        _text_tuple(self.test_host_groups, "test_host_groups", nonempty=True)
        for group in self.training_host_groups + self.test_host_groups:
            validate_digest(group, "host group")
        if set(self.training_host_groups) & set(self.test_host_groups):
            raise ValueError("training and test host groups must be disjoint.")
        if type(self.seed) is not int:
            raise ValueError("seed must be an integer.")
        _finite_number(self.test_fraction, "test_fraction", minimum=0.0, maximum=0.5)
        if self.test_fraction == 0 or self.test_fraction >= 0.5:
            raise ValueError("test_fraction must be greater than 0 and less than 0.5.")
        if type(self.epochs) is not int or self.epochs < 1:
            raise ValueError("epochs must be a positive integer.")
        _finite_number(self.learning_rate, "learning_rate", minimum=0.0)
        if self.learning_rate == 0:
            raise ValueError("learning_rate must be positive.")
        _finite_number(self.l2, "l2", minimum=0.0)
        if not isinstance(self.metrics, dict) or set(self.metrics) != _METRIC_FIELDS:
            raise ValueError("metrics have missing or unknown fields.")
        _scalar_mapping(self.metrics, "metrics")
        if self.metrics["train_sample_count"] != len(self.train_example_ids):
            raise ValueError("train sample count does not match train example IDs.")
        if self.metrics["test_sample_count"] != len(self.test_example_ids):
            raise ValueError("test sample count does not match test example IDs.")
        if self.model_status != "research_only":
            raise ValueError("v0 models must remain research_only.")
        if self.calibration_status != "not_calibrated":
            raise ValueError("v0 models must remain not_calibrated.")
        _text_tuple(self.limitations, "limitations", nonempty=True)
        parse_timestamp(self.created_at, "model created_at")

    @property
    def record_id(self):
        return f"{self.model_id}:v{self.revision}"

    @property
    def content_sha256(self):
        return content_hash(self._content_dict())

    def _content_dict(self):
        return {
            "schema_version": self.schema_version,
            "record_id": self.record_id,
            "model_id": self.model_id,
            "revision": self.revision,
            "target": self.target,
            "algorithm": self.algorithm,
            "algorithm_version": self.algorithm_version,
            "input_feature_names": list(self.input_feature_names),
            "transformed_feature_names": list(self.transformed_feature_names),
            "imputation_means": dict(self.imputation_means),
            "scales": dict(self.scales),
            "coefficients": list(self.coefficients),
            "intercept": self.intercept,
            "training_dataset_sha256": self.training_dataset_sha256,
            "train_example_ids": list(self.train_example_ids),
            "test_example_ids": list(self.test_example_ids),
            "training_host_groups": list(self.training_host_groups),
            "test_host_groups": list(self.test_host_groups),
            "seed": self.seed,
            "test_fraction": self.test_fraction,
            "epochs": self.epochs,
            "learning_rate": self.learning_rate,
            "l2": self.l2,
            "metrics": dict(self.metrics),
            "model_status": self.model_status,
            "calibration_status": self.calibration_status,
            "limitations": list(self.limitations),
            "created_at": self.created_at,
        }

    def to_dict(self):
        return with_content_hash(self._content_dict())


def interaction_model_from_dict(data):
    if not isinstance(data, dict) or set(data) != _MODEL_FIELDS:
        raise ValueError("InteractionModelArtifact has missing or unknown fields.")
    list_fields = (
        "input_feature_names", "transformed_feature_names", "coefficients",
        "train_example_ids", "test_example_ids", "training_host_groups",
        "test_host_groups", "limitations",
    )
    if any(not isinstance(data[name], list) for name in list_fields):
        raise ValueError("InteractionModelArtifact array fields must be arrays.")
    model = InteractionModelArtifact(
        model_id=data["model_id"],
        revision=data["revision"],
        target=data["target"],
        algorithm=data["algorithm"],
        algorithm_version=data["algorithm_version"],
        input_feature_names=tuple(data["input_feature_names"]),
        transformed_feature_names=tuple(data["transformed_feature_names"]),
        imputation_means=data["imputation_means"],
        scales=data["scales"],
        coefficients=tuple(data["coefficients"]),
        intercept=data["intercept"],
        training_dataset_sha256=data["training_dataset_sha256"],
        train_example_ids=tuple(data["train_example_ids"]),
        test_example_ids=tuple(data["test_example_ids"]),
        training_host_groups=tuple(data["training_host_groups"]),
        test_host_groups=tuple(data["test_host_groups"]),
        seed=data["seed"],
        test_fraction=data["test_fraction"],
        epochs=data["epochs"],
        learning_rate=data["learning_rate"],
        l2=data["l2"],
        metrics=data["metrics"],
        model_status=data["model_status"],
        calibration_status=data["calibration_status"],
        limitations=tuple(data["limitations"]),
        created_at=data["created_at"],
        schema_version=data["schema_version"],
    )
    if model.to_dict() != data:
        raise ValueError("InteractionModelArtifact content hash or derived fields mismatch.")
    return model


def write_interaction_model(model: InteractionModelArtifact, path: Path):
    if not isinstance(model, InteractionModelArtifact):
        raise ValueError("model must be an InteractionModelArtifact.")
    atomic_write_json(model.to_dict(), path)


def load_interaction_model(path: Path):
    return interaction_model_from_dict(read_json(path, "InteractionModelArtifact"))


def _group_split(examples, *, test_fraction, seed):
    groups = sorted({example.host_group for example in examples})
    if len(groups) < 5:
        raise ValueError(
            "InteractionModel v0 requires at least five distinct host-genome groups "
            "for a grouped train/test split."
        )
    test_count = max(2, min(len(groups) - 2, math.ceil(len(groups) * test_fraction)))
    group_labels = {
        group: {example.label for example in examples if example.host_group == group}
        for group in groups
    }
    for attempt in range(512):
        ordered = sorted(
            groups,
            key=lambda group: sha256(f"{seed}:{attempt}:{group}".encode("utf-8")).hexdigest(),
        )
        test_groups = set(ordered[:test_count])
        train_groups = set(ordered[test_count:])
        train_labels = {
            example.label for example in examples if example.host_group in train_groups
        }
        test_labels = {
            example.label for example in examples if example.host_group in test_groups
        }
        if train_labels == {0, 1} and test_labels == {0, 1}:
            return train_groups, test_groups
    raise ValueError(
        "Could not create a host-grouped train/test split containing both labels in "
        "each partition; add more diverse host groups or change the seed/test fraction."
    )


def _preprocess_fit(examples, feature_names):
    means, scales = {}, {}
    for name in feature_names:
        values = [
            float(example.feature_vector.features[name])
            for example in examples
            if example.feature_vector.features[name] is not None
        ]
        if not values:
            raise ValueError(
                f"feature {name!r} is missing for every training row; remove it or add assessed values."
            )
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        scale = math.sqrt(variance) if variance > 0 else 1.0
        means[name] = mean
        scales[name] = scale
    return means, scales


def _transform(vector, feature_names, means, scales):
    if tuple(sorted(vector.features)) != tuple(feature_names):
        raise ValueError("feature schema or feature names do not match the model.")
    values, missing = [], []
    for name in feature_names:
        raw = vector.features[name]
        if raw is None:
            values.append(0.0)
            missing.append(1.0)
        else:
            values.append((float(raw) - means[name]) / scales[name])
            missing.append(0.0)
    return values + missing


def _sigmoid(value):
    if value >= 0:
        inverse = math.exp(-min(value, 700.0))
        return 1.0 / (1.0 + inverse)
    exponential = math.exp(max(value, -700.0))
    return exponential / (1.0 + exponential)


def _fit_logistic(rows, labels, *, epochs, learning_rate, l2, seed):
    count = len(rows)
    dimensions = len(rows[0])
    positive_rate = sum(labels) / count
    clipped_rate = min(1.0 - 1e-6, max(1e-6, positive_rate))
    intercept = math.log(clipped_rate / (1.0 - clipped_rate))
    weights = [0.0] * dimensions
    batch_size = min(32, count)
    for epoch in range(epochs):
        order = list(range(count))
        random.Random(seed + epoch).shuffle(order)
        for start in range(0, count, batch_size):
            batch = order[start:start + batch_size]
            gradient = [0.0] * dimensions
            intercept_gradient = 0.0
            for index in batch:
                row = rows[index]
                score = intercept + sum(weights[j] * row[j] for j in range(dimensions))
                error = _sigmoid(score) - labels[index]
                intercept_gradient += error
                for j in range(dimensions):
                    gradient[j] += error * row[j]
            denominator = len(batch)
            for j in range(dimensions):
                weights[j] -= learning_rate * (
                    gradient[j] / denominator + l2 * weights[j]
                )
            intercept -= learning_rate * intercept_gradient / denominator
    return tuple(weights), intercept


def _probability(weights, intercept, row):
    return _sigmoid(intercept + sum(weights[index] * value for index, value in enumerate(row)))


def _auc(labels, probabilities):
    positives = sum(labels)
    negatives = len(labels) - positives
    if positives == 0 or negatives == 0:
        return None
    ordered = sorted(range(len(labels)), key=lambda index: probabilities[index])
    rank_sum = 0.0
    cursor = 0
    while cursor < len(ordered):
        end = cursor + 1
        while end < len(ordered) and probabilities[ordered[end]] == probabilities[ordered[cursor]]:
            end += 1
        average_rank = ((cursor + 1) + end) / 2.0
        for position in range(cursor, end):
            if labels[ordered[position]] == 1:
                rank_sum += average_rank
        cursor = end
    return (rank_sum - positives * (positives + 1) / 2.0) / (positives * negatives)


def _average_precision(labels, probabilities):
    positives = sum(labels)
    if positives == 0:
        return None
    ordered = sorted(
        range(len(labels)),
        key=lambda index: (-probabilities[index], index),
    )
    hits, precision_sum = 0, 0.0
    for rank, index in enumerate(ordered, start=1):
        if labels[index] == 1:
            hits += 1
            precision_sum += hits / rank
    return precision_sum / positives


def _brier(labels, probabilities):
    return sum((probabilities[i] - labels[i]) ** 2 for i in range(len(labels))) / len(labels)


def _log_loss(labels, probabilities):
    epsilon = 1e-15
    total = 0.0
    for label, probability in zip(labels, probabilities):
        probability = min(1.0 - epsilon, max(epsilon, probability))
        total -= label * math.log(probability) + (1 - label) * math.log(1 - probability)
    return total / len(labels)


def train_interaction_model(
    examples,
    *,
    model_id: str,
    revision: int = 1,
    test_fraction: float = 0.25,
    seed: int = 17,
    epochs: int = 120,
    learning_rate: float = 0.05,
    l2: float = 0.01,
    created_at: str | None = None,
) -> InteractionModelArtifact:
    """Fit and evaluate a research-only productive-infection baseline."""

    require_text(model_id, "model_id")
    if not isinstance(examples, (list, tuple)) or not examples:
        raise ValueError("examples must be a nonempty list or tuple.")
    if any(not isinstance(example, ModelTrainingExample) for example in examples):
        raise ValueError("examples must contain ModelTrainingExample objects.")
    if type(seed) is not int:
        raise ValueError("seed must be an integer.")
    if type(epochs) is not int or epochs < 1:
        raise ValueError("epochs must be a positive integer.")
    _finite_number(test_fraction, "test_fraction", minimum=0.0, maximum=0.5)
    if test_fraction == 0 or test_fraction >= 0.5:
        raise ValueError("test_fraction must be greater than 0 and less than 0.5.")
    _finite_number(learning_rate, "learning_rate", minimum=0.0)
    if learning_rate == 0:
        raise ValueError("learning_rate must be positive.")
    _finite_number(l2, "l2", minimum=0.0)
    if revision < 1:
        raise ValueError("revision must be a positive integer.")

    ordered_examples = sorted(examples, key=lambda item: item.observation.record_id)
    example_ids = [item.observation.record_id for item in ordered_examples]
    if len(set(example_ids)) != len(example_ids):
        raise ValueError("duplicate LearningObservation IDs are not allowed.")
    pair_keys = [item.pair_key for item in ordered_examples]
    if len(set(pair_keys)) != len(pair_keys):
        raise ValueError("duplicate host-genome/phage pairs are not allowed.")
    feature_names = tuple(sorted(ordered_examples[0].feature_vector.features))
    for item in ordered_examples:
        if tuple(sorted(item.feature_vector.features)) != feature_names:
            raise ValueError("all feature vectors must use exactly the same feature schema.")
        if item.observation.target != MODEL_TARGET:
            raise ValueError(f"all labels must target {MODEL_TARGET}.")
    labels = [item.label for item in ordered_examples]
    if set(labels) != {0, 1}:
        raise ValueError("training data must contain both positive and negative labels.")

    train_groups, test_groups = _group_split(
        ordered_examples, test_fraction=test_fraction, seed=seed
    )
    train_examples = [item for item in ordered_examples if item.host_group in train_groups]
    test_examples = [item for item in ordered_examples if item.host_group in test_groups]
    train_labels = [item.label for item in train_examples]
    test_labels = [item.label for item in test_examples]
    means, scales = _preprocess_fit(train_examples, feature_names)
    train_rows = [
        _transform(item.feature_vector, feature_names, means, scales)
        for item in train_examples
    ]
    test_rows = [
        _transform(item.feature_vector, feature_names, means, scales)
        for item in test_examples
    ]
    coefficients, intercept = _fit_logistic(
        train_rows,
        train_labels,
        epochs=epochs,
        learning_rate=learning_rate,
        l2=l2,
        seed=seed,
    )
    test_probabilities = [
        _probability(coefficients, intercept, row) for row in test_rows
    ]
    train_prevalence = sum(train_labels) / len(train_labels)
    baseline_probabilities = [train_prevalence] * len(test_labels)
    metrics = {
        "train_sample_count": len(train_examples),
        "test_sample_count": len(test_examples),
        "train_host_group_count": len(train_groups),
        "test_host_group_count": len(test_groups),
        "train_positive_rate": train_prevalence,
        "test_positive_rate": sum(test_labels) / len(test_labels),
        "auroc": _auc(test_labels, test_probabilities),
        "average_precision": _average_precision(test_labels, test_probabilities),
        "brier_score": _brier(test_labels, test_probabilities),
        "log_loss": _log_loss(test_labels, test_probabilities),
        "prevalence_baseline_brier_score": _brier(test_labels, baseline_probabilities),
        "prevalence_baseline_log_loss": _log_loss(test_labels, baseline_probabilities),
    }
    dataset_sha256 = content_hash([item.to_dict() for item in ordered_examples])
    transformed_names = tuple(
        [f"value:{name}" for name in feature_names]
        + [f"missing:{name}" for name in feature_names]
    )
    return InteractionModelArtifact(
        model_id=model_id,
        revision=revision,
        target=MODEL_TARGET,
        algorithm=MODEL_ALGORITHM,
        algorithm_version=MODEL_ALGORITHM_VERSION,
        input_feature_names=feature_names,
        transformed_feature_names=transformed_names,
        imputation_means=means,
        scales=scales,
        coefficients=coefficients,
        intercept=intercept,
        training_dataset_sha256=dataset_sha256,
        train_example_ids=tuple(item.observation.record_id for item in train_examples),
        test_example_ids=tuple(item.observation.record_id for item in test_examples),
        training_host_groups=tuple(sorted(train_groups)),
        test_host_groups=tuple(sorted(test_groups)),
        seed=seed,
        test_fraction=test_fraction,
        epochs=epochs,
        learning_rate=learning_rate,
        l2=l2,
        metrics=metrics,
        model_status="research_only",
        calibration_status="not_calibrated",
        limitations=(
            "Research-only baseline; the raw score is uncalibrated.",
            "Feature vectors are supplied by an upstream analysis; this module does not extract biological features.",
            "External validation and assay comparability have not been established.",
        ),
        created_at=created_at or utc_now(),
    )


@dataclass(frozen=True)
class ResearchPrediction:
    """Uncalibrated model score; intentionally not an InteractionPrediction."""

    prediction_id: str
    target: str
    status: str
    model_id: str
    model_artifact_sha256: str
    feature_vector_id: str
    feature_vector_sha256: str
    host_state: HostStateReference
    phage_profile_id: str
    phage_profile_sha256: str
    uncalibrated_probability: float
    limitations: tuple[str, ...]
    predicted_at: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self):
        require_text(self.prediction_id, "prediction_id")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"ResearchPrediction schema_version must be {SCHEMA_VERSION}.")
        if self.target != MODEL_TARGET:
            raise ValueError(f"ResearchPrediction target must be {MODEL_TARGET}.")
        if self.status != RESEARCH_SCORE_STATUS:
            raise ValueError(f"ResearchPrediction status must be {RESEARCH_SCORE_STATUS}.")
        require_text(self.model_id, "model_id")
        validate_digest(self.model_artifact_sha256, "model_artifact_sha256")
        require_text(self.feature_vector_id, "feature_vector_id")
        validate_digest(self.feature_vector_sha256, "feature_vector_sha256")
        if not isinstance(self.host_state, HostStateReference):
            raise ValueError("ResearchPrediction host_state must be a HostStateReference.")
        require_text(self.phage_profile_id, "phage_profile_id")
        validate_digest(self.phage_profile_sha256, "phage_profile_sha256")
        _finite_number(self.uncalibrated_probability, "uncalibrated_probability", minimum=0.0, maximum=1.0)
        _text_tuple(self.limitations, "limitations", nonempty=True)
        parse_timestamp(self.predicted_at, "ResearchPrediction predicted_at")

    @property
    def record_id(self):
        return self.prediction_id

    def _content_dict(self):
        return {
            "schema_version": self.schema_version,
            "record_id": self.record_id,
            "prediction_id": self.prediction_id,
            "target": self.target,
            "status": self.status,
            "model_id": self.model_id,
            "model_artifact_sha256": self.model_artifact_sha256,
            "feature_vector_id": self.feature_vector_id,
            "feature_vector_sha256": self.feature_vector_sha256,
            "host_state": self.host_state.to_dict(),
            "phage_profile_id": self.phage_profile_id,
            "phage_profile_sha256": self.phage_profile_sha256,
            "uncalibrated_probability": self.uncalibrated_probability,
            "limitations": list(self.limitations),
            "predicted_at": self.predicted_at,
        }

    def to_dict(self):
        return with_content_hash(self._content_dict())


def predict_research_score(
    model: InteractionModelArtifact,
    feature_vector: InteractionFeatureVector,
    *,
    prediction_id: str,
    predicted_at: str | None = None,
) -> ResearchPrediction:
    """Score one compatible feature vector without claiming calibration."""

    if not isinstance(model, InteractionModelArtifact):
        raise ValueError("model must be an InteractionModelArtifact.")
    if not isinstance(feature_vector, InteractionFeatureVector):
        raise ValueError("feature_vector must be an InteractionFeatureVector.")
    row = _transform(
        feature_vector,
        model.input_feature_names,
        model.imputation_means,
        model.scales,
    )
    score = _probability(model.coefficients, model.intercept, row)
    return ResearchPrediction(
        prediction_id=prediction_id,
        target=MODEL_TARGET,
        status=RESEARCH_SCORE_STATUS,
        model_id=model.model_id,
        model_artifact_sha256=model.content_sha256,
        feature_vector_id=feature_vector.record_id,
        feature_vector_sha256=feature_vector.content_sha256,
        host_state=feature_vector.host_state,
        phage_profile_id=feature_vector.phage_profile_id,
        phage_profile_sha256=feature_vector.phage_profile_sha256,
        uncalibrated_probability=score,
        limitations=(
            "Uncalibrated research score; not an admitted InteractionPrediction.",
            "Do not use this score as clinical evidence or as a calibrated probability.",
        ),
        predicted_at=predicted_at or utc_now(),
    )


def research_prediction_from_dict(data):
    if not isinstance(data, dict) or set(data) != _RESEARCH_PREDICTION_FIELDS:
        raise ValueError("ResearchPrediction has missing or unknown fields.")
    if not isinstance(data["host_state"], dict) or set(data["host_state"]) != {
        "record_id", "content_sha256", "host_profile_id", "host_genome_sha256", "as_of"
    }:
        raise ValueError("ResearchPrediction host_state reference is malformed.")
    if not isinstance(data["limitations"], list):
        raise ValueError("ResearchPrediction limitations must be an array.")
    prediction = ResearchPrediction(
        prediction_id=data["prediction_id"],
        target=data["target"],
        status=data["status"],
        model_id=data["model_id"],
        model_artifact_sha256=data["model_artifact_sha256"],
        feature_vector_id=data["feature_vector_id"],
        feature_vector_sha256=data["feature_vector_sha256"],
        host_state=HostStateReference(**data["host_state"]),
        phage_profile_id=data["phage_profile_id"],
        phage_profile_sha256=data["phage_profile_sha256"],
        uncalibrated_probability=data["uncalibrated_probability"],
        limitations=tuple(data["limitations"]),
        predicted_at=data["predicted_at"],
        schema_version=data["schema_version"],
    )
    if prediction.to_dict() != data:
        raise ValueError("ResearchPrediction content hash or derived fields mismatch.")
    return prediction


def write_research_prediction(prediction: ResearchPrediction, path: Path):
    if not isinstance(prediction, ResearchPrediction):
        raise ValueError("prediction must be a ResearchPrediction.")
    atomic_write_json(prediction.to_dict(), path)


def load_research_prediction(path: Path):
    return research_prediction_from_dict(read_json(path, "ResearchPrediction"))

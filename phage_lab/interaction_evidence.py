"""Traceable evidence about one host-phage interaction.

InteractionEvidence is deliberately weaker than a susceptibility call. It records
what a source observed or computed, with explicit producer and input provenance,
without silently promoting that signal into infection probability, susceptible/
resistant labels, or biological truth.
"""

from dataclasses import dataclass, field
from hashlib import sha256
import json
from pathlib import Path
import re

from .artifacts import (
    atomic_write_json,
    parse_timestamp as _validate_timestamp,
    read_json,
    require_text as _require_text,
)

SCHEMA_VERSION = 1
EVIDENCE_KINDS = ("source_annotation", "computational")
SHA256_PATTERN = re.compile(r"\A[0-9a-f]{64}\Z")
_SUSPECT_PROBABILITY = re.compile(
    r"(probab|likelihood|efficacy|infectivity|success_rate)", re.I
)


def _validate_sha256(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not SHA256_PATTERN.match(value):
        raise ValueError(f"{field_name} must be a SHA-256 digest.")


def _validate_scalar_mapping(value: dict, field_name: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object.")
    for key, item in value.items():
        _require_text(key, f"{field_name} key")
        if item is not None and not isinstance(item, (str, int, float, bool)):
            raise ValueError(
                f"{field_name} values must be scalar values or null."
            )


@dataclass(frozen=True)
class HostReference:
    """Host identity usable before every workflow has a HostProfile ID."""

    genome_sha256: str
    profile_id: str | None = None

    def __post_init__(self) -> None:
        _validate_sha256(self.genome_sha256, "host genome_sha256")
        if self.profile_id is not None:
            _require_text(self.profile_id, "host profile_id")

    def to_dict(self) -> dict:
        result = {"genome_sha256": self.genome_sha256}
        if self.profile_id is not None:
            result["profile_id"] = self.profile_id
        return result


@dataclass(frozen=True)
class EvidenceProducer:
    """Identity of the database/tool/model that emitted an evidence record."""

    name: str
    version: str
    parameters: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.name, "producer name")
        _require_text(self.version, "producer version")
        _validate_scalar_mapping(self.parameters, "producer parameters")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "parameters": dict(self.parameters),
        }


@dataclass(frozen=True)
class InteractionEvidence:
    """Immutable evidence linking one host and one versioned phage profile."""

    host: HostReference
    phage_profile_id: str
    kind: str
    signal: str
    result: dict
    interpretation: str
    observed_at: str
    producer: EvidenceProducer
    input_provenance: dict = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"InteractionEvidence schema_version must be {SCHEMA_VERSION}."
            )
        if not isinstance(self.host, HostReference):
            raise ValueError("host must be a HostReference.")
        _require_text(self.phage_profile_id, "phage_profile_id")
        if self.kind not in EVIDENCE_KINDS:
            raise ValueError(
                "kind must be one of " + ", ".join(EVIDENCE_KINDS) + "."
            )
        _require_text(self.signal, "signal")
        _require_text(self.interpretation, "interpretation")
        _validate_timestamp(self.observed_at, "observed_at")
        if not isinstance(self.producer, EvidenceProducer):
            raise ValueError("producer must be an EvidenceProducer.")
        _validate_scalar_mapping(self.result, "result")
        _validate_scalar_mapping(self.input_provenance, "input_provenance")
        offenders = [
            key for key in self.result if _SUSPECT_PROBABILITY.search(key)
        ]
        if offenders:
            raise ValueError(
                "InteractionEvidence result contains probability-shaped field(s): "
                + ", ".join(offenders)
                + ". Store the source statistic, not an invented infection probability."
            )

    @property
    def evidence_id(self) -> str:
        canonical = json.dumps(
            self._content_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return "ie-" + sha256(canonical).hexdigest()

    def _content_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "host": self.host.to_dict(),
            "phage_profile_id": self.phage_profile_id,
            "kind": self.kind,
            "signal": self.signal,
            "result": dict(self.result),
            "interpretation": self.interpretation,
            "observed_at": self.observed_at,
            "producer": self.producer.to_dict(),
            "input_provenance": dict(self.input_provenance),
        }

    def to_dict(self) -> dict:
        return {"evidence_id": self.evidence_id, **self._content_dict()}


def _host_from_dict(data: dict) -> HostReference:
    if not isinstance(data, dict):
        raise ValueError("host must be an object.")
    allowed = {"genome_sha256", "profile_id"}
    if set(data) - allowed:
        raise ValueError("host contains unknown fields.")
    return HostReference(
        genome_sha256=data.get("genome_sha256"),
        profile_id=data.get("profile_id"),
    )


def _producer_from_dict(data: dict) -> EvidenceProducer:
    if not isinstance(data, dict):
        raise ValueError("producer must be an object.")
    required = {"name", "version", "parameters"}
    if set(data) != required:
        raise ValueError("producer has missing or unknown fields.")
    return EvidenceProducer(
        name=data["name"],
        version=data["version"],
        parameters=data["parameters"],
    )


def interaction_evidence_from_dict(data: dict) -> InteractionEvidence:
    """Validate and reconstruct serialized interaction evidence."""

    if not isinstance(data, dict):
        raise ValueError("InteractionEvidence must be an object.")
    required = {
        "evidence_id",
        "schema_version",
        "host",
        "phage_profile_id",
        "kind",
        "signal",
        "result",
        "interpretation",
        "observed_at",
        "producer",
        "input_provenance",
    }
    if set(data) != required:
        raise ValueError("InteractionEvidence has missing or unknown fields.")
    evidence = InteractionEvidence(
        schema_version=data["schema_version"],
        host=_host_from_dict(data["host"]),
        phage_profile_id=data["phage_profile_id"],
        kind=data["kind"],
        signal=data["signal"],
        result=data["result"],
        interpretation=data["interpretation"],
        observed_at=data["observed_at"],
        producer=_producer_from_dict(data["producer"]),
        input_provenance=data["input_provenance"],
    )
    if data["evidence_id"] != evidence.evidence_id:
        raise ValueError("evidence_id does not match the evidence content.")
    return evidence


def phist_ranking_to_evidence(
    record: dict,
    *,
    host_profile_id: str | None = None,
) -> InteractionEvidence:
    """Convert one legacy PHIST ranking block into InteractionEvidence v1.

    The legacy ranking block remains supported by the current workflow. This
    adapter creates the scientific evidence object that future decision layers
    should consume.
    """

    if not isinstance(record, dict):
        raise ValueError("ranked candidate must be an object.")
    ranking = record.get("ranking")
    if not isinstance(ranking, dict):
        raise ValueError("ranked candidate has no ranking block.")
    if ranking.get("tool") != "phist":
        raise ValueError("only PHIST ranking blocks are supported by this adapter.")

    required = (
        "tool_version",
        "parameters",
        "ranked_at",
        "host_genome_sha256",
        "statistic",
        "interpretation",
        "reported",
    )
    missing = [field for field in required if field not in ranking]
    if missing:
        raise ValueError(
            "PHIST ranking is missing required fields: " + ", ".join(missing)
        )
    if type(ranking["reported"]) is not bool:
        raise ValueError("PHIST reported must be a boolean.")

    phage_profile_id = record.get("phage_profile_id")
    if phage_profile_id is None:
        candidate_id = record.get("id")
        _require_text(candidate_id, "candidate id")
        phage_profile_id = f"{candidate_id}:v1"
    _require_text(phage_profile_id, "phage_profile_id")

    result = {
        "status": "reported_signal" if ranking["reported"] else "no_signal",
        "statistic": ranking["statistic"],
    }
    if ranking["reported"]:
        if ranking.get("rank") is None:
            raise ValueError("reported PHIST ranking requires a rank.")
        for field in ("value", "pvalue", "adj_pvalue"):
            if field in ranking:
                result[field] = ranking[field]
    elif ranking.get("rank") is not None:
        raise ValueError("unreported PHIST evidence cannot carry a rank.")

    interpretation = ranking["interpretation"]
    if not ranking["reported"] and ranking.get("note"):
        interpretation = interpretation + " " + str(ranking["note"])

    input_provenance = {}
    for field in ("sequence_snapshot_version", "sequence_snapshot_sha256"):
        if ranking.get(field) is not None:
            input_provenance[field] = ranking[field]

    return InteractionEvidence(
        host=HostReference(
            genome_sha256=ranking["host_genome_sha256"],
            profile_id=host_profile_id,
        ),
        phage_profile_id=phage_profile_id,
        kind="computational",
        signal="shared_kmer_similarity",
        result=result,
        interpretation=interpretation,
        observed_at=ranking["ranked_at"],
        producer=EvidenceProducer(
            name="phist",
            version=ranking["tool_version"],
            parameters=ranking["parameters"],
        ),
        input_provenance=input_provenance,
    )


def write_interaction_evidence(
    evidence: InteractionEvidence,
    path: Path,
) -> None:
    """Atomically write one InteractionEvidence JSON document."""

    if not isinstance(evidence, InteractionEvidence):
        raise ValueError("evidence must be an InteractionEvidence.")
    atomic_write_json(evidence.to_dict(), path)


def load_interaction_evidence(path: Path) -> InteractionEvidence:
    """Load and validate one InteractionEvidence JSON document."""

    data = read_json(path, 'InteractionEvidence')
    return interaction_evidence_from_dict(data)

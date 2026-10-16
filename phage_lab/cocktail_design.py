"""Versioned, traceable cocktail designs.

CocktailDesign is a scientific design artifact, not an execution plan. It binds
one HostProfile to versioned PhageProfiles and the InteractionEvidence that
supports each selected member. It records objectives, assumptions and unresolved
gaps without promoting weak computational signals into efficacy claims.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from .host_profile import HostProfile
from .interaction_evidence import (
    EvidenceProducer,
    HostReference,
    InteractionEvidence,
    interaction_evidence_from_dict,
)
from .phage_profile import PhageProfile

SCHEMA_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a nonempty string.")
    return value.strip()


def _validate_timestamp(value: str, field_name: str) -> None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp.") from None
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone.")


def _validate_scalar_mapping(value: dict, field_name: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object.")
    for key, item in value.items():
        _require_text(key, f"{field_name} key")
        if item is not None and not isinstance(item, (str, int, float, bool)):
            raise ValueError(
                f"{field_name} values must be scalar values or null."
            )


def _validate_text_tuple(values: tuple[str, ...], field_name: str) -> None:
    if not isinstance(values, tuple):
        raise ValueError(f"{field_name} must be a tuple.")
    for value in values:
        _require_text(value, field_name)
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} values must be unique.")


@dataclass(frozen=True)
class DesignObjective:
    """A named goal with an explicit rationale, not an unsupported score."""

    name: str
    rationale: str

    def __post_init__(self) -> None:
        _require_text(self.name, "objective name")
        _require_text(self.rationale, "objective rationale")

    def to_dict(self) -> dict:
        return {"name": self.name, "rationale": self.rationale}


@dataclass(frozen=True)
class CocktailMember:
    """One selected PhageProfile and the evidence used to support its inclusion."""

    phage_profile_id: str
    evidence_ids: tuple[str, ...]
    selection_context: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.phage_profile_id, "member phage_profile_id")
        if not self.evidence_ids:
            raise ValueError("CocktailMember requires at least one evidence_id.")
        _validate_text_tuple(self.evidence_ids, "member evidence_id")
        _validate_scalar_mapping(self.selection_context, "selection_context")

    def to_dict(self) -> dict:
        return {
            "phage_profile_id": self.phage_profile_id,
            "evidence_ids": list(self.evidence_ids),
            "selection_context": dict(self.selection_context),
        }


@dataclass(frozen=True)
class CocktailDesign:
    """Immutable scientific proposal for a host-targeted phage combination."""

    cocktail_id: str
    revision: int
    target_host: HostReference
    members: tuple[CocktailMember, ...]
    supporting_evidence: tuple[InteractionEvidence, ...]
    objectives: tuple[DesignObjective, ...]
    assumptions: tuple[str, ...]
    unresolved_gaps: tuple[str, ...]
    rationale: str
    designer: EvidenceProducer
    created_at: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_text(self.cocktail_id, "cocktail_id")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("revision must be a positive integer.")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"CocktailDesign schema_version must be {SCHEMA_VERSION}."
            )
        if not isinstance(self.target_host, HostReference):
            raise ValueError("target_host must be a HostReference.")
        if self.target_host.profile_id is None:
            raise ValueError("CocktailDesign requires a target HostProfile ID.")
        if not self.members:
            raise ValueError("CocktailDesign requires at least one member.")
        if any(not isinstance(member, CocktailMember) for member in self.members):
            raise ValueError("members must contain CocktailMember objects.")
        member_ids = [member.phage_profile_id for member in self.members]
        if len(set(member_ids)) != len(member_ids):
            raise ValueError("CocktailDesign member PhageProfile IDs must be unique.")

        if not self.supporting_evidence:
            raise ValueError("CocktailDesign requires supporting InteractionEvidence.")
        if any(
            not isinstance(evidence, InteractionEvidence)
            for evidence in self.supporting_evidence
        ):
            raise ValueError(
                "supporting_evidence must contain InteractionEvidence objects."
            )
        evidence_by_id = {
            evidence.evidence_id: evidence for evidence in self.supporting_evidence
        }
        if len(evidence_by_id) != len(self.supporting_evidence):
            raise ValueError("supporting_evidence contains duplicate evidence IDs.")

        referenced: set[str] = set()
        for evidence in self.supporting_evidence:
            if evidence.host.genome_sha256 != self.target_host.genome_sha256:
                raise ValueError(
                    "supporting evidence names a different host genome."
                )
            if (
                evidence.host.profile_id is not None
                and evidence.host.profile_id != self.target_host.profile_id
            ):
                raise ValueError(
                    "supporting evidence names a different HostProfile."
                )
            if evidence.phage_profile_id not in member_ids:
                raise ValueError(
                    "supporting evidence targets a phage that is not a design member."
                )

        for member in self.members:
            for evidence_id in member.evidence_ids:
                evidence = evidence_by_id.get(evidence_id)
                if evidence is None:
                    raise ValueError(
                        f"member {member.phage_profile_id!r} references unknown evidence."
                    )
                if evidence.phage_profile_id != member.phage_profile_id:
                    raise ValueError(
                        f"member {member.phage_profile_id!r} references evidence "
                        "for a different phage."
                    )
                referenced.add(evidence_id)
        if referenced != set(evidence_by_id):
            raise ValueError(
                "every supporting evidence record must be referenced by a member."
            )

        if not self.objectives:
            raise ValueError("CocktailDesign requires at least one objective.")
        if any(not isinstance(item, DesignObjective) for item in self.objectives):
            raise ValueError("objectives must contain DesignObjective objects.")
        objective_names = [item.name for item in self.objectives]
        if len(set(objective_names)) != len(objective_names):
            raise ValueError("objective names must be unique.")

        _validate_text_tuple(self.assumptions, "assumption")
        _validate_text_tuple(self.unresolved_gaps, "unresolved gap")
        _require_text(self.rationale, "rationale")
        if not isinstance(self.designer, EvidenceProducer):
            raise ValueError("designer must be an EvidenceProducer.")
        _validate_timestamp(self.created_at, "created_at")

    @property
    def design_id(self) -> str:
        return f"{self.cocktail_id}:v{self.revision}"

    def _content_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "design_id": self.design_id,
            "cocktail_id": self.cocktail_id,
            "revision": self.revision,
            "target_host": self.target_host.to_dict(),
            "members": [member.to_dict() for member in self.members],
            "supporting_evidence": [
                evidence.to_dict() for evidence in self.supporting_evidence
            ],
            "objectives": [objective.to_dict() for objective in self.objectives],
            "assumptions": list(self.assumptions),
            "unresolved_gaps": list(self.unresolved_gaps),
            "rationale": self.rationale,
            "designer": self.designer.to_dict(),
            "created_at": self.created_at,
        }

    @property
    def content_sha256(self) -> str:
        canonical = json.dumps(
            self._content_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return sha256(canonical).hexdigest()

    def to_dict(self) -> dict:
        return {"content_sha256": self.content_sha256, **self._content_dict()}


def _host_reference_from_dict(data: dict) -> HostReference:
    if not isinstance(data, dict):
        raise ValueError("target_host must be an object.")
    allowed = {"genome_sha256", "profile_id"}
    if set(data) - allowed:
        raise ValueError("target_host contains unknown fields.")
    return HostReference(
        genome_sha256=data.get("genome_sha256"),
        profile_id=data.get("profile_id"),
    )


def _member_from_dict(data: dict) -> CocktailMember:
    if not isinstance(data, dict):
        raise ValueError("member must be an object.")
    required = {"phage_profile_id", "evidence_ids", "selection_context"}
    if set(data) != required:
        raise ValueError("member has missing or unknown fields.")
    evidence_ids = data["evidence_ids"]
    if not isinstance(evidence_ids, list):
        raise ValueError("member evidence_ids must be an array.")
    return CocktailMember(
        phage_profile_id=data["phage_profile_id"],
        evidence_ids=tuple(evidence_ids),
        selection_context=data["selection_context"],
    )


def _objective_from_dict(data: dict) -> DesignObjective:
    if not isinstance(data, dict) or set(data) != {"name", "rationale"}:
        raise ValueError("objective has missing or unknown fields.")
    return DesignObjective(name=data["name"], rationale=data["rationale"])


def _producer_from_dict(data: dict) -> EvidenceProducer:
    if not isinstance(data, dict) or set(data) != {
        "name",
        "version",
        "parameters",
    }:
        raise ValueError("designer has missing or unknown fields.")
    return EvidenceProducer(
        name=data["name"],
        version=data["version"],
        parameters=data["parameters"],
    )


def cocktail_design_from_dict(data: dict) -> CocktailDesign:
    """Validate and reconstruct a serialized CocktailDesign."""

    if not isinstance(data, dict):
        raise ValueError("CocktailDesign must be an object.")
    required = {
        "content_sha256",
        "schema_version",
        "design_id",
        "cocktail_id",
        "revision",
        "target_host",
        "members",
        "supporting_evidence",
        "objectives",
        "assumptions",
        "unresolved_gaps",
        "rationale",
        "designer",
        "created_at",
    }
    if set(data) != required:
        raise ValueError("CocktailDesign has missing or unknown fields.")
    for field in (
        "members",
        "supporting_evidence",
        "objectives",
        "assumptions",
        "unresolved_gaps",
    ):
        if not isinstance(data[field], list):
            raise ValueError(f"{field} must be an array.")

    design = CocktailDesign(
        schema_version=data["schema_version"],
        cocktail_id=data["cocktail_id"],
        revision=data["revision"],
        target_host=_host_reference_from_dict(data["target_host"]),
        members=tuple(_member_from_dict(item) for item in data["members"]),
        supporting_evidence=tuple(
            interaction_evidence_from_dict(item)
            for item in data["supporting_evidence"]
        ),
        objectives=tuple(
            _objective_from_dict(item) for item in data["objectives"]
        ),
        assumptions=tuple(data["assumptions"]),
        unresolved_gaps=tuple(data["unresolved_gaps"]),
        rationale=data["rationale"],
        designer=_producer_from_dict(data["designer"]),
        created_at=data["created_at"],
    )
    if data["design_id"] != design.design_id:
        raise ValueError("design_id does not match cocktail_id and revision.")
    if data["content_sha256"] != design.content_sha256:
        raise ValueError("content_sha256 does not match the design content.")
    return design


def phist_screening_design(
    host_profile: HostProfile,
    phage_profiles: list[PhageProfile],
    ranked_candidates: list[dict],
    *,
    cocktail_id: str,
    min_members: int = 2,
    max_members: int = 3,
    revision: int = 1,
    created_at: str | None = None,
) -> CocktailDesign:
    """Create a conservative screening design from PHIST evidence.

    This is intentionally not called an optimizer. It selects distinct phages
    with PHIST-reported signal in legacy cohort rank order, while explicitly
    recording the mechanistic and phenotype evidence that is still missing.
    """

    if not isinstance(host_profile, HostProfile):
        raise ValueError("host_profile must be a HostProfile.")
    if (
        type(min_members) is not int
        or type(max_members) is not int
        or not 2 <= min_members <= max_members
    ):
        raise ValueError(
            "PHIST screening design requires 2 <= min_members <= max_members."
        )
    if not ranked_candidates:
        raise ValueError("ranked_candidates must not be empty.")

    if any(not isinstance(profile, PhageProfile) for profile in phage_profiles):
        raise ValueError("phage_profiles must contain PhageProfile objects.")
    profiles = {profile.profile_id: profile for profile in phage_profiles}
    if len(profiles) != len(phage_profiles):
        raise ValueError("phage_profiles contains duplicate profile IDs.")

    eligible = []
    for candidate in ranked_candidates:
        if not isinstance(candidate, dict):
            raise ValueError("ranked candidate must be an object.")
        candidate_id = candidate.get("id")
        _require_text(candidate_id, "candidate id")
        profile_id = candidate.get("phage_profile_id") or f"{candidate_id}:v1"
        if profile_id not in profiles:
            raise ValueError(
                f"ranked candidate {candidate_id!r} has no matching PhageProfile."
            )
        if profiles[profile_id].provenance.kind == "engineered":
            continue
        ranking = candidate.get("ranking")
        if (
            not isinstance(ranking, dict)
            or ranking.get("tool") != "phist"
            or ranking.get("reported") is not True
            or type(ranking.get("rank")) is not int
            or ranking["rank"] < 1
        ):
            continue

        raw_evidence = candidate.get("interaction_evidence")
        if not isinstance(raw_evidence, list) or not raw_evidence:
            raise ValueError(
                f"ranked candidate {candidate_id!r} has no InteractionEvidence."
            )
        matching = []
        for raw in raw_evidence:
            evidence = interaction_evidence_from_dict(raw)
            if (
                evidence.producer.name == "phist"
                and evidence.kind == "computational"
                and evidence.phage_profile_id == profile_id
                and evidence.host.genome_sha256 == host_profile.genome.sha256
                and evidence.host.profile_id == host_profile.profile_id
                and evidence.result.get("status") == "reported_signal"
            ):
                matching.append(evidence)
        if not matching:
            raise ValueError(
                f"ranked candidate {candidate_id!r} has no matching PHIST "
                "InteractionEvidence for the target HostProfile."
            )
        eligible.append((ranking["rank"], profile_id, matching))

    ranks = [item[0] for item in eligible]
    if len(set(ranks)) != len(ranks):
        raise ValueError("PHIST screening candidates carry duplicate cohort ranks.")
    profile_ids = [item[1] for item in eligible]
    if len(set(profile_ids)) != len(profile_ids):
        raise ValueError("PHIST screening candidates repeat a PhageProfile.")

    eligible.sort(key=lambda item: (item[0], item[1]))
    if len(eligible) < min_members:
        raise ValueError(
            f"Only {len(eligible)} candidate(s) have PHIST-reported evidence; "
            f"at least {min_members} are required for this screening cocktail."
        )
    selected = eligible[:max_members]

    evidence_records = []
    members = []
    for rank, profile_id, evidence_list in selected:
        for evidence in evidence_list:
            if evidence.evidence_id not in {
                item.evidence_id for item in evidence_records
            }:
                evidence_records.append(evidence)
        members.append(
            CocktailMember(
                phage_profile_id=profile_id,
                evidence_ids=tuple(
                    evidence.evidence_id for evidence in evidence_list
                ),
                selection_context={"phist_rank": rank},
            )
        )

    return CocktailDesign(
        cocktail_id=cocktail_id,
        revision=revision,
        target_host=HostReference(
            genome_sha256=host_profile.genome.sha256,
            profile_id=host_profile.profile_id,
        ),
        members=tuple(members),
        supporting_evidence=tuple(evidence_records),
        objectives=(
            DesignObjective(
                name="experimental_screening",
                rationale=(
                    "Select multiple distinct phages with a PHIST-reported "
                    "computational signal for comparative experimental testing."
                ),
            ),
        ),
        assumptions=(
            "PHIST shared-kmer signal is used for prioritization only and is not "
            "treated as infection probability or susceptibility.",
            "The baseline excludes engineered PhageProfiles; retrieved provenance "
            "records source identity but does not itself prove natural biological origin.",
        ),
        unresolved_gaps=(
            "No physical susceptibility phenotype has yet been incorporated.",
            "No receptor/RBP complementarity evidence is available.",
            "No defense/counter-defense complementarity evidence is available.",
            "No cross-resistance evidence is available.",
            "No phage-phage antagonism or compatibility evidence is available.",
        ),
        rationale=(
            "Conservative baseline screening design. Members are chosen only "
            "from PHIST-reported candidates in cohort rank order; the design "
            "does not claim mechanistic complementarity or therapeutic efficacy."
        ),
        designer=EvidenceProducer(
            name="phist-screening-baseline",
            version="1.0",
            parameters={
                "min_members": min_members,
                "max_members": max_members,
                "eligible_candidates": len(eligible),
            },
        ),
        created_at=created_at or utc_now(),
    )


def write_cocktail_design(design: CocktailDesign, path: Path) -> None:
    """Atomically write one CocktailDesign JSON document."""

    if not isinstance(design, CocktailDesign):
        raise ValueError("design must be a CocktailDesign.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(design.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def load_cocktail_design(path: Path) -> CocktailDesign:
    """Load and validate one CocktailDesign JSON document."""

    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"CocktailDesign could not be loaded: {exc}") from None
    return cocktail_design_from_dict(data)

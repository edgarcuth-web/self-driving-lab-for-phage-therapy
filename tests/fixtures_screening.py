"""Shared software contract fixtures; never experimental evidence."""

"""Contract fixtures only: no biological probabilities or experimental results."""

from dataclasses import replace

from phage_lab.biology import GenomeSummary
from phage_lab.host_profile import new_host_profile
from phage_lab.host_state import new_host_state
from phage_lab.interaction_prediction import PredictionProducer, ProbabilityEstimate, evidence_only_unresolved_prediction, new_interaction_prediction
from phage_lab.natural_phage_recommender import recommend_natural_phages
from phage_lab.phage_profile import new_natural_phage_profile

T0 = "2026-01-01T00:00:00+00:00"
T1 = "2026-01-02T00:00:00+00:00"
T2 = "2026-01-03T00:00:00+00:00"
T3 = "2026-01-04T00:00:00+00:00"
UNKNOWN = ProbabilityEstimate(status="not_estimated")


def state():
    host = new_host_profile(
        "fixture-host", GenomeSummary(sha256="a" * 64, bases=100, contigs=1),
        created_at=T0,
    )
    return new_host_state(host, host_state_id="fixture-state", as_of=T1, created_at=T1)


def phage(name):
    return new_natural_phage_profile(
        name, collection_id="fixture-collection", isolate_id=name,
        recorded_at=T0, source_description="Contract fixture only.", created_at=T0,
    )


def prediction(profile, lower=None, point=0.8, upper=0.9, **changes):
    if lower is None:
        item = evidence_only_unresolved_prediction(
            state(), profile, [], prediction_id=f"prediction-{profile.phage_id}", predicted_at=T2,
        )
    else:
        item = new_interaction_prediction(
            state(), profile, [], prediction_id=f"prediction-{profile.phage_id}",
            adsorption=UNKNOWN,
            productive_infection=ProbabilityEstimate(
                status="estimated", probability=point, uncertainty_lower=lower,
                uncertainty_upper=upper, uncertainty_method="fixture-interval",
            ),
            resistance_emergence=UNKNOWN,
            mechanistic_explanation="Contract fixture only; no biological claim.",
            limitations=("Fixture output is not a calibrated biological model.",),
            producer=PredictionProducer(name="fixture-model", version="1"), predicted_at=T2,
        )
    return replace(item, **changes)


def recommend(profiles, predictions, **kwargs):
    return recommend_natural_phages(
        state(), profiles, predictions, candidate_set_id="fixture-candidates", created_at=T3,
        **kwargs,
    )

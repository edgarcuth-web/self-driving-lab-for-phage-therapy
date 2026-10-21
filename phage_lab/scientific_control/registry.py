"""Explicit registry of scientific modules trusted by control-plane code."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable

from ..model_contract import new_model_request
from ..natural_phage_recommender import recommend_natural_phages


NATURAL_PHAGE_RECOMMENDER_ID = "natural_phage_recommender"
NATURAL_PHAGE_RECOMMENDER_VERSION = "1"
MODEL_REQUEST_BUILDER_ID = "model_request_builder"
MODEL_REQUEST_BUILDER_VERSION = "1"


@dataclass(frozen=True)
class TrustedModule:
    module_id: str
    version: str
    call: Callable


TRUSTED_MODULES = MappingProxyType({
    NATURAL_PHAGE_RECOMMENDER_ID: TrustedModule(
        module_id=NATURAL_PHAGE_RECOMMENDER_ID,
        version=NATURAL_PHAGE_RECOMMENDER_VERSION,
        call=recommend_natural_phages,
    ),
    MODEL_REQUEST_BUILDER_ID: TrustedModule(
        module_id=MODEL_REQUEST_BUILDER_ID,
        version=MODEL_REQUEST_BUILDER_VERSION,
        call=new_model_request,
    ),
})

TRUSTED_MODULE_IDENTITIES = frozenset(
    (module.module_id, module.version) for module in TRUSTED_MODULES.values()
)

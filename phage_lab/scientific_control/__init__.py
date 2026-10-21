"""Scientific control: bounded orchestration and independent review.

This package deliberately has no dependency on workflow/device execution.
"""

from .contracts import (
    ArtifactReference,
    ModuleInvocation,
    ReviewFinding,
    ScientificClaim,
    ScientificObjective,
    ScientificProposal,
    ScientificReview,
)
from .orchestrator import ScientificOrchestrator
from .reviewer import ScientificReviewer

__all__ = [
    "ArtifactReference",
    "ModuleInvocation",
    "ReviewFinding",
    "ScientificClaim",
    "ScientificObjective",
    "ScientificOrchestrator",
    "ScientificProposal",
    "ScientificReview",
    "ScientificReviewer",
]

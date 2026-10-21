"""Scientific control: bounded orchestration and independent review.

This package deliberately has no dependency on workflow/device execution.
"""

from .contracts import (
    ArtifactReference,
    ModuleInvocation,
    ReviewFinding,
    ScientificClaim,
    ScientificObjective,
    ScientificPlan,
    ScientificProposal,
    ScientificReview,
    ScientificTask,
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
    "ScientificPlan",
    "ScientificProposal",
    "ScientificReview",
    "ScientificReviewer",
    "ScientificTask",
]

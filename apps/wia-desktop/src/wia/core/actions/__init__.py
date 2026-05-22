"""WIA Actions — rule-based suggesters that turn entries into next steps.

See :mod:`wia.core.actions.base` for the suggester contract and
:mod:`wia.core.actions.registry` for the orchestrator entry point.
"""

from wia.core.actions.base import ActionCandidate, Suggester, SuggesterContext
from wia.core.actions.registry import run_all

__all__ = ["ActionCandidate", "Suggester", "SuggesterContext", "run_all"]

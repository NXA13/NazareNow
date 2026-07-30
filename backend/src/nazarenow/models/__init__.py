"""Amplification Models.

One interface, per ADR 0001, so ADR 0006's Heuristic Baseline can be replaced by a
learned model in ticket #13 without the Decision Model, the API or the interface
changing. The baseline is not deleted when that happens — it stays as the benchmark.
"""

from .base import AmplificationModel, Condition, ConditionOutcome, Prediction
from .heuristic import HeuristicBaseline

__all__ = [
    "AmplificationModel",
    "Condition",
    "ConditionOutcome",
    "HeuristicBaseline",
    "Prediction",
]

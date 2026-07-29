"""The Amplification Model interface.

ADR 0001 splits the system in two: this layer predicts what the Nazaré Canyon does to
Offshore Conditions, and the Decision Model turns that prediction into advice. Keeping
them apart is what lets ADR 0006's Heuristic Baseline be swapped for a learned model in
ticket #13 without anything downstream changing.

ADR 0004 requires implementations to be cheap to evaluate: ticket #15 will run one
hundreds of times per forecast date to build a Predictive Distribution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Prediction:
    """What an Amplification Model expects at Praia do Norte.

    The quantity is **Significant Wave Height**, the Proxy Target of ADR 0002 — not Face
    Height. CONTEXT.md holds those apart because the canyon's famous threefold
    amplification describes the wave a person sees, not the instrument's measure of the
    sea. A model that multiplied Hs by a face-height factor would emit a confident,
    plausible, wrong number, which is this project's characteristic failure.
    """

    significant_wave_height: float
    unit: str = "m"

    matched: tuple[str, ...] = field(default_factory=tuple)
    """Conditions that held, in words a reader can check against the forecast."""

    unmatched: tuple[str, ...] = field(default_factory=tuple)
    """Conditions that did not. A verdict without these is not advice."""

    @property
    def matches_rule(self) -> bool:
        return not self.unmatched


class AmplificationModel(Protocol):
    """Offshore Conditions in, predicted conditions at Praia do Norte out."""

    name: str
    calibrated: bool
    """False until ticket #12 fits thresholds to Gold Days. Surfaced to the user rather
    than left implicit, so nobody mistakes a rule of thumb for a fitted model."""

    def predict(self, readings: dict[str, float]) -> Prediction: ...

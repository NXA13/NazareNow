"""The Amplification Model interface.

ADR 0001 splits the system in two: this layer predicts what the Nazaré Canyon does to
Offshore Conditions, and the Decision Model turns that prediction into advice. Keeping
them apart is what lets ADR 0006's Heuristic Baseline be swapped for a learned model in
ticket #13 without anything downstream changing.

ADR 0004 requires implementations to be cheap to evaluate: ticket #15 will run one
hundreds of times per forecast date to build a Predictive Distribution.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class Condition(StrEnum):
    """The conditions an Amplification Model reports a verdict on.

    Identities, not prose. The Decision Model needs to ask whether the *swell* conditions
    hold without caring how a model worded them — ADR 0003 keeps a Watch looser than a Go
    Call, and that distinction cannot rest on substring-matching display strings. It did
    once: rewording a message silently moved a day between tiers, and any implementation
    of `AmplificationModel` that phrased its failures differently made every day a Watch.

    The values are the words the interface uses, so a reason string and its identity stay
    recognisably the same thing to a reader comparing them.
    """

    SIGNIFICANT_WAVE_HEIGHT = "significant wave height"
    SWELL_PERIOD = "swell period"
    SWELL_DIRECTION = "swell direction"
    WIND = "wind"

    SWELL_PERIOD_FOR_GO_CALL = "swell period for a go call"
    """The same measurement as `SWELL_PERIOD`, judged against the stricter of the two bars.

    Ticket #12 gives the tiers different minimum swell periods, because #11 measured that
    period is the only condition that ever blocks a Gold Day — so it is the only place a
    recall tier and a precision tier can genuinely differ. A model reports both verdicts
    and the Decision Model requires whichever its tier calls for; the alternative, passing
    a tier down into the model, would make the Amplification Model layer aware of a
    distinction ADR 0001 keeps on the other side of the seam.

    Two verdicts on one measurement is also what lets the interface say *why* a day is a
    Watch rather than a Go Call, in the same sentence the user already reads."""


@dataclass(frozen=True)
class ConditionOutcome:
    """One condition's verdict, and the sentence explaining it to a reader."""

    condition: Condition
    holds: bool
    explanation: str
    """In words a reader can check against the forecast — a verdict without these is not
    advice. Display only: nothing may branch on this string."""


@dataclass(frozen=True)
class Prediction:
    """What an Amplification Model expects the sea to do.

    The quantity is **Significant Wave Height**, the Proxy Target of ADR 0002 — not Face
    Height. CONTEXT.md holds those apart because the canyon's famous threefold
    amplification describes the wave a person sees, not the instrument's measure of the
    sea. A model that multiplied Hs by a face-height factor would emit a confident,
    plausible, wrong number, which is this project's characteristic failure.

    The interface deliberately does not fix *where* the number stands, because no shipped
    implementation stands at the beach: the Heuristic Baseline carries the offshore
    forecast through unchanged, and #13's learned model predicts the Proxy Target at
    Monican02, 15 km offshore. Each says so itself. This docstring named Praia do Norte
    until #13, which was harmless only while every implementation returned its input —
    once a model earned a number of its own, the same sentence became the place-conflation
    the whole layer exists to prevent.
    """

    significant_wave_height: float
    unit: str = "m"

    conditions: tuple[ConditionOutcome, ...] = ()
    """Every condition the model judged, held or not."""

    @property
    def matched(self) -> tuple[str, ...]:
        return tuple(outcome.explanation for outcome in self.conditions if outcome.holds)

    @property
    def unmatched(self) -> tuple[str, ...]:
        return tuple(outcome.explanation for outcome in self.conditions if not outcome.holds)

    @property
    def matches_rule(self) -> bool:
        """Every condition judged, and all of them held.

        A prediction that judged nothing does not match the rule. Reading this as "no
        failures" meant a model reporting no conditions at all earned a Go Call — advice
        to book a flight, from silence.
        """
        return bool(self.conditions) and all(outcome.holds for outcome in self.conditions)

    def holds(self, *conditions: Condition) -> bool:
        """Whether every named condition was judged and held.

        A condition the model never judged does not hold. The alternative — treating
        absence as success — turns an unfamiliar model's silence into a call.
        """
        held = {outcome.condition for outcome in self.conditions if outcome.holds}
        return set(conditions) <= held


class AmplificationModel(Protocol):
    """Offshore Conditions in, a predicted Significant Wave Height out.

    Not conditions at Praia do Norte — see `Prediction` for where the number actually
    stands, which differs by implementation and is not yet the beach.
    """

    name: str
    calibrated: bool
    """Whether the thresholds behind this model were fitted to Gold Days (#12) or are a
    rule of thumb. Surfaced to the user rather than left implicit, so nobody mistakes an
    unfitted model for a fitted one — and read from the threshold set's own provenance, so
    it cannot be asserted by a model whose numbers came from nowhere."""

    def predict(self, readings: dict[str, float]) -> Prediction: ...

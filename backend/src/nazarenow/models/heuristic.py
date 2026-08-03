"""The Heuristic Baseline: the rule of thumb, now with thresholds fitted to Gold Days.

Per ADR 0006 this ships first and stays permanently. It is the number every learned
model has to beat, and reporting a learned model's accuracy without it would be
meaningless — 0.87 says nothing until you know what guessing well scores.

It contains no machine learning. What ticket #12 changed is where its numbers come from:
they are no longer written in this file. `thresholds.py` loads them from data carrying the
provenance of the fit that produced them, and `analysis/calibration/` is the fit. The rule
is still the rule; it is the constants that stopped being guesses.

**The shape of the rule has changed twice.** The model reports two verdicts on swell period
— one against the Watch bar, one against the stricter Go Call bar — because #11's backtest
found period was the only condition that ever blocked a Gold Day, and therefore the only
place ADR 0003's recall tier and precision tier can actually differ. See
`Condition.SWELL_PERIOD_FOR_GO_CALL`.

And per **ADR 0009**, the wind condition is a disjunction rather than a conjunction: wind
light enough not to matter, *or* offshore and within the cap. That claim about period being
the only binding condition was measured on six Gold Days; #39 re-ran it against 25 and found
the wind condition rejecting six documented XXL Days on breezes of 4-16 km/h, blocked by the
offshore arc rather than by the speed. A wind too light to raise a ripple cannot wreck a wave
face whichever way it blows, and the rule now says so.
"""

from __future__ import annotations

from nazarenow.thresholds import Thresholds, load

from .base import Condition, ConditionOutcome, Prediction


def _within(value: float, arc: tuple[float, float]) -> bool:
    """Whether a bearing falls inside an arc, inclusive of both ends.

    Raises on an arc that wraps past north. Neither calibrated arc does, and silently
    returning False for every bearing — which a naive comparison does — would be a
    plausible-looking lie. `thresholds.parse` rejects such an arc on load, so this is the
    second of two guards: this one also covers a model constructed directly in a test.
    """
    low, high = arc
    if low > high:
        raise ValueError(
            f"arc {arc} wraps past north, which this comparison cannot express; "
            "split it into two arcs rather than letting it match nothing"
        )
    return low <= value <= high


class HeuristicBaseline:
    """Applies the rule of thumb. Deterministic, and cheap enough for ticket #15."""

    name = "heuristic-baseline"

    def __init__(self, thresholds: Thresholds | None = None) -> None:
        """Takes its numbers, rather than reading them from module scope.

        The parameter is what lets `analysis/calibration/` sweep candidate thresholds
        against the real class instead of a copy of it. The sweep used to work by
        reassigning a module constant, which mutated global state for the duration of the
        loop and left every concurrent reader of the model looking at whichever value the
        sweep happened to be on.
        """
        self.thresholds = thresholds if thresholds is not None else load()

    @property
    def calibrated(self) -> bool:
        """Read off the thresholds' provenance, never asserted independently.

        A model that could set this itself could claim a calibration its numbers do not
        have, and `calibrated` is the flag the interface uses to decide whether to warn
        the user that the calls are a rule of thumb.
        """
        return self.thresholds.calibrated

    def predict(self, readings: dict[str, float]) -> Prediction:
        # ADR 0006 defines the rule of thumb on Significant Wave Height, and CONTEXT.md
        # lists "swell height" under that term's avoided synonyms because they are
        # different variables. Reading swell height here and reporting it as Hs conflated
        # exactly the two quantities this project holds apart.
        significant_wave_height = readings["significant_wave_height"]
        period = readings["swell_period"]
        direction = readings["swell_direction"]
        wind_speed = readings["wind_speed"]
        wind_direction = readings["wind_direction"]

        limits = self.thresholds
        height_bar = limits.minimum_significant_wave_height_m
        watch_bar = limits.watch_minimum_swell_period_s
        go_bar = limits.go_call_minimum_swell_period_s

        # Each condition carries its identity alongside its sentence. The Decision Model
        # branches on the identity; only the interface reads the sentence.
        conditions = tuple(
            ConditionOutcome(condition, holds, held if holds else failed)
            for condition, holds, held, failed in (
                (
                    Condition.SIGNIFICANT_WAVE_HEIGHT,
                    significant_wave_height >= height_bar,
                    f"significant wave height {significant_wave_height:g}m is at or above "
                    f"{height_bar:g}m",
                    f"significant wave height {significant_wave_height:g}m is below "
                    f"{height_bar:g}m",
                ),
                (
                    Condition.SWELL_PERIOD,
                    period >= watch_bar,
                    f"swell period {period:g}s is at or above the {watch_bar:g}s a Watch needs",
                    f"swell period {period:g}s is below the {watch_bar:g}s a Watch needs",
                ),
                (
                    # Deliberately worded so that a day clearing the Watch bar and failing
                    # this one reads as an explanation of its own tier rather than as a
                    # contradiction of the line above it.
                    Condition.SWELL_PERIOD_FOR_GO_CALL,
                    period >= go_bar,
                    f"swell period {period:g}s is at or above the {go_bar:g}s a Go Call needs",
                    f"swell period {period:g}s is below the {go_bar:g}s a Go Call needs",
                ),
                (
                    Condition.SWELL_DIRECTION,
                    _within(direction, limits.swell_arc),
                    f"swell direction {direction:g}° is within the canyon's arc",
                    f"swell direction {direction:g}° is outside the canyon's arc",
                ),
                (
                    # A disjunction since ADR 0009: wind light enough not to matter, OR
                    # offshore and within the cap. Written as a conjunction this rejected six
                    # documented Gold Days on 4-16 km/h breezes that happened to blow from
                    # the wrong quarter — the condition claimed they were unsurfable.
                    Condition.WIND,
                    wind_speed <= limits.light_wind_exemption_kmh
                    or (
                        _within(wind_direction, limits.offshore_wind_arc)
                        and wind_speed <= limits.maximum_wind_speed_kmh
                    ),
                    self._wind_held(wind_speed),
                    self._wind_fault(wind_speed, wind_direction),
                ),
            )
        )

        return Prediction(
            # Deliberately the forecast's own swell height, not a multiple of it. The
            # canyon's threefold amplification applies to Face Height, a different
            # quantity from the Significant Wave Height predicted here, and inventing a
            # factor would produce a plausible number with nothing behind it. A learned
            # model in ticket #13 is what earns the right to predict a different value —
            # and this baseline is the floor it must clear.
            significant_wave_height=significant_wave_height,
            conditions=conditions,
        )

    def _wind_held(self, speed: float) -> str:
        """Which of the two ways the condition held.

        They are not the same statement to a user. "Too light to matter" describes a glassy
        morning with no wind worth naming; "offshore and light" describes a wind that is
        actively grooming the face. Collapsing both into one sentence would tell somebody
        deciding whether to fly to Portugal that the wind was favourable when in fact it was
        merely absent.
        """
        if speed <= self.thresholds.light_wind_exemption_kmh:
            return f"wind is too light to matter at {speed:g} km/h"
        return f"wind is offshore and light at {speed:g} km/h"

    def _wind_fault(self, speed: float, direction: float) -> str:
        """Why the condition failed, following the disjunction it now reports on.

        A day failing on direction is only failing *because* it was too windy to be exempt,
        and saying "onshore" without that leaves a reader wondering why a 20 km/h breeze was
        judged differently from the 12 km/h one an hour earlier.
        """
        exemption = self.thresholds.light_wind_exemption_kmh
        if not _within(direction, self.thresholds.offshore_wind_arc):
            return (
                f"wind direction {direction:g}° is onshore and {speed:g} km/h is above the "
                f"{exemption:g} km/h that would make direction irrelevant"
            )
        return f"wind speed {speed:g} km/h is above {self.thresholds.maximum_wind_speed_kmh:g} km/h"

"""The Heuristic Baseline: the rule of thumb, now with thresholds fitted to Gold Days.

Per ADR 0006 this ships first and stays permanently. It is the number every learned
model has to beat, and reporting a learned model's accuracy without it would be
meaningless — 0.87 says nothing until you know what guessing well scores.

It contains no machine learning. What ticket #12 changed is where its numbers come from:
they are no longer written in this file. `thresholds.py` loads them from data carrying the
provenance of the fit that produced them, and `analysis/calibration/` is the fit. The rule
is still the rule; it is the constants that stopped being guesses.

**The shape of the rule is unchanged, with one addition.** The model now reports two
verdicts on swell period — one against the Watch bar, one against the stricter Go Call bar
— because #11's backtest found period is the only condition that ever blocks a Gold Day,
and therefore the only place ADR 0003's recall tier and precision tier can actually differ.
See `Condition.SWELL_PERIOD_FOR_GO_CALL`.
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
                    Condition.WIND,
                    _within(wind_direction, limits.offshore_wind_arc)
                    and wind_speed <= limits.maximum_wind_speed_kmh,
                    f"wind is offshore and light at {wind_speed:g} km/h",
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

    def _wind_fault(self, speed: float, direction: float) -> str:
        if not _within(direction, self.thresholds.offshore_wind_arc):
            return f"wind direction {direction:g}° is onshore"
        return f"wind speed {speed:g} km/h is above {self.thresholds.maximum_wind_speed_kmh:g} km/h"

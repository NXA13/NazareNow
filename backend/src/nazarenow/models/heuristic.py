"""The Heuristic Baseline: the surf community's rule of thumb, as code.

Per ADR 0006 this ships first and stays permanently. It is the number every learned
model has to beat, and reporting a learned model's accuracy without it would be
meaningless — 0.87 says nothing until you know what guessing well scores.

It contains no machine learning and is deliberately weak. Its job is to be a floor.
"""

from __future__ import annotations

from .base import Condition, ConditionOutcome, Prediction

# Thresholds from the surf community's rule of thumb for Praia do Norte: a large swell,
# a long period, arriving from the west-north-west, with light offshore wind. Ticket #12
# replaces these with values calibrated against Gold Days; until then they are a
# starting point and the interface says so.
MINIMUM_WAVE_HEIGHT_M = 3.0
MINIMUM_SWELL_PERIOD_S = 14.0
SWELL_ARC = (255.0, 330.0)
"""West-south-west through north-north-west. The canyon is fed from this arc."""

OFFSHORE_WIND_ARC = (20.0, 180.0)
"""Praia do Norte faces west, so wind blowing off the land arrives from the eastern half
of the compass — north-north-east round through south. The previous arc of 45-200
accepted 199 degrees, which has an onshore component, and rejected the north-easterlies
that are among the cleanest winds the spot gets: real data showed wind from 15 degrees
reported to users as onshore."""

MAXIMUM_WIND_SPEED_KMH = 35.0


def _within(value: float, arc: tuple[float, float]) -> bool:
    """Whether a bearing falls inside an arc, inclusive of both ends.

    Raises on an arc that wraps past north. Neither shipped arc does, and silently
    returning False for every bearing — which a naive comparison does — would be a
    plausible-looking lie waiting for ticket #12 to recalibrate into existence.
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
    calibrated = False

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

        # Each condition carries its identity alongside its sentence. The Decision Model
        # branches on the identity; only the interface reads the sentence.
        conditions = tuple(
            ConditionOutcome(condition, holds, held if holds else failed)
            for condition, holds, held, failed in (
                (
                    Condition.SIGNIFICANT_WAVE_HEIGHT,
                    significant_wave_height >= MINIMUM_WAVE_HEIGHT_M,
                    f"significant wave height {significant_wave_height:g}m is at or above "
                    f"{MINIMUM_WAVE_HEIGHT_M:g}m",
                    f"significant wave height {significant_wave_height:g}m is below "
                    f"{MINIMUM_WAVE_HEIGHT_M:g}m",
                ),
                (
                    Condition.SWELL_PERIOD,
                    period >= MINIMUM_SWELL_PERIOD_S,
                    f"swell period {period:g}s is at or above {MINIMUM_SWELL_PERIOD_S:g}s",
                    f"swell period {period:g}s is below {MINIMUM_SWELL_PERIOD_S:g}s",
                ),
                (
                    Condition.SWELL_DIRECTION,
                    _within(direction, SWELL_ARC),
                    f"swell direction {direction:g}° is within the canyon's arc",
                    f"swell direction {direction:g}° is outside the canyon's arc",
                ),
                (
                    Condition.WIND,
                    _within(wind_direction, OFFSHORE_WIND_ARC)
                    and wind_speed <= MAXIMUM_WIND_SPEED_KMH,
                    f"wind is offshore and light at {wind_speed:g} km/h",
                    _wind_fault(wind_speed, wind_direction),
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


def _wind_fault(speed: float, direction: float) -> str:
    if not _within(direction, OFFSHORE_WIND_ARC):
        return f"wind direction {direction:g}° is onshore"
    return f"wind speed {speed:g} km/h is above {MAXIMUM_WIND_SPEED_KMH:g} km/h"

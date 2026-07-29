"""The Heuristic Baseline: the surf community's rule of thumb, as code.

Per ADR 0006 this ships first and stays permanently. It is the number every learned
model has to beat, and reporting a learned model's accuracy without it would be
meaningless — 0.87 says nothing until you know what guessing well scores.

It contains no machine learning and is deliberately weak. Its job is to be a floor.
"""

from __future__ import annotations

from .base import Prediction

# Thresholds from the surf community's rule of thumb for Praia do Norte: a large swell,
# a long period, arriving from the west-north-west, with light offshore wind. Ticket #12
# replaces these with values calibrated against Gold Days; until then they are a
# starting point and the interface says so.
MINIMUM_SWELL_HEIGHT_M = 3.0
MINIMUM_SWELL_PERIOD_S = 14.0
SWELL_ARC = (255.0, 330.0)
"""West-south-west through north-north-west. The canyon is fed from this arc."""

OFFSHORE_WIND_ARC = (45.0, 200.0)
"""Praia do Norte faces west, so wind blowing off the land arrives from the eastern
half of the compass. Onshore wind pulls the face apart regardless of swell size."""

MAXIMUM_WIND_SPEED_KMH = 35.0


def _within(value: float, arc: tuple[float, float]) -> bool:
    low, high = arc
    return low <= value <= high


class HeuristicBaseline:
    """Applies the rule of thumb. Deterministic, and cheap enough for ticket #15."""

    name = "heuristic-baseline"
    calibrated = False

    def predict(self, readings: dict[str, float]) -> Prediction:
        matched: list[str] = []
        unmatched: list[str] = []

        height = readings["swell_height"]
        period = readings["swell_period"]
        direction = readings["swell_direction"]
        wind_speed = readings["wind_speed"]
        wind_direction = readings["wind_direction"]

        for holds, held, failed in (
            (
                height >= MINIMUM_SWELL_HEIGHT_M,
                f"swell height {height:g}m is at or above {MINIMUM_SWELL_HEIGHT_M:g}m",
                f"swell height {height:g}m is below {MINIMUM_SWELL_HEIGHT_M:g}m",
            ),
            (
                period >= MINIMUM_SWELL_PERIOD_S,
                f"swell period {period:g}s is at or above {MINIMUM_SWELL_PERIOD_S:g}s",
                f"swell period {period:g}s is below {MINIMUM_SWELL_PERIOD_S:g}s",
            ),
            (
                _within(direction, SWELL_ARC),
                f"swell direction {direction:g}° is within the canyon's arc",
                f"swell direction {direction:g}° is outside the canyon's arc",
            ),
            (
                _within(wind_direction, OFFSHORE_WIND_ARC) and wind_speed <= MAXIMUM_WIND_SPEED_KMH,
                f"wind is offshore and light at {wind_speed:g} km/h",
                _wind_fault(wind_speed, wind_direction),
            ),
        ):
            (matched if holds else unmatched).append(held if holds else failed)

        return Prediction(
            # Deliberately the forecast's own swell height, not a multiple of it. The
            # canyon's threefold amplification applies to Face Height, a different
            # quantity from the Significant Wave Height predicted here, and inventing a
            # factor would produce a plausible number with nothing behind it. A learned
            # model in ticket #13 is what earns the right to predict a different value —
            # and this baseline is the floor it must clear.
            significant_wave_height=height,
            matched=tuple(matched),
            unmatched=tuple(unmatched),
        )


def _wind_fault(speed: float, direction: float) -> str:
    if not _within(direction, OFFSHORE_WIND_ARC):
        return f"wind direction {direction:g}° is onshore"
    return f"wind speed {speed:g} km/h is above {MAXIMUM_WIND_SPEED_KMH:g} km/h"

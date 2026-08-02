"""The calibrated thresholds, and where they come from.

Ticket #12. Until it, the numbers the Heuristic Baseline compares against were module
constants written from the surf community's rule of thumb — fitted to nothing, and
changeable only by editing code and redeploying. Both halves of that were problems: ADR
0006 requires an accuracy figure to name what produced it, and a threshold that needs a
release to change is a threshold nobody recalibrates.

So thresholds are **data**, loaded at startup from a JSON file, carrying the provenance of
the calibration that produced them. `analysis/calibration/` writes that file; nothing here
fits anything. The two are deliberately separate: fitting needs the Hindcast and fifteen
years of it, and the running system should not be able to reach for either.

**Per-tier swell period is the point of the shape.** ADR 0003 makes a Watch
recall-optimised and a Go Call precision-optimised, and #11's backtest found the shipped
rule delivered neither — the two tiers differed only by the wind condition, wind never
blocked a Gold Day, and so both tiers caught exactly the same three days. A Watch that
cannot see anything a Go Call misses is one rule with two names. The tiers now differ where
the backtest showed the decision actually lives: the minimum swell period.

The file is validated on load rather than trusted. A threshold set is the kind of
configuration whose corruption produces confident wrong advice instead of a crash — a Go
Call bar looser than the Watch bar inverts the tiers while every field still parses as a
float.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path(__file__).resolve().parent / "thresholds.json"
"""The calibration this release ships with, versioned alongside the code that reads it."""

PATH_VARIABLE = "NAZARENOW_THRESHOLDS"
"""Points at a different file, so recalibrating does not mean redeploying (#12).

Follows `NAZARENOW_DB`: the same idiom, for the same reason — the running system reads its
configuration from the environment, and the default is what the repository ships.
"""


class ThresholdsUnusable(ValueError):
    """The threshold file is missing, unparseable, or describes an incoherent rule.

    Raised rather than falling back to a built-in default. A fallback would let a
    misconfigured deployment issue calls from thresholds nobody chose, and — because the
    calls would look entirely normal — nothing downstream would reveal it. ADR 0006's
    requirement that an accuracy figure name what produced it is not satisfiable by a
    system that silently substitutes its own numbers.
    """


@dataclass(frozen=True)
class Calibration:
    """What a threshold set rests on, carried with it.

    Every field is here so the interface can state the calibration's limits rather than
    implying it has none — criterion of #12, and the reason `gold_days_fitted` is exposed
    at all. Nine Gold Days is a small number and the user is told it.
    """

    fitted_on: str
    """The span the thresholds were fitted on, as a reader would name it."""

    validated_on: str
    """The held-out span. Disjoint from `fitted_on`, checked on load."""

    gold_days_fitted: int
    gold_days_validated: int

    method: str
    """One line on how the values were chosen, for someone reading the API response."""

    source: str
    """The path in this repository that regenerates the file."""

    fitted_at: str
    """The date the fit was run, so a stale calibration is visible as one."""

    @property
    def gold_days_total(self) -> int:
        return self.gold_days_fitted + self.gold_days_validated


@dataclass(frozen=True)
class Thresholds:
    """The numbers the rule compares against, per tier where the tier matters.

    Height, swell direction and wind are shared across tiers. #11's backtest measured that
    none of the three blocked a single missed Gold Day, so splitting them per tier would
    fit parameters the evidence cannot distinguish — nine Gold Days does not support four
    thresholds in two variants, and the extra freedom would be spent on noise.
    """

    minimum_significant_wave_height_m: float
    watch_minimum_swell_period_s: float
    go_call_minimum_swell_period_s: float
    swell_arc: tuple[float, float]
    offshore_wind_arc: tuple[float, float]
    maximum_wind_speed_kmh: float
    calibration: Calibration | None
    """`None` for an uncalibrated set. The API reports `calibrated` from this, so the
    interface cannot claim a fit that did not happen."""

    @property
    def calibrated(self) -> bool:
        return self.calibration is not None


def _arc(raw: Any, field: str) -> tuple[float, float]:
    """A two-bearing arc, checked for the shape `_within` can actually express.

    `heuristic._within` raises on an arc that wraps past north, because a naive comparison
    silently matches nothing. Catching it here means a bad arc fails at startup with the
    field name attached, rather than on the first hour of the first forecast that reaches
    it.
    """
    if not isinstance(raw, list) or len(raw) != 2:
        raise ThresholdsUnusable(f"{field} must be a list of two bearings, got {raw!r}")
    try:
        low, high = float(raw[0]), float(raw[1])
    except (TypeError, ValueError) as error:
        raise ThresholdsUnusable(f"{field} must hold two numbers, got {raw!r}") from error
    if not 0.0 <= low <= 360.0 or not 0.0 <= high <= 360.0:
        raise ThresholdsUnusable(f"{field} bearings must lie between 0 and 360, got {raw!r}")
    if low >= high:
        raise ThresholdsUnusable(
            f"{field} is {raw!r}, which does not open eastward; an arc that wraps past north "
            "cannot be expressed as one pair and would match no bearing at all"
        )
    return low, high


def _number(body: dict[str, Any], field: str) -> float:
    if field not in body:
        raise ThresholdsUnusable(f"missing required threshold {field!r}")
    try:
        return float(body[field])
    except (TypeError, ValueError) as error:
        raise ThresholdsUnusable(f"{field} must be a number, got {body[field]!r}") from error


def _calibration(raw: Any) -> Calibration | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ThresholdsUnusable(f"calibration must be an object or null, got {raw!r}")

    fields = (
        "fitted_on",
        "validated_on",
        "gold_days_fitted",
        "gold_days_validated",
        "method",
        "source",
        "fitted_at",
    )
    missing = [field for field in fields if field not in raw]
    if missing:
        raise ThresholdsUnusable(
            f"calibration is present but incomplete, missing {missing}; a partial provenance "
            "would let the interface claim a fit it cannot describe"
        )

    if raw["fitted_on"] == raw["validated_on"]:
        raise ThresholdsUnusable(
            f"calibration was fitted and validated on the same span ({raw['fitted_on']!r}); "
            "that is an in-sample score reported as a held-out one"
        )
    for field in ("gold_days_fitted", "gold_days_validated"):
        if not isinstance(raw[field], int) or raw[field] <= 0:
            raise ThresholdsUnusable(f"calibration {field} must be a positive whole number")

    return Calibration(
        fitted_on=str(raw["fitted_on"]),
        validated_on=str(raw["validated_on"]),
        gold_days_fitted=raw["gold_days_fitted"],
        gold_days_validated=raw["gold_days_validated"],
        method=str(raw["method"]),
        source=str(raw["source"]),
        fitted_at=str(raw["fitted_at"]),
    )


def parse(body: dict[str, Any]) -> Thresholds:
    """Build a threshold set from a parsed file, refusing an incoherent one.

    Every check here describes a file that parses cleanly and means something wrong. A
    schema check alone would pass all of them.
    """
    if not isinstance(body, dict):
        raise ThresholdsUnusable(
            f"the threshold file must hold an object, got {type(body).__name__}"
        )

    height = _number(body, "minimum_significant_wave_height_m")
    watch_period = _number(body, "watch_minimum_swell_period_s")
    go_period = _number(body, "go_call_minimum_swell_period_s")
    wind_speed = _number(body, "maximum_wind_speed_kmh")

    for name, value in (
        ("minimum_significant_wave_height_m", height),
        ("watch_minimum_swell_period_s", watch_period),
        ("go_call_minimum_swell_period_s", go_period),
        ("maximum_wind_speed_kmh", wind_speed),
    ):
        if value <= 0:
            raise ThresholdsUnusable(f"{name} must be positive, got {value}")

    # The check this file exists for. ADR 0003 has a Watch reach further than a Go Call;
    # a Go bar at or below the Watch bar makes the Watch tier unreachable — every day
    # clearing it clears the Go bar too — which is precisely the collapse #11 measured and
    # #12 exists to undo. Every field would still be a valid float.
    if go_period <= watch_period:
        raise ThresholdsUnusable(
            f"the Go Call swell period bar ({go_period}s) is not above the Watch bar "
            f"({watch_period}s), so no day could ever earn a Watch without also earning a Go "
            "Call; ADR 0003 requires the recall tier to reach further than the precision tier"
        )

    return Thresholds(
        minimum_significant_wave_height_m=height,
        watch_minimum_swell_period_s=watch_period,
        go_call_minimum_swell_period_s=go_period,
        swell_arc=_arc(body.get("swell_arc"), "swell_arc"),
        offshore_wind_arc=_arc(body.get("offshore_wind_arc"), "offshore_wind_arc"),
        maximum_wind_speed_kmh=wind_speed,
        calibration=_calibration(body.get("calibration")),
    )


def load(path: str | Path | None = None) -> Thresholds:
    """Read a threshold set from disk.

    Resolution order: the argument, then `NAZARENOW_THRESHOLDS`, then the file this
    release ships. A missing file raises rather than defaulting, for the reason
    `ThresholdsUnusable` documents.
    """
    resolved = Path(path or os.environ.get(PATH_VARIABLE) or DEFAULT_PATH)
    try:
        text = resolved.read_text(encoding="utf-8")
    except OSError as error:
        raise ThresholdsUnusable(
            f"cannot read thresholds from {resolved}: {error}. Set {PATH_VARIABLE} to a "
            "calibration file, or run analysis/calibration/calibrate.py to regenerate the default"
        ) from error

    try:
        body = json.loads(text)
    except json.JSONDecodeError as error:
        raise ThresholdsUnusable(f"{resolved} is not valid JSON: {error}") from error

    return parse(body)

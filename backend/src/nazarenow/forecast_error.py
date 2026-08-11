"""The measured Forecast Error Profile, and where it stops.

Ticket #15. ADR 0004 separates two things that would otherwise be learned together: the
Amplification Model learns the canyon's physics from clean Hindcast inputs, and forecast
unreliability is characterised separately from Open-Meteo's Previous Runs archive. At serving
time the incoming forecast is perturbed by that profile and the model is evaluated many times,
so what reaches a user is a range rather than a point estimate.

#14 measured the profile and shipped it as `forecast_error.json`; this reads it. The same
idiom as `thresholds.py` and for the same reason — measured against archives the running
system cannot reach, shipped as data, validated on load rather than trusted.

**This file is one term of three, and the smallest one where a Go Call is issued.** At one
day's Lead Time drift is 0.095 m against a 0.130 m Translation residual and a 0.356 m
Amplification error. A caller that treated this as the whole uncertainty would build a
distribution roughly three times too narrow exactly where a person books a flight, which is
why the file carries `only_term` and why a file without it is refused.

**Absence is a value here, not an error.** The archive begins 2025-11-16 and reaches seven
days; beyond that nothing is measured and `at()` answers `None`. The tempting fallback — reuse
the widest measured band — would quietly claim seven days of evidence about an eighth day the
archive says nothing about. ADR 0004 requires far-out dates to be *visibly* more cautious, and
a caller that must handle `None` cannot forget to be.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_PATH = Path(__file__).resolve().parent / "forecast_error.json"
"""The profile this release ships with, versioned alongside the code that reads it."""

PATH_VARIABLE = "NAZARENOW_FORECAST_ERROR"
"""Points at a different file, so re-measuring the profile does not mean redeploying.

Follows `NAZARENOW_THRESHOLDS` and `NAZARENOW_DB`: same idiom, same reason.
"""


class ForecastErrorUnusable(ValueError):
    """The profile is missing, unparseable, or describes a width that means nothing.

    Raised rather than falling back to a built-in default. A fallback would let a
    misconfigured deployment publish confident-looking ranges nobody measured — and unlike a
    wrong threshold, a wrong *width* does not look wrong to a reader. It reads as certainty.
    """


@dataclass(frozen=True)
class Band:
    """How far the forecast drifts, over one regime of sea at one Lead Time.

    Two regimes are measured separately because they differ by roughly half again: at seven
    days the all-hours drift is 0.518 m and the big-swell drift 0.717 m. Applying the
    all-hours figure to a big swell would understate the uncertainty on precisely the days
    this project exists to call.
    """

    drift: float
    """The part of the error a constant correction cannot remove.

    Exported rather than `rmse` by #14: bias share is under 1% at every Lead Time so the two
    are nearly equal today, and this is the field that stays correct if that stops being true.

    Called `drift` and not `noise` since #65; the JSON key moved with it, so a profile written
    before then is refused rather than read. ADR 0013 has the reasoning.
    """

    bias: float
    """Signed drift. Not a correction to apply blindly — see `ForecastError.only_term`.

    At seven days on big swell this is -0.230 m: the forecast under-reads a big swell that
    far out, against the provider's own settled analysis. ADR 0004 assumed the profile would
    be injected symmetrically and its amendment records that it cannot be.
    """

    p5: float
    p95: float
    """The measured 5th and 95th percentiles of the drift, for a caller that wants the
    observed shape rather than a Gaussian assumption about it."""

    hours: int
    """How many archived hours the band rests on, so a thin one is visible as thin."""


@dataclass(frozen=True)
class LeadTime:
    """The two bands measured at one Lead Time, and the bar that chooses between them."""

    lead_time_days: int
    all_hours: Band
    big_swell: Band
    big_swell_m: float

    def for_sea(self, significant_wave_height_m: float) -> Band:
        """The band that applies to a sea of this size.

        `>=` at the bar, matching every other 3 m bar in the project — `train.py`'s
        `BIG_SWELL_M`, `measure.FITTINGS`, and #14's own split all include the boundary.
        """
        if significant_wave_height_m >= self.big_swell_m:
            return self.big_swell
        return self.all_hours


@dataclass(frozen=True)
class ForecastError:
    """The whole profile, and the honest edge of it."""

    quantity: str
    reference: str
    measured_through_lead_days: int

    only_term: str
    """What this profile is *not*: the whole uncertainty.

    Carried out of the file rather than known here, so that the warning travels with the data
    to anything that serialises it onward.
    """

    by_lead_time: dict[int, LeadTime]

    def at(self, lead_time_days: int) -> LeadTime | None:
        """The profile for this Lead Time, or `None` where nothing was measured.

        `None` covers both edges: beyond the archive's seven days, and at or below zero,
        where a Pipeline Run is scoring a date whose forecast has no drift left to have.
        Callers must widen for the first and may ignore the second, and the type makes them
        say which.
        """
        return self.by_lead_time.get(lead_time_days)


def _number(body: dict[str, Any], field: str, where: str) -> float:
    if field not in body:
        raise ForecastErrorUnusable(f"{where} is missing {field!r}")
    try:
        return float(body[field])
    except (TypeError, ValueError) as error:
        raise ForecastErrorUnusable(
            f"{where} {field!r} must be a number, got {body[field]!r}"
        ) from error


def _band(raw: Any, where: str) -> Band:
    if not isinstance(raw, dict):
        raise ForecastErrorUnusable(f"{where} must be an object, got {raw!r}")

    drift = _number(raw, "drift", where)
    p5 = _number(raw, "p5", where)
    p95 = _number(raw, "p95", where)
    bias = _number(raw, "bias", where)
    hours = _number(raw, "hours", where)

    # A zero-width band is the dangerous one. Perturbing by zero is not an error — every
    # evaluation agrees, the range renders as a single number, and the interface reports
    # certainty it never measured.
    if drift <= 0:
        raise ForecastErrorUnusable(
            f"{where} drift is {drift}, which claims the forecast does not move at all; "
            "a zero-width band collapses the Predictive Distribution to a point estimate "
            "and would be published as confidence"
        )
    if p5 >= p95:
        raise ForecastErrorUnusable(
            f"{where} has p5 ({p5}) at or above p95 ({p95}), which describes no distribution"
        )
    if hours <= 0:
        raise ForecastErrorUnusable(f"{where} rests on {hours} hours, so nothing was measured")

    return Band(drift=drift, bias=bias, p5=p5, p95=p95, hours=int(hours))


def parse(body: dict[str, Any]) -> ForecastError:
    """Build a profile from a parsed file, refusing one that would mis-shape a range.

    Every check describes a file that parses cleanly. A schema check would pass all of them.
    """
    if not isinstance(body, dict):
        raise ForecastErrorUnusable(
            f"the forecast error file must hold an object, got {type(body).__name__}"
        )

    if "only_term" not in body:
        raise ForecastErrorUnusable(
            "the profile does not carry 'only_term', the field recording that forecast drift "
            "is one of three uncertainty terms and the smallest at short Lead Times; a file "
            "without it invites a consumer to publish a distribution three times too narrow"
        )

    method = body.get("method")
    if not isinstance(method, dict) or "big_swell_m" not in method:
        raise ForecastErrorUnusable(
            "the profile does not record 'big_swell_m' under 'method', so there is no way to "
            "know which sea reads the big-swell band and which reads the all-hours one"
        )
    big_swell_m = _number(method, "big_swell_m", "method")

    through = body.get("measured_through_lead_days")
    if not isinstance(through, int) or through <= 0:
        raise ForecastErrorUnusable(
            f"measured_through_lead_days must be a positive whole number, got {through!r}"
        )

    raw_leads = body.get("by_lead_time")
    if not isinstance(raw_leads, dict):
        raise ForecastErrorUnusable(f"by_lead_time must be an object, got {raw_leads!r}")

    by_lead_time: dict[int, LeadTime] = {}
    for lead in range(1, through + 1):
        # The file states a range; the keys have to cover it. A gap would make `at()` answer
        # `None` for a Lead Time the file claims to have measured, and the caller would then
        # widen for missing data that is really a typo.
        raw = raw_leads.get(str(lead), raw_leads.get(lead))
        if raw is None:
            raise ForecastErrorUnusable(
                f"the profile claims to reach {through} days but has no entry for lead time "
                f"{lead}; a gap reads as unmeasured rather than as the mistake it is"
            )
        if not isinstance(raw, dict):
            raise ForecastErrorUnusable(f"lead time {lead} must be an object, got {raw!r}")

        for regime in ("all_hours", "big_swell"):
            if regime not in raw:
                raise ForecastErrorUnusable(
                    f"lead time {lead} is missing the {regime!r} band; both regimes are "
                    "required, and a file with one would apply it to every sea"
                )

        by_lead_time[lead] = LeadTime(
            lead_time_days=lead,
            all_hours=_band(raw["all_hours"], f"lead time {lead} all_hours"),
            big_swell=_band(raw["big_swell"], f"lead time {lead} big_swell"),
            big_swell_m=big_swell_m,
        )

    return ForecastError(
        quantity=str(body.get("quantity", "")),
        reference=str(body.get("reference", "")),
        measured_through_lead_days=through,
        only_term=str(body["only_term"]),
        by_lead_time=by_lead_time,
    )


def load(path: str | Path | None = None) -> ForecastError:
    """Read a profile from disk.

    Resolution order: the argument, then `NAZARENOW_FORECAST_ERROR`, then the file this
    release ships. A missing file raises rather than defaulting, for the reason
    `ForecastErrorUnusable` documents.
    """
    resolved = Path(path or os.environ.get(PATH_VARIABLE) or DEFAULT_PATH)
    try:
        text = resolved.read_text(encoding="utf-8")
    except OSError as error:
        raise ForecastErrorUnusable(
            f"cannot read the forecast error profile from {resolved}: {error}. Set "
            f"{PATH_VARIABLE} to a profile file, or run analysis/forecast_error/profile.py "
            "to regenerate the default"
        ) from error

    try:
        body = json.loads(text)
    except json.JSONDecodeError as error:
        raise ForecastErrorUnusable(f"{resolved} is not valid JSON: {error}") from error

    return parse(body)

"""The published track record: what the system called, and what actually happened.

Ticket #16. This is the page a reader consults before deciding whether a Go Call is worth
a flight, so it is the one place in the system where overstating is the expensive failure
and understating is merely disappointing. Everything here is shaped around that asymmetry.

**It is data, not a computation.** `analysis/track_record/publish.py` assembles the file
from the committed reports — #11's backtest, #12's calibration, #13's held-out scores and
#52's served-path measurement — and this module reads it. ADR 0005 makes the request path a
reader, and the alternative is worse than a rule violation: scoring the record at serve time
would mean re-deriving what the system "would have said" using data that did not exist when
it said it, which is the exact failure the retained-call record was built to prevent.

**Rates are derived here and never stored.** A file carrying both `days_flagged` and a
`precision` is carrying the same fact twice, and the copies drift in one predictable
direction — the rate is what gets quoted, the counts are what get regenerated. So the file
holds counts and this module divides.

**A band is a pair, and a panel is a pair.** ADR 0006 requires the Heuristic Baseline beside
every accuracy figure this project reports, and #16 requires Watch and Go Call accuracy
reported separately. Both are enforced by the shape: `Band` cannot be constructed without
both models' error, and `Panel` names its two tiers as fields rather than keying them out of
a mapping. Neither promise is left to a renderer to remember.

The validation below is the same idea as `thresholds.py`'s: every refusal describes a file
that parses cleanly and means something wrong. A track record's corruption does not crash a
page — it produces a confident, ordinary-looking one that claims more than the evidence.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nazarenow.decision import Status

DEFAULT_PATH = Path(__file__).resolve().parent / "track_record.json"
"""The record this release publishes, versioned alongside the code that reads it."""

PATH_VARIABLE = "NAZARENOW_TRACK_RECORD"
"""Points at a different file, following `NAZARENOW_THRESHOLDS` and `NAZARENOW_DB`."""

TIERS = ("watch_or_better", "go_call")
"""The two tiers a panel must carry, in the order a reader meets them.

Named here so the file's keys are spelled once. The parsed `Panel` holds them as fields
rather than as a mapping — a file carrying one tier would render a page quoting its figures
under both headings, and that is a shape worth making unrepresentable rather than checking
for at each place a tier is read.
"""


class TrackRecordUnusable(ValueError):
    """The track record file is missing, unparseable, or claims more than it can support.

    Raised rather than degrading to a partial page. A track record with a section missing
    is not a smaller claim than a complete one — a reader who sees Watch accuracy and no Go
    Call accuracy has no way to tell an omission from an absence of evidence, and the
    omission always looks like the more flattering of the two.
    """


@dataclass(frozen=True)
class DeliveredStep:
    """How many of a tier's flagged days reached one height, out of how many there were.

    Carries its own denominator so the share is derived here rather than by a renderer
    holding two numbers from two places. That is the same rule the module docstring states
    about rates, applied at the point where getting it wrong would say "97 of 43".
    """

    metres: float
    days: int
    of_days: int

    @property
    def share(self) -> float:
        return self.days / self.of_days


@dataclass(frozen=True)
class Delivery:
    """What the sea actually did on the days a tier flagged (#83).

    The answer to a different question from everything else on this page. Recall and
    precision are scored against the **Gold Days** — days ratified giant by a contest or a
    record — which is the only claim here a reader can check against the outside world, and
    is also a bar so high that a rule flagging nothing but excellent days still reads as
    mostly waste. This says what the ocean did on those same days, in the quantity the system
    is actually grounded in.

    **It is Significant Wave Height and not Face Height.** The distinction is `CONTEXT.md`'s
    load-bearing one: this is the sea measured at a mooring, not the wave a person watches
    break at Praia do Norte, and the two are not convertible by any fixed ratio. A renderer
    putting these metres beside a photograph is the failure this docstring exists to prevent.

    **It is a record, not a forecast.** These are days the rule flagged in the past, scored
    on a Hindcast. Nothing here says what the next Go Call will bring.
    """

    minimum_m: float
    median_m: float
    maximum_m: float
    above: tuple[DeliveredStep, ...]


@dataclass(frozen=True)
class Tier:
    """One tier's record against the Gold Days in a panel.

    Counts only. Every rate below is a property, for the reason the module docstring gives.
    """

    gold_days_called: int
    gold_days_in_panel: int
    days_flagged: int
    big_wave_seasons: float
    delivered: Delivery | None = None
    """What this tier's days delivered, or `None` where it is not published.

    `None` is the Watch tier today, and the reason is a disagreement between the two reports
    the record is built from rather than an absence of data — `publish.py`'s `DELIVERED_TIERS`
    carries the diagnosis and #87 is the fix. Optional rather than required because a page
    that cannot say this is a page missing a sentence, where a page that cannot say a recall
    is a page that should not be served.
    """

    @property
    def recall(self) -> float:
        """The share of Gold Days this tier caught."""
        return self.gold_days_called / self.gold_days_in_panel

    @property
    def precision_lower_bound(self) -> float:
        """The share of flagged days known to have been genuinely giant.

        A **lower** bound, per #11: a day this tier flagged that is not on the Gold Day list
        may still have been an XXL Day nobody documented. The Gold Day list is hand-verified
        from contest records and ratified measurements, not a census.
        """
        return self.gold_days_called / self.days_flagged

    @property
    def wasted_upper_bound(self) -> float:
        """How often acting on this tier would have been wasted, at worst.

        The complement of a lower bound is an upper one. #16 asks for this stated plainly
        rather than left as an inversion for the reader to perform, and stating it the
        pessimistic way round is the only honest direction: the system is asking someone to
        spend money.
        """
        return 1.0 - self.precision_lower_bound

    @property
    def days_wasted_upper_bound(self) -> int:
        """The same figure as a count of days, which is what a reader actually pictures."""
        return self.days_flagged - self.gold_days_called

    @property
    def flags_per_big_wave_season(self) -> float:
        """What this tier costs in a typical Big-Wave Season.

        The number that decides whether a tier is usable at all. 32 Watch days a season is
        a reason to keep watching; 32 Go Calls a season is a reason to ignore them.
        """
        return self.days_flagged / self.big_wave_seasons


@dataclass(frozen=True)
class Panel:
    """One span the record was scored over, with both tiers as fields.

    Two panels are published and they are deliberately not merged. The held-out one is the
    honest figure; the whole-record one is larger and partly measured on days the thresholds
    were chosen against. A reader given only their average would be given neither.
    """

    span: str
    basis: str
    """What the calls were derived from, named in `CONTEXT.md`'s vocabulary — the Hindcast,
    which is a reconstruction of Offshore Conditions as they were and was never available in
    advance. The page states this: a rule scored on a perfect reconstruction of the past
    flatters itself against one served a real forecast."""

    gold_days: int
    big_wave_seasons: float
    watch_or_better: Tier
    go_call: Tier


@dataclass(frozen=True)
class Band:
    """The two models' error over one subset of hours, which is the only shape either
    travels in. See the module docstring."""

    name: str
    hours: int
    baseline_mae_m: float
    learned_mae_m: float

    caveat: str | None
    """What this row cannot carry on its own, when the report it came from says so.

    Present on exactly the rows whose source insists the figure never be quoted bare — the
    Gold Day row, which rests on five days, and the served aggregate, which #52 measured as
    not robust to the reconstruction assumption. A caveat that lives beside the number
    travels with it into whatever renders the table; one that lives in the renderer does not
    survive the next table.
    """

    @property
    def gain_m(self) -> float:
        """Positive means the learned Amplification Model is closer to the Proxy Target.

        The sign convention every table in `analysis/amplification_model/` already uses.
        Choosing the other one here would make the same measurement read as its opposite
        beside the reports it is drawn from.
        """
        return self.baseline_mae_m - self.learned_mae_m


@dataclass(frozen=True)
class RangeCoverage:
    """How often the printed range held the outcome, over one subset of hours at one Lead Time.

    Every other figure in this record is scored against the **Gold Days** — days ratified giant
    by a contest or a record. This one is scored against the sea itself, hour by hour, and it
    is the only published claim measured against what the range said rather than against what
    the call said.
    """

    hours: int
    covered: float
    """The share of outcomes that fell inside the range. Compared against the claim on
    `RangeCalibration`, which is one number for the whole table rather than a copy per row."""

    median_width_m: float
    widening_factor: float
    """What the half-width would have to be multiplied by for the claimed share of outcomes to
    fall inside it. Above one, the range is narrower than the outcomes justify; below one, it
    is wider. `analysis/distribution_coverage/README.md` defines it and #80 measured it."""

    @property
    def justified_width_m(self) -> float:
        """The width these outcomes actually asked for.

        The whole finding in one number a reader can picture beside the one the site prints:
        a range spanning 2.19 m that would have held the same share of outcomes at 1.15 m.
        Derived rather than stored, for the reason the module docstring gives about rates —
        a file carrying both this and the width it comes from carries one fact twice.
        """
        return self.median_width_m * self.widening_factor


@dataclass(frozen=True)
class RangeLead:
    """One Lead Time, with both subsets as fields.

    The pair is structural for the same reason `Panel`'s two tiers are. The `big_swell` rows
    describe the sea a Go Call is actually issued on and are the more flattering of the two,
    so a shape that could carry one alone is a shape that could publish the kinder number
    under a heading a reader takes for the whole finding.
    """

    lead_days: int
    all_hours: RangeCoverage
    big_swell: RangeCoverage


@dataclass(frozen=True)
class RangeCalibration:
    """What the range the interface prints claims to hold, against what it held (#80, #94).

    **This section states nothing about which way the miss runs.** It carries the claim, the
    measurement and the two caveats, and whatever renders it derives the direction. #82 exists
    to change the direction, and a verdict baked in here would outlive the refit that falsifies
    it — the failure ADR 0014 and #76 are both about, in a different costume.

    **Required, not optional**, unlike `Delivery`. A record that cannot say this renders a page
    that prints a range and says nothing about whether it means what it says, which is exactly
    the flattering omission `TrackRecordUnusable` exists to refuse.
    """

    claimed: float
    """The share the range says it holds — the 5th to 95th percentile of the draws, so 0.9."""

    understates_because: str
    rests_on: str
    """The two qualifications that must travel with the table, as fields rather than a list.

    A list can arrive with one element and render a page that looks complete. The first says
    the shipped range is wider than the one measured; the second says the whole table rests on
    one partial Big-Wave Season. Neither is derivable from the numbers, and a reader given the
    figures without them has been handed a calibration certificate, which this is not.
    """

    leads: tuple[RangeLead, ...]


@dataclass(frozen=True)
class RecordedDay:
    """One past day: what was called, and what the Hindcast then held for it."""

    date: str
    season: str
    call: Status
    peak_significant_wave_height_m: float
    """The day's largest Significant Wave Height **in the Hindcast** — which is the same
    reconstruction the call above was derived from, not an independent observation of the
    outcome. The independent part of this row is `gold_day`.

    Published anyway because it is what the call was judged on and a reader comparing a
    missed Gold Day against a quiet sea is owed the number. But it must never be labelled as
    what was measured afterwards: no buoy reading is involved, and the whole point of the
    Proxy Target is that Face Height at Praia do Norte has no historical archive."""

    gold_day: bool
    gold_tier: str | None
    """How the day was verified, for a Gold Day. `None` otherwise, and a tier without a Gold
    Day is refused: it would present an ordinary day as independently confirmed."""


@dataclass(frozen=True)
class TrackRecord:
    published_at: str
    source: str
    """The path in this repository that regenerates the file, so a reader can check it."""

    held_out: Panel
    full_record: Panel
    scored: list[Band]
    """Both models on identical hours, each reading the Hindcast directly. What the fit is
    worth, in the units it was fitted in."""

    range_calibration: RangeCalibration
    """How often the range the interface prints held the outcome, against how often it claims
    to (#94). The only figure in this record scored against the sea rather than against the
    Gold Days, and until #94 the only published claim with a measurement behind it that the
    page did not mention."""

    served: list[Band]
    """The same comparison along the path a Pipeline Run actually takes, where the learned
    model must first restate an Open-Meteo reading into the units it was fitted in.

    Published beside `scored` rather than instead of it because they disagree, and the
    disagreement is the finding: the translation step costs real ground in the middle bands
    and almost nothing at size. #52 corrected these figures — the previously published
    served table was partly measuring its own generator."""

    gold_days_fitted: int
    gold_days_validated: int
    days: list[RecordedDay]

    @property
    def gold_days_total(self) -> int:
        """The whole basis of the calibration, and a small number. Stated rather than
        implied — #16 requires it on the page."""
        return self.gold_days_fitted + self.gold_days_validated


def _require(body: dict[str, Any], field: str, where: str) -> Any:
    if not isinstance(body, dict):
        raise TrackRecordUnusable(f"{where} must hold an object, got {type(body).__name__}")
    if field not in body:
        raise TrackRecordUnusable(f"{where} is missing required field {field!r}")
    return body[field]


def _count(body: dict[str, Any], field: str, where: str) -> int:
    value = _require(body, field, where)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise TrackRecordUnusable(
            f"{where}: {field} must be a whole number of days at or above zero, got {value!r}"
        )
    return value


def _metres(body: dict[str, Any], field: str, where: str) -> float:
    value = _require(body, field, where)
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise TrackRecordUnusable(f"{where}: {field} must be a number in metres, got {value!r}")
    if value < 0:
        raise TrackRecordUnusable(f"{where}: {field} must not be negative, got {value!r}")
    return float(value)


def _share(body: dict[str, Any], field: str, where: str) -> float:
    value = _require(body, field, where)
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise TrackRecordUnusable(f"{where}: {field} must be a number, got {value!r}")
    if not 0.0 <= value <= 1.0:
        raise TrackRecordUnusable(
            f"{where}: {field} is a share of outcomes and must fall between 0 and 1, got "
            f"{value!r}. A share above one renders as a percentage over 100, which reads as a "
            "rendering fault rather than as the corrupt figure it is"
        )
    return float(value)


def _sentence(body: dict[str, Any], field: str, where: str) -> str:
    """A qualification that must actually say something.

    An empty string passes every type check and renders as a bullet with nothing in it, which
    a reader skips — so the page keeps its shape and loses the sentence that was the point of
    publishing the section at all.
    """
    value = _require(body, field, where)
    if not isinstance(value, str) or not value.strip():
        raise TrackRecordUnusable(
            f"{where}: {field} must carry the qualification it names, got {value!r}"
        )
    return value


def _range_coverage(raw: Any, where: str) -> RangeCoverage:
    if not isinstance(raw, dict):
        raise TrackRecordUnusable(f"{where} must hold an object, got {type(raw).__name__}")

    hours = _count(raw, "hours", where)
    if hours == 0:
        raise TrackRecordUnusable(
            f"{where} was scored over no hours, so the shares beside it are divisions by zero "
            "dressed as measurements"
        )

    width = _metres(raw, "median_width_m", where)
    if width <= 0:
        raise TrackRecordUnusable(
            f"{where}: median_width_m is {width}, so the range has no width and cannot have "
            "held anything"
        )

    factor = _require(raw, "widening_factor", where)
    if not isinstance(factor, int | float) or isinstance(factor, bool) or factor <= 0:
        raise TrackRecordUnusable(
            f"{where}: widening_factor must be greater than zero, got {factor!r}. It multiplies "
            f"a half-width, so zero or less describes a range that cannot be drawn"
        )

    return RangeCoverage(
        hours=hours,
        covered=_share(raw, "covered", where),
        median_width_m=width,
        widening_factor=float(factor),
    )


def _range_calibration(raw: Any) -> RangeCalibration:
    """Parse the measured calibration of the printed range, refusing an incoherent one.

    **Nothing here refuses a direction.** A record where the range holds the outcome *less*
    often than it claims is not a corrupt file — it is what #82 is trying to produce, and a
    parser that rejected it would make the repair unshippable while looking like a safety
    check. What is refused is a file that cannot describe any distribution at all: a subset
    that is larger than the set containing it, a Lead Time appearing twice, a share above one.
    """
    where = "height_record.range_calibration"
    if not isinstance(raw, dict):
        raise TrackRecordUnusable(f"{where} must hold an object, got {type(raw).__name__}")

    claimed = _share(raw, "claimed", where)
    if not 0.0 < claimed < 1.0:
        raise TrackRecordUnusable(
            f"{where}: claimed is {claimed}, but a range holding all outcomes or none of them "
            "is not a claim any measurement below can be compared against"
        )

    raw_leads = _require(raw, "leads", where)
    if not isinstance(raw_leads, list) or not raw_leads:
        raise TrackRecordUnusable(
            f"{where} carries no Lead Times, so the page would print a claim about the range "
            "with no measurement under it"
        )

    leads = []
    for index, entry in enumerate(raw_leads):
        at = f"{where}.leads[{index}]"
        if not isinstance(entry, dict):
            raise TrackRecordUnusable(f"{at} is not an object")
        lead_days = _count(entry, "lead_days", at)
        if lead_days == 0:
            raise TrackRecordUnusable(f"{at}: lead_days must be at least one day of notice")

        all_hours = _range_coverage(_require(entry, "all_hours", at), f"{at}.all_hours")
        big_swell = _range_coverage(_require(entry, "big_swell", at), f"{at}.big_swell")
        if big_swell.hours > all_hours.hours:
            raise TrackRecordUnusable(
                f"{at}: the big-swell rows hold {big_swell.hours} hours against "
                f"{all_hours.hours} for all hours, so they are not a subset of them and the "
                "page would present two unrelated measurements as one comparison"
            )
        leads.append(RangeLead(lead_days=lead_days, all_hours=all_hours, big_swell=big_swell))

    ordered = [lead.lead_days for lead in leads]
    if ordered != sorted(set(ordered)):
        raise TrackRecordUnusable(
            f"{where}: Lead Times {ordered} are repeated or out of order. The page reads down "
            "them as a forecast reaching further, and a repeat renders one Lead Time's figures "
            "under another's heading"
        )

    return RangeCalibration(
        claimed=claimed,
        understates_because=_sentence(raw, "understates_because", where),
        rests_on=_sentence(raw, "rests_on", where),
        leads=tuple(leads),
    )


def _tier(raw: Any, name: str, panel: str, gold_days: int, seasons: float) -> Tier:
    where = f"{panel} tier {name!r}"
    gold_days_called = _count(raw, "gold_days_called", where)
    days_flagged = _count(raw, "days_flagged", where)

    if gold_days_called > gold_days:
        raise TrackRecordUnusable(
            f"{where} caught more Gold Days ({gold_days_called}) than the panel contains "
            f"({gold_days})"
        )
    if gold_days_called > days_flagged:
        raise TrackRecordUnusable(
            f"{where}: gold_days_called ({gold_days_called}) exceeds days_flagged "
            f"({days_flagged}), so more days were caught than were ever flagged"
        )

    return Tier(
        gold_days_called=gold_days_called,
        gold_days_in_panel=gold_days,
        days_flagged=days_flagged,
        big_wave_seasons=seasons,
        delivered=_delivered(raw.get("delivered"), where, days_flagged),
    )


def _delivered(raw: Any, where: str, days_flagged: int) -> Delivery | None:
    """The delivered sea, or `None` where the record does not publish one for this tier.

    Every refusal here describes a file that parses and means something wrong, in the
    direction that flatters. A ladder counting more days than were flagged, or one that
    admits more days as the bar rises, produces an ordinary-looking sentence claiming the
    system did better than the record holds.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise TrackRecordUnusable(f"{where}: delivered must be an object, got {type(raw)}")

    minimum = _metres(raw, "minimum_m", where)
    median = _metres(raw, "median_m", where)
    maximum = _metres(raw, "maximum_m", where)
    if not minimum <= median <= maximum:
        raise TrackRecordUnusable(
            f"{where}: delivered minimum {minimum}, median {median} and maximum {maximum} "
            "are not in order, so at least one describes a different set of days"
        )

    ladder = _require(raw, "above", f"{where}.delivered")
    if not isinstance(ladder, list) or not ladder:
        raise TrackRecordUnusable(
            f"{where}: delivered carries no thresholds, so it states a range with nothing inside it"
        )

    steps = []
    for index, step in enumerate(ladder):
        at = f"{where}.delivered.above[{index}]"
        if not isinstance(step, dict):
            raise TrackRecordUnusable(f"{at} is not an object")
        metres = _metres(step, "metres", at)
        days = _count(step, "days", at)
        if days > days_flagged:
            raise TrackRecordUnusable(
                f"{at}: {days} days reached {metres} m out of {days_flagged} flagged, which "
                "is more days than the tier ever called"
            )
        if metres > maximum and days:
            raise TrackRecordUnusable(
                f"{at}: {days} days reached {metres} m where the highest day recorded is "
                f"{maximum} m"
            )
        steps.append(DeliveredStep(metres=metres, days=days, of_days=days_flagged))

    for lower, higher in zip(steps, steps[1:], strict=False):
        if higher.metres <= lower.metres:
            raise TrackRecordUnusable(
                f"{where}: delivered thresholds are not increasing ({lower.metres} then "
                f"{higher.metres}), so the ladder does not read as one"
            )
        if higher.days > lower.days:
            raise TrackRecordUnusable(
                f"{where}: {higher.days} days reached {higher.metres} m but only "
                f"{lower.days} reached {lower.metres} m, which cannot both be true"
            )

    return Delivery(minimum_m=minimum, median_m=median, maximum_m=maximum, above=tuple(steps))


def _panel(raw: Any, name: str) -> Panel:
    where = f"call_record.{name}"
    gold_days = _count(raw, "gold_days", where)
    if gold_days == 0:
        raise TrackRecordUnusable(
            f"{where} contains no Gold Days, so nothing on it can be a recall"
        )

    seasons = _require(raw, "big_wave_seasons", where)
    if not isinstance(seasons, int | float) or isinstance(seasons, bool) or seasons <= 0:
        raise TrackRecordUnusable(
            f"{where}: big_wave_seasons must be greater than zero, got {seasons!r}"
        )

    tiers_raw = _require(raw, "tiers", where)
    missing = [tier for tier in TIERS if tier not in (tiers_raw or {})]
    if missing:
        raise TrackRecordUnusable(
            f"{where} is missing tier(s) {missing}; #16 requires Watch and Go Call accuracy "
            "reported separately, and a page with one of them would quote its figures under "
            "both headings"
        )

    watch, go_call = (
        _tier(tiers_raw[tier], tier, where, gold_days, float(seasons)) for tier in TIERS
    )

    # ADR 0003 makes a Watch reach further than a Go Call, so this ordering is a property of
    # the tiers rather than of any particular calibration. A file inverting it is not a worse
    # system; it is a mislabelled table, and every rate on it would read as the other tier's.
    if watch.days_flagged < go_call.days_flagged:
        raise TrackRecordUnusable(
            f"{where}: the Watch tier flagged fewer days ({watch.days_flagged}) than the Go "
            f"Call tier ({go_call.days_flagged}); the recall tier reaches further than the "
            "precision tier by construction, so this is a table with its columns swapped"
        )

    return Panel(
        span=str(_require(raw, "span", where)),
        basis=str(_require(raw, "basis", where)),
        gold_days=gold_days,
        big_wave_seasons=float(seasons),
        watch_or_better=watch,
        go_call=go_call,
    )


def _bands(raw: Any, name: str) -> list[Band]:
    where = f"height_record.{name}"
    raw_bands = _require(raw, "bands", where)
    if not isinstance(raw_bands, list) or not raw_bands:
        raise TrackRecordUnusable(f"{where} must carry at least one band, got {raw_bands!r}")

    bands = []
    for index, band in enumerate(raw_bands):
        at = f"{where}[{index}]"
        caveat = band.get("caveat") if isinstance(band, dict) else None
        bands.append(
            Band(
                name=str(_require(band, "name", at)),
                hours=_count(band, "hours", at),
                # Both, always. There is no partial band, which is what makes ADR 0006's
                # "never without the baseline" a property of the data rather than a habit of
                # whoever writes the next renderer.
                baseline_mae_m=_metres(band, "baseline_mae_m", at),
                learned_mae_m=_metres(band, "learned_mae_m", at),
                caveat=str(caveat) if caveat else None,
            )
        )
    return bands


def _day(raw: Any, index: int) -> RecordedDay:
    where = f"days[{index}]"
    raw_call = _require(raw, "call", where)
    try:
        call = Status(raw_call)
    except ValueError as error:
        raise TrackRecordUnusable(
            f"{where}: {raw_call!r} is not a call this system issues; the page renders each "
            f"of {[status.value for status in Status]} differently and would render this as "
            "nothing at all"
        ) from error

    gold_day = _require(raw, "gold_day", where)
    if not isinstance(gold_day, bool):
        raise TrackRecordUnusable(f"{where}: gold_day must be true or false, got {gold_day!r}")

    tier = raw.get("gold_tier")
    if tier and not gold_day:
        raise TrackRecordUnusable(
            f"{where} carries gold_tier {tier!r} without being a Gold Day, which would present "
            "an ordinary day as independently confirmed"
        )
    if gold_day and not tier:
        raise TrackRecordUnusable(
            f"{where} is a Gold Day with no gold_tier; how a day was verified is the whole "
            "weight the Gold Day list carries"
        )

    return RecordedDay(
        date=str(_require(raw, "date", where)),
        season=str(_require(raw, "season", where)),
        call=call,
        peak_significant_wave_height_m=_metres(raw, "peak_significant_wave_height_m", where),
        gold_day=gold_day,
        gold_tier=str(tier) if tier else None,
    )


def parse(body: dict[str, Any]) -> TrackRecord:
    """Build a track record from a parsed file, refusing one that overstates.

    Every check describes a file that would render a plausible page making a claim the
    evidence behind it does not support.
    """
    if not isinstance(body, dict):
        raise TrackRecordUnusable(
            f"the track record file must hold an object, got {type(body).__name__}"
        )

    for section in ("call_record", "height_record", "gold_days", "days"):
        if section not in body:
            raise TrackRecordUnusable(
                f"the track record is missing its {section!r} section; a partial record reads "
                "as an absence of evidence rather than as an omission, and the omission is "
                "always the more flattering of the two"
            )

    call_record = body["call_record"]
    held_out = _panel(_require(call_record, "held_out", "call_record"), "held_out")
    full_record = _panel(_require(call_record, "full_record", "call_record"), "full_record")

    height = body["height_record"]
    scored = _bands(_require(height, "scored", "height_record"), "scored")
    served = _bands(_require(height, "served", "height_record"), "served")
    if "range_calibration" not in height:
        raise TrackRecordUnusable(
            "height_record carries no range_calibration; the interface prints a range in "
            "metres and this is the measurement of whether it means what it claims, so a "
            "record without it serves a page that states the claim and omits the check"
        )
    calibration = _range_calibration(height["range_calibration"])

    gold_days = body["gold_days"]
    fitted = _count(gold_days, "fitted", "gold_days")
    validated = _count(gold_days, "validated", "gold_days")

    # The split has to be the panels it is quoted beside. A validated count that does not
    # match the held-out panel makes the thinnest number on the page look less thin, and
    # nothing downstream can tell which of the two is the mistake.
    if validated != held_out.gold_days:
        raise TrackRecordUnusable(
            f"gold_days.validated ({validated}) is not the held-out panel's Gold Day count "
            f"({held_out.gold_days}); the calibration's basis and the record it is scored on "
            "must be the same days"
        )
    if fitted + validated != full_record.gold_days:
        raise TrackRecordUnusable(
            f"gold_days fitted + validated ({fitted + validated}) is not the whole record's "
            f"Gold Day count ({full_record.gold_days})"
        )

    raw_days = body["days"]
    if not isinstance(raw_days, list) or not raw_days:
        raise TrackRecordUnusable("the track record carries no days, so there is nothing to show")
    days = [_day(day, index) for index, day in enumerate(raw_days)]

    dates = [day.date for day in days]
    if dates != sorted(dates):
        raise TrackRecordUnusable(
            "days are not in date order; the page reads as a chronology, and rows out of "
            "order look like a rendering fault rather than a regenerated file"
        )

    return TrackRecord(
        published_at=str(_require(body, "published_at", "the track record")),
        source=str(_require(body, "source", "the track record")),
        held_out=held_out,
        full_record=full_record,
        scored=scored,
        range_calibration=calibration,
        served=served,
        gold_days_fitted=fitted,
        gold_days_validated=validated,
        days=days,
    )


def load(path: str | Path | None = None) -> TrackRecord:
    """Read the published track record from disk.

    Resolution order: the argument, then `NAZARENOW_TRACK_RECORD`, then the file this
    release ships. A missing file raises rather than yielding an empty record — a page that
    renders with nothing on it is indistinguishable from a system with nothing to show.
    """
    resolved = Path(path or os.environ.get(PATH_VARIABLE) or DEFAULT_PATH)
    try:
        text = resolved.read_text(encoding="utf-8")
    except OSError as error:
        raise TrackRecordUnusable(
            f"cannot read the track record from {resolved}: {error}. Run "
            "analysis/track_record/publish.py to regenerate the default"
        ) from error

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as error:
        raise TrackRecordUnusable(f"{resolved} is not valid JSON: {error}") from error

    return parse(parsed)

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

**A band is a pair.** ADR 0006 requires the Heuristic Baseline beside every accuracy figure
this project reports. Rather than asking each renderer to remember, `Band` cannot be
constructed without both models' error, so there is no shape in which one travels alone.

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
"""Both tiers, always. #16 requires Watch and Go Call accuracy reported separately, and a
file carrying one of them would render a page quoting its figures under both headings."""


class TrackRecordUnusable(ValueError):
    """The track record file is missing, unparseable, or claims more than it can support.

    Raised rather than degrading to a partial page. A track record with a section missing
    is not a smaller claim than a complete one — a reader who sees Watch accuracy and no Go
    Call accuracy has no way to tell an omission from an absence of evidence, and the
    omission always looks like the more flattering of the two.
    """


@dataclass(frozen=True)
class Tier:
    """One tier's record against the Gold Days in a panel.

    Counts only. Every rate below is a property, for the reason the module docstring gives.
    """

    name: str
    gold_days_called: int
    gold_days_in_panel: int
    days_flagged: int
    big_wave_seasons: float

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
    """One span the record was scored over, with both tiers.

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
    tiers: dict[str, Tier]


@dataclass(frozen=True)
class Band:
    """The two models' error over one subset of hours, which is the only shape either
    travels in. See the module docstring."""

    name: str
    hours: int
    baseline_mae_m: float
    learned_mae_m: float

    @property
    def gain_m(self) -> float:
        """Positive means the learned Amplification Model is closer to the Proxy Target.

        The sign convention every table in `analysis/amplification_model/` already uses.
        Choosing the other one here would make the same measurement read as its opposite
        beside the reports it is drawn from.
        """
        return self.baseline_mae_m - self.learned_mae_m


@dataclass(frozen=True)
class HeightRecord:
    """How close the predicted height came, band by band."""

    bands: list[Band]


@dataclass(frozen=True)
class RecordedDay:
    """One past day: what was called, and what the sea then did."""

    date: str
    season: str
    call: Status
    peak_significant_wave_height_m: float
    """The day's largest Significant Wave Height in the Hindcast — the whole Combined Sea,
    15km offshore near the canyon head. Not Face Height, and not convertible to it."""

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
    scored: HeightRecord
    """Both models on identical hours, each reading the Hindcast directly. What the fit is
    worth, in the units it was fitted in."""

    served: HeightRecord
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
        name=name,
        gold_days_called=gold_days_called,
        gold_days_in_panel=gold_days,
        days_flagged=days_flagged,
        big_wave_seasons=seasons,
    )


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

    tiers = {tier: _tier(tiers_raw[tier], tier, where, gold_days, float(seasons)) for tier in TIERS}

    # ADR 0003 makes a Watch reach further than a Go Call, so this ordering is a property of
    # the tiers rather than of any particular calibration. A file inverting it is not a worse
    # system; it is a mislabelled table, and every rate on it would read as the other tier's.
    if tiers["watch_or_better"].days_flagged < tiers["go_call"].days_flagged:
        raise TrackRecordUnusable(
            f"{where}: the Watch tier flagged fewer days "
            f"({tiers['watch_or_better'].days_flagged}) than the Go Call tier "
            f"({tiers['go_call'].days_flagged}); the recall tier reaches further than the "
            "precision tier by construction, so this is a table with its columns swapped"
        )

    return Panel(
        span=str(_require(raw, "span", where)),
        basis=str(_require(raw, "basis", where)),
        gold_days=gold_days,
        big_wave_seasons=float(seasons),
        tiers=tiers,
    )


def _height(raw: Any, name: str) -> HeightRecord:
    where = f"height_record.{name}"
    raw_bands = _require(raw, "bands", where)
    if not isinstance(raw_bands, list) or not raw_bands:
        raise TrackRecordUnusable(f"{where} must carry at least one band, got {raw_bands!r}")

    bands = []
    for index, band in enumerate(raw_bands):
        at = f"{where}[{index}]"
        bands.append(
            Band(
                name=str(_require(band, "name", at)),
                hours=_count(band, "hours", at),
                # Both, always. There is no partial band, which is what makes ADR 0006's
                # "never without the baseline" a property of the data rather than a habit of
                # whoever writes the next renderer.
                baseline_mae_m=_metres(band, "baseline_mae_m", at),
                learned_mae_m=_metres(band, "learned_mae_m", at),
            )
        )
    return HeightRecord(bands=bands)


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
    scored = _height(_require(height, "scored", "height_record"), "scored")
    served = _height(_require(height, "served", "height_record"), "served")

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

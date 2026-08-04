"""What the agreement gate costs, on the two Big-Wave Seasons the archive can measure it over.

#8's second half makes a Go Call require the independent wave models to agree that the
deciding hour clears the Go Call bar. That changes the tier rule ADR 0003 governs and #12 and
#43 calibrated, and the ticket is explicit that the change cannot ship without knowing what it
costs.

**`analysis/backtest/` cannot answer that, and it is not an oversight.** A Hindcast is what
the ocean did. It contains no forecast, so there is nothing in it to disagree, and the
backtest says in its own source that it assumes agreement and scores the rule's ceiling. Run
either side of this ticket it produces identical tables, which is correct and is not a
measurement of the gate.

This is the measurement. The marine archive carries a **real Swell partition per model**, and
from mid-2024 every one of the three organisations reports it — so the gate can be scored
against the same rule, the same thresholds and the same `agreement_of` the Pipeline Run uses,
over two Big-Wave Seasons of real weather rather than one flat summer sample.

**The real gate, not a copy of it.** `HeuristicBaseline`, `spread.derive`, `decide` and
`pipeline.agreement_at` are all imported from the running system, for the reason
`analysis/backtest/` gives: a reimplementation drifts from the thing it claims to measure, and
the drift shows up as a report about a rule nobody ships.

## Two limits on what the number below means

**It is a lower bound, and the direction is known.** The archive's per-model value for a past
hour is that model's settled reading of it — near enough an analysis. A real Go Call is issued
two to seven days ahead, and `alignment.py` measures provider spread growing with Lead Time:
0.446 m at one day against 0.652 m at six, on Combined Sea. The models divide *more* when a
call is actually issued than they do here, so the gate withholds more in production than this
reports.

**The wind is ERA5's, 9.6 km inshore.** The same series and the same caveat
`analysis/backtest/README.md` records, and it matters here only for deciding which hours would
have earned a Go Call at all — never for the gate itself, which reads swell period.

Run, from the repository root:

    .venv/Scripts/python.exe analysis/model_spread/agreement.py
    .venv/Scripts/python.exe analysis/model_spread/agreement.py --check   # arithmetic, offline
"""

from __future__ import annotations

import csv
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUTPUT = HERE / "output"

sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "analysis" / "backtest"))
sys.path.insert(0, str(ROOT / "analysis" / "forecast_error"))

from alignment import _get, _months  # noqa: E402
from backtest import (  # noqa: E402
    LEAD_TIME_DAYS,
    MODELS_ASSUMED_TO_AGREE,
    load_gold_days,
    season_of,
)
from download_runs import END  # noqa: E402
from hindcast import ARCHIVE_URL, WIND  # noqa: E402
from nazarenow.days import group_by_date  # noqa: E402
from nazarenow.decision import Status, decide, strength  # noqa: E402
from nazarenow.models.heuristic import HeuristicBaseline  # noqa: E402
from nazarenow.pipeline import agreement_at  # noqa: E402
from nazarenow.sources.open_meteo import (  # noqa: E402
    LATITUDE,
    LONGITUDE,
    MARINE_URL,
    TIMEZONE,
)
from nazarenow.spread import PROVIDERS  # noqa: E402

START = date(2024, 7, 1)
"""The first month every organisation carries a Swell partition in the archive.

Established by probing, like `WAVE_ARCHIVE_START` next door, and the boundary is NCEP's:
`swell_wave_period_ncep_gfswave025` is null for every hour of 2024-01, partial through
2024-06, and complete from 2024-07. MeteoFrance and DWD reach back years further and are not
the constraint.

Before this date the ensemble is two organisations rather than three, and a spread measured
across a different roster is not the same quantity — the reason `Spread` carries its
`providers` at all. Two Big-Wave Seasons is what the record supports, so two is what this
scores.
"""

OUR_MODEL = "best_match"
"""What the live Pipeline Run reads, and therefore what plays the part of our own forecast.

Requested in the same call as the roster so it describes the same hours from the same
response — the reason `fetch_ensemble` sends one request rather than five.
"""

OUR_SUFFIX = "marine_best_match"
"""What the provider calls it on the way back, which is not what we asked it by.

Every roster member returns under the name it was requested under; `best_match` alone comes
back as `swell_wave_period_marine_best_match`. Named rather than derived because the
alternative — picking whichever series is left over — would silently attach our own forecast
to some other model's readings the day the roster changes.
"""

MARINE_VARIABLES = ("wave_height", "swell_wave_period", "swell_wave_direction")
"""`wave_height` is the Combined Sea Significant Wave Height the height condition is written
in — CONTEXT.md holds it apart from swell height and the Heuristic Baseline reads this one."""


@dataclass(frozen=True)
class Hour:
    """One archived hour: what we would have forecast, and what each model said."""

    at: str
    readings: dict[str, float]
    members: dict[str, float]
    """Swell period per model identifier, for the models that answered this hour."""


def marine(start: date, end: date) -> dict[str, Any]:
    return _get(
        MARINE_URL,
        {
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "hourly": ",".join(MARINE_VARIABLES),
            "models": ",".join([OUR_MODEL, *PROVIDERS]),
            "timezone": TIMEZONE,
            "length_unit": "metric",
        },
        f"agreement_marine_{start:%Y_%m}",
    )


def wind(start: date, end: date) -> dict[str, Any]:
    return _get(
        ARCHIVE_URL,
        {
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "hourly": ",".join(WIND),
            "timezone": TIMEZONE,
        },
        f"agreement_wind_{start:%Y_%m}",
    )


def hours() -> list[Hour]:
    """Every archived hour both sources cover, month by month.

    An hour missing any reading the rule needs is dropped rather than filled. A gap-toothed
    hour cannot be decided, and inventing a value for one would put the invention inside the
    number this file exists to report.
    """
    found: list[Hour] = []
    for start, end in _months(START, END):
        sea = marine(start, end)["hourly"]
        air = wind(start, end)["hourly"]
        by_stamp = {stamp: index for index, stamp in enumerate(air["time"])}

        for index, stamp in enumerate(sea["time"]):
            gust = by_stamp.get(stamp)
            if gust is None:
                continue
            readings = {
                "significant_wave_height": sea[f"wave_height_{OUR_SUFFIX}"][index],
                "swell_period": sea[f"swell_wave_period_{OUR_SUFFIX}"][index],
                "swell_direction": sea[f"swell_wave_direction_{OUR_SUFFIX}"][index],
                "wind_speed": air["wind_speed_10m"][gust],
                "wind_direction": air["wind_direction_10m"][gust],
            }
            if any(value is None for value in readings.values()):
                continue
            members = {
                model: sea[f"swell_wave_period_{model}"][index]
                for model in PROVIDERS
                if sea.get(f"swell_wave_period_{model}", [None])[index] is not None
            }
            found.append(Hour(at=stamp, readings=readings, members=members))
    return found


def as_ensemble(hour: Hour) -> dict[str, dict[str, dict[str, dict[str, Any]]]]:
    """One hour's members in the shape a Pipeline Run holds them.

    Built so `pipeline.agreement_at` can be called unmodified. Rebuilding the gate's logic
    against a flatter structure would be less code here and a different rule than the one that
    ships, which is the trade this file refuses everywhere else.
    """
    return {
        hour.at: {
            model: {"swell_period": {"value": period, "unit": "s"}}
            for model, period in hour.members.items()
        }
    }


@dataclass(frozen=True)
class DayVerdict:
    """One Nazaré local day, called with the gate and without it."""

    date: str
    ungated: Status
    gated: Status

    @property
    def withheld(self) -> bool:
        """A Go Call the models refused, rather than one the conditions never supported."""
        return self.ungated in GO_TIERS and self.gated not in GO_TIERS


GO_TIERS = (Status.GO, Status.CONFIRMED)


def call_days(archived: list[Hour], model: HeuristicBaseline) -> list[DayVerdict]:
    """Decide every day twice: as the rule stood before #8's second half, and as it stands.

    Both passes take the day's strongest call, matching how a Pipeline Run reduces a day. The
    ungated pass is `MODELS_ASSUMED_TO_AGREE` — the same assumption `analysis/backtest/` makes
    — so the difference between the two columns is the gate and nothing else.
    """
    by_stamp = {hour.at: hour for hour in archived}
    verdicts: list[DayVerdict] = []

    for day, day_hours in group_by_date([{"at": hour.at} for hour in archived]).items():
        best_ungated, best_gated = Status.NONE, Status.NONE
        for stamp in (entry["at"] for entry in day_hours):
            hour = by_stamp[stamp]
            prediction = model.predict(hour.readings)
            agreement = agreement_at(model, hour.readings, as_ensemble(hour), stamp)

            ungated = decide(prediction, LEAD_TIME_DAYS, MODELS_ASSUMED_TO_AGREE)
            gated = decide(prediction, LEAD_TIME_DAYS, agreement)
            if strength(ungated.status) > strength(best_ungated):
                best_ungated = ungated.status
            if strength(gated.status) > strength(best_gated):
                best_gated = gated.status
        verdicts.append(DayVerdict(date=day, ungated=best_ungated, gated=best_gated))

    return verdicts


@dataclass(frozen=True)
class SeasonCost:
    season: str
    days: int
    go_ungated: int
    go_gated: int
    withheld: int

    @property
    def share_withheld(self) -> float:
        return self.withheld / self.go_ungated if self.go_ungated else 0.0


def cost_per_season(verdicts: list[DayVerdict]) -> list[SeasonCost]:
    """The gate's price, split by Big-Wave Season and reported over the whole span.

    Split because a season is the unit both budgets in `analysis/calibration/` are stated in,
    and because a gate that bites in one season and not the next is a different finding from
    one that bites evenly.
    """
    seasons = sorted({season_of(verdict.date) for verdict in verdicts})
    rows = [
        _cost(season, [v for v in verdicts if season_of(v.date) == season]) for season in seasons
    ]
    return [*rows, _cost("all", verdicts)]


def _cost(season: str, verdicts: list[DayVerdict]) -> SeasonCost:
    return SeasonCost(
        season=season,
        days=len(verdicts),
        go_ungated=sum(1 for v in verdicts if v.ungated in GO_TIERS),
        go_gated=sum(1 for v in verdicts if v.gated in GO_TIERS),
        withheld=sum(1 for v in verdicts if v.withheld),
    )


def gold_day_effect(verdicts: list[DayVerdict]) -> list[tuple[str, Status, Status]]:
    """What the gate does to the documented XXL Days inside the span.

    Reported as a list rather than a recall figure. Only two Gold Days fall in the span the
    ensemble covers, and two is not a rate — quoting "2 of 2 survive" as recall would be the
    kind of number this project keeps having to withdraw.
    """
    gold = load_gold_days()
    return [
        (verdict.date, verdict.ungated, verdict.gated)
        for verdict in verdicts
        if verdict.date in gold
    ]


def write_csv(rows: list[SeasonCost]) -> Path:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / "agreement.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["season", "days_scored", "go_days_ungated", "go_days_gated", "withheld", "share"]
        )
        for row in rows:
            writer.writerow(
                [
                    row.season,
                    row.days,
                    row.go_ungated,
                    row.go_gated,
                    row.withheld,
                    f"{row.share_withheld:.3f}",
                ]
            )
    return path


def check() -> int:
    """Self-test the reduction and the gate, offline, on hours whose answer is known by hand.

    Every case is a day whose ungated call is a Go Call, so each isolates what the gate does
    rather than what the rule does. The shipped Go Call bar is read from the same threshold
    file the rule reads, so this cannot drift from a recalibration into testing nothing.
    """
    model = HeuristicBaseline()
    bar = model.thresholds.go_call_minimum_swell_period_s
    clean = {
        "significant_wave_height": 5.0,
        "swell_period": bar + 3.0,
        "swell_direction": 300.0,
        "wind_speed": 18.0,
        "wind_direction": 90.0,
    }

    def day(name: str, members: dict[str, float]) -> DayVerdict:
        archived = [
            Hour(at=f"{name}T{hour:02d}:00", readings=clean, members=members) for hour in range(24)
        ]
        return call_days(archived, model)[0]

    # Every organisation well clear of the bar.
    unanimous = day("2026-01-01", {model: bar + 3.0 for model in PROVIDERS})
    # DWD alone below it — one organisation is enough to withhold, which is the whole point
    # of a rule written on the lowest opinion rather than on the average one.
    divided = day(
        "2026-01-02",
        {**{m: bar + 3.0 for m in PROVIDERS}, "dwd_ewam": bar - 0.1, "dwd_gwam": bar - 0.1},
    )
    # One organisation reporting is not an ensemble agreeing with itself.
    alone = day("2026-01-03", {"meteofrance_wave": bar + 3.0})

    failures = []
    for name, verdict, expected in (
        ("unanimous", unanimous, Status.GO),
        ("divided", divided, Status.WATCH),
        ("one organisation", alone, Status.WATCH),
    ):
        if verdict.ungated is not Status.GO:
            failures.append(f"{name}: the ungated rule should issue a Go Call here")
        if verdict.gated is not expected:
            failures.append(f"{name}: gated call is {verdict.gated}, expected {expected}")

    if divided.withheld is not True or unanimous.withheld is not False:
        failures.append("`withheld` does not distinguish a refused Go Call from an unearned one")

    for failure in failures:
        print(f"  FAIL {failure}")
    print("agreement.py --check:", "FAILED" if failures else "ok")
    return 1 if failures else 0


def main() -> int:
    if "--check" in sys.argv:
        return check()

    archived = hours()
    print(f"{len(archived)} archived hours, {archived[0].at} to {archived[-1].at}")
    # Both counts, because they are different facts and only the second one bears on the
    # spread. Finding 4 rests on the organisation count staying at three while members come
    # and go, and a report showing only the member count would leave that unevidenced here.
    models = Counter(len(hour.members) for hour in archived)
    organisations = Counter(len({PROVIDERS[m] for m in hour.members}) for hour in archived)
    print(f"  models per hour:        {dict(sorted(models.items()))}")
    print(f"  organisations per hour: {dict(sorted(organisations.items()))}")

    verdicts = call_days(archived, HeuristicBaseline())
    rows = cost_per_season(verdicts)

    print("\n  season   days   Go days   with the gate   withheld")
    for row in rows:
        print(
            f"  {row.season:8s} {row.days:5d} {row.go_ungated:9d} "
            f"{row.go_gated:15d} {row.withheld:10d}  ({row.share_withheld:.1%})"
        )

    print("\n  Gold Days inside the span:")
    for day, ungated, gated in gold_day_effect(verdicts):
        print(f"    {day}  {ungated.value:9s} -> {gated.value}")

    print(f"\nWrote {write_csv(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

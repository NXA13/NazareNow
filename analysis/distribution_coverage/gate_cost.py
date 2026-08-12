"""What the height-probability gate costs, in Go Call days rather than in hours.

Ticket #96. `decide` withholds a Go Call when `height_bar_probability` falls under
`GO_CALL_MINIMUM_HEIGHT_PROBABILITY`. `coverage.py` scored that gate by the hour and found the
bin immediately below the floor is a band in which **every hour cleared the height bar**, at
every Lead Time. It then said, in as many words, that this is not a count of lost Go Calls and
must not be read as one: the height condition is one of several, and hours are not days.

This is the count. Same archive, same shipped budget, same model, grouped into the unit a
Traveller acts on.

**Why the number was missing rather than merely unpublished.** `analysis/backtest/` scores the
rule against a Hindcast and passes `decide` no distribution at all, so the gate never fires there
— correctly, because what the ocean did carries no forecast error, and scoring it must not
silently become stricter than the rule it is scoring. But that left the published Go Call figures
a ceiling in a respect the sister gate states plainly and this one did not:
`MODELS_ASSUMED_TO_AGREE` is a named constant with a docstring, and `analysis/model_spread/`
measures what the agreement gate costs in days. This file is that measurement for the other gate.

## The one control that makes the two arms comparable

**Both arms assume the wave models agree.** The archived runs carry `best_match` only, with no
per-model roster, so agreement is no more measurable here than in the backtest — and holding it
at `AGREED` on both sides is what makes the difference between the two counts *only* the height
gate. Passing anything else would fold the agreement gate's cost into a number reported as this
gate's.

**A distribution is priced exactly where the Pipeline Run prices one** — on the hours already
clearing every other Go Call condition, which is the only branch `_height_probable_enough`
gates. Doing it everywhere would be correct and slow, and would still change no call.

## Two scopes, because the archive is not all winter

The archive runs **2025-11-16 to 2026-07-31**. That is a partial Big-Wave Season followed by four
months of summer, and CONTEXT.md is clear that an XXL Day is a winter event — so a rate over all
258 days would divide a winter numerator by a denominator that cannot contribute to it. Every row
is therefore reported twice, `all` and `Oct-Mar only`, exactly as `agreement.py`'s
`cost_per_season` does and for the reason it gives: an overcounted denominator stated as a fact
is worse than no rate at all.

## What the number is not

**Not a recall, and not a precision.** The in-season window holds a single confirmed giant day,
2025-12-13. A day count is what this can honestly report. Whether the gate is *right* to withhold
is a different question and belongs to #82, which is parked; nothing here moves the floor.

**Not a marginal cost either.** The ungated count is itself agreement-free, because both arms
hold agreement at `AGREED`. Under the live system the agreement gate runs first, so a day this
one reports as withheld may already have been withheld by the forecasters disagreeing — in which
case the height gate costs nothing further on it. What is measured is this gate's cost *given
the models agree*, which is the only form of it the archive can answer.

**A lower bound on the live cost, for the same reason `coverage.py` gives.** Every distribution
here is built with `model_spread=None`, because no per-Lead-Time ensemble archive exists, and the
ensemble term can only widen a distribution. A wider distribution puts less mass past the height
bar, so the running system's probabilities are lower than these and its gate withholds at least
as often.

Run, from the repository root:

    .venv/Scripts/python.exe analysis/distribution_coverage/gate_cost.py
    .venv/Scripts/python.exe analysis/distribution_coverage/gate_cost.py --check   # offline

"""

from __future__ import annotations

import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = HERE / "output"

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "analysis" / "backtest"))
sys.path.insert(0, str(ROOT / "analysis" / "forecast_error"))
sys.path.insert(0, str(ROOT / "backend" / "src"))

from backtest import in_big_wave_season  # noqa: E402
from coverage import readings_at  # noqa: E402
from download_runs import LEAD_TIMES, Runs, waves, wind  # noqa: E402
from nazarenow.days import group_by_date  # noqa: E402
from nazarenow.decision import (  # noqa: E402
    Agreement,
    Status,
    decide,
    go_call_is_available,
    strength,
)
from nazarenow.distribution import ErrorBudget  # noqa: E402
from nazarenow.models.base import AmplificationModel  # noqa: E402
from nazarenow.pipeline import amplification_model  # noqa: E402
from nazarenow.thresholds import load as load_thresholds  # noqa: E402
from settled import settled  # noqa: E402

GOLD = ROOT / "analysis" / "gold_days" / "gold_days.jsonl"
"""The confirmed giant days, read straight from the curated file.

One JSON object per line, and the only field needed is the date.
"""

MODELS_ASSUMED_TO_AGREE = Agreement.AGREED
"""Held on **both** arms, which is the whole reason the difference below is this gate's.

The same assumption `analysis/backtest/` names and for a narrower reason: these archived runs
carry `best_match` alone, so there is no roster here to disagree. Letting agreement vary between
the two arms would report the sum of two gates as the cost of one.
"""

ALL_DAYS = "all"
IN_SEASON = "Oct-Mar only"
"""The two denominators, under `agreement.py`'s own names so the two reports read alike."""

OUTPUT_NAME = "gate_day_cost.csv"


@dataclass(frozen=True)
class Archive:
    """The three archived series one decision reads, kept together because they are one thing.

    They are always loaded together, always passed together, and an hour missing from any of
    them cannot be decided at all — which is a type wanting to exist rather than three
    parameters that happen to travel.
    """

    sea: Runs
    winds: Runs
    swell: dict[str, dict[str, float]]


@dataclass(frozen=True)
class Pricing:
    """What turns an hour into a call: the shipped budget, the shipped model, the shipped bar.

    All three are read from the running system rather than rebuilt, for the reason
    `analysis/backtest/` gives about the rule itself — a reimplementation drifts from the thing
    it claims to measure, and the drift is reported as a finding.
    """

    budget: ErrorBudget
    model: AmplificationModel
    height_bar_m: float

    def call(self, features: dict[str, float], lead: int, *, gated: bool) -> Status:
        """The status this hour earns, with the height gate applied or bypassed.

        The two arms differ in this argument and in nothing else. `gated=False` passes no
        distribution, which is exactly what `analysis/backtest/` does and what
        `_height_probable_enough` reads as "nothing to be uncertain about".
        """
        prediction = self.model.predict(features)
        distribution = (
            self.budget.distribution(self.model, features, lead, height_bar_m=self.height_bar_m)
            # Priced exactly where a Pipeline Run prices one: the hours already clearing every
            # other Go Call condition, which is the only branch this gate can change.
            if gated and go_call_is_available(prediction, lead)
            else None
        )
        return decide(prediction, lead, MODELS_ASSUMED_TO_AGREE, distribution).status


@dataclass(frozen=True)
class DayVerdict:
    """One day at one Lead Time, under both arms.

    Pairing the arms per **day** rather than per Lead Time is what lets `withheld` be a property
    rather than a subtraction of two counts computed apart — and a subtraction cannot name the
    date it lost, which is the figure worth reading.
    """

    date: str
    ungated: Status
    gated: Status

    @property
    def withheld(self) -> bool:
        return self.ungated is Status.GO and self.gated is not Status.GO


@dataclass(frozen=True)
class DayCost:
    """One Lead Time over one denominator: the Go Call days each arm admits."""

    lead: int
    scope: str
    days_scored: int
    go_days_ungated: int
    go_days_gated: int
    confirmed_days_ungated: int
    confirmed_days_gated: int
    """Days whose best call was Confirmed. Recorded for both arms, and the reason the shortest
    Lead Time shows no Go Calls at all rather than showing a gap.

    **Two separate mechanisms, and they are easy to conflate.** The shortest Lead Time has no Go
    Calls because the tier does not exist there: `go_call_is_available` requires
    `CONFIRMED_THROUGH < lead_time_days`, and `CONFIRMED_THROUGH` is 1, so at one day out no
    hour is a Go Call candidate at all and the gate has nothing to act on. Separately, the gate
    can never *reduce* a Confirmed at any Lead Time, because `decide` assigns that status in a
    branch that does not consult `probable`.

    `--check` pins the two counts equal, which is the second mechanism. If the probability check
    ever reaches the Confirmed branch, this gate would start withholding a statement made to
    someone already travelling, and the pin is what would say so.
    """

    gold_days_scored: int
    gold_days_ungated: int
    gold_days_gated: int
    withheld_dates: tuple[str, ...]
    """Every date the gate took, listed rather than counted. A count answers "how much" and a
    list answers "which", and only the second can be held against the Gold Day list."""

    @property
    def days_withheld(self) -> int:
        return len(self.withheld_dates)


def gold_days() -> set[str]:
    lines = GOLD.read_text(encoding="utf-8").splitlines()
    return {json.loads(line)["date"] for line in lines if line.strip()}


def strongest(statuses: list[Status]) -> Status:
    """The day's call: the best any of its hours earned.

    `analysis/backtest/` ranks a day the same way. The tie-breaks the Pipeline Run applies
    within a status do not matter here — this asks only which tier the day reached, and
    `strength` is the ordering that answers it.
    """
    best = Status.NONE
    for status in statuses:
        if strength(status) > strength(best):
            best = status
    return best


def verdicts_at(lead: int, archive: Archive, pricing: Pricing) -> list[DayVerdict]:
    """Both arms over every archived day, at one Lead Time."""
    verdicts = []
    for day, stamps in group_by_date([{"at": hour} for hour in sorted(archive.swell)]).items():
        gated: list[Status] = []
        ungated: list[Status] = []
        for stamp in stamps:
            features = readings_at(stamp["at"], lead, archive.sea, archive.winds, archive.swell)
            if features is None:
                continue
            gated.append(pricing.call(features, lead, gated=True))
            ungated.append(pricing.call(features, lead, gated=False))
        if not gated:
            continue
        verdicts.append(DayVerdict(date=day, ungated=strongest(ungated), gated=strongest(gated)))

    # The gate withholds; it cannot grant. A day reaching a Go Call under the gate that the
    # ungated arm did not reach means the two arms are not the same rule, which is a wiring
    # fault rather than a finding, and it must stop the run.
    gained = [
        verdict.date
        for verdict in verdicts
        if verdict.gated is Status.GO and verdict.ungated is not Status.GO
    ]
    if gained:
        raise RuntimeError(
            f"lead {lead}: the height gate produced Go Calls the ungated rule did not reach "
            f"({gained}). It can only withhold, so the two arms are not the same rule"
        )
    return verdicts


def cost(lead: int, scope: str, verdicts: list[DayVerdict], gold: set[str]) -> DayCost:
    def days(status: Status, *, gated: bool) -> set[str]:
        return {
            verdict.date
            for verdict in verdicts
            if (verdict.gated if gated else verdict.ungated) is status
        }

    go_gated = days(Status.GO, gated=True)
    go_ungated = days(Status.GO, gated=False)
    scored = {verdict.date for verdict in verdicts}

    return DayCost(
        lead=lead,
        scope=scope,
        days_scored=len(scored),
        go_days_ungated=len(go_ungated),
        go_days_gated=len(go_gated),
        confirmed_days_ungated=len(days(Status.CONFIRMED, gated=False)),
        confirmed_days_gated=len(days(Status.CONFIRMED, gated=True)),
        gold_days_scored=len(scored & gold),
        gold_days_ungated=len(go_ungated & gold),
        gold_days_gated=len(go_gated & gold),
        withheld_dates=tuple(sorted(verdict.date for verdict in verdicts if verdict.withheld)),
    )


COLUMNS = (
    "lead_days",
    "scope",
    "days_scored",
    "go_days_ungated",
    "go_days_gated",
    "days_withheld",
    "confirmed_days_ungated",
    "confirmed_days_gated",
    "gold_days_scored",
    "gold_days_ungated",
    "gold_days_gated",
    "withheld_dates",
)


def write(rows: list[DayCost]) -> Path:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / OUTPUT_NAME
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(COLUMNS)
        for row in rows:
            writer.writerow(
                [
                    row.lead,
                    row.scope,
                    row.days_scored,
                    row.go_days_ungated,
                    row.go_days_gated,
                    row.days_withheld,
                    row.confirmed_days_ungated,
                    row.confirmed_days_gated,
                    row.gold_days_scored,
                    row.gold_days_ungated,
                    row.gold_days_gated,
                    " ".join(row.withheld_dates),
                ]
            )
    return path


def report(rows: list[DayCost], scope: str) -> None:
    print(f"\n{scope}")
    print(f"{'lead':>5}  {'days':>5}  {'Go ungated':>11}  {'Go gated':>9}  {'withheld':>8}  gold")
    for row in (row for row in rows if row.scope == scope):
        print(
            f"{row.lead:>4}d  {row.days_scored:>5}  {row.go_days_ungated:>11}  "
            f"{row.go_days_gated:>9}  {row.days_withheld:>8}  "
            f"{row.gold_days_gated}/{row.gold_days_ungated} of {row.gold_days_scored}"
            + (f"   confirmed {row.confirmed_days_gated}" if row.confirmed_days_gated else "")
        )


def main() -> int:
    thresholds = load_thresholds()
    pricing = Pricing(
        budget=ErrorBudget.shipped(),
        model=amplification_model(),
        height_bar_m=thresholds.minimum_significant_wave_height_m,
    )
    gold = gold_days()

    print(f"Pricing the height gate: model {pricing.model.name}, bar {pricing.height_bar_m} m")
    archive = Archive(sea=waves(), winds=wind(), swell=settled())
    dates = sorted({hour[:10] for hour in archive.swell})
    print(f"Archive spans {dates[0]} to {dates[-1]} ({len(dates)} days)")

    rows = []
    for lead in LEAD_TIMES:
        verdicts = verdicts_at(lead, archive, pricing)
        rows.append(cost(lead, ALL_DAYS, verdicts, gold))
        rows.append(
            cost(lead, IN_SEASON, [v for v in verdicts if in_big_wave_season(v.date)], gold)
        )

    for scope in (ALL_DAYS, IN_SEASON):
        report(rows, scope)

    taken = sorted({date for row in rows for date in row.withheld_dates})
    print(f"\nDates the gate took at any Lead Time: {', '.join(taken) if taken else 'none'}")
    print(f"Wrote {write(rows).relative_to(ROOT)}")
    return 0


def check() -> int:
    """Re-check the committed table offline. No archive, no network, no credentials.

    It cannot re-derive the distributions — that needs the archive — so it pins the properties
    a wrong table would break rather than the values themselves.
    """
    failures: list[str] = []

    def expect(label: str, condition: bool, detail: str) -> None:
        if not condition:
            failures.append(f"{label}: {detail}")

    path = OUTPUT / OUTPUT_NAME
    if not path.exists():
        print(f"{path.relative_to(ROOT)} is missing; run gate_cost.py first")
        return 1

    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    for scope in (ALL_DAYS, IN_SEASON):
        expect(
            f"{scope} leads",
            {int(row["lead_days"]) for row in rows if row["scope"] == scope} == set(LEAD_TIMES),
            "the table does not cover exactly the archive's Lead Times",
        )

    by_key = {(int(row["lead_days"]), row["scope"]): row for row in rows}

    for row in rows:
        where = f"lead {row['lead_days']} ({row['scope']})"
        ungated, gated = int(row["go_days_ungated"]), int(row["go_days_gated"])
        withheld = int(row["days_withheld"])
        named = [date for date in row["withheld_dates"].split(" ") if date]

        # The gate withholds. A table where it grants is a table with its arms swapped, and
        # every figure on it would read as the opposite of what it measures.
        expect(
            f"{where} direction",
            gated <= ungated,
            f"the gated arm admits {gated} Go Call days against the ungated arm's {ungated}",
        )
        expect(
            f"{where} arithmetic",
            withheld == ungated - gated,
            f"days_withheld is {withheld} where the two arms differ by {ungated - gated}",
        )
        expect(
            f"{where} named dates",
            len(named) == withheld,
            f"{len(named)} date(s) named against {withheld} withheld",
        )
        expect(
            f"{where} gold subset",
            int(row["gold_days_gated"]) <= int(row["gold_days_ungated"]) <= ungated,
            "the Gold Day counts are not a subset of the Go Call days they are drawn from",
        )
        expect(
            f"{where} scored",
            ungated <= int(row["days_scored"]),
            f"{ungated} Go Call days out of {row['days_scored']} scored",
        )

        # The gate cannot reach a Confirmed statement: `decide` assigns that status in a branch
        # that never consults `probable`. If this stops holding, the gate has begun withholding
        # advice given to someone already travelling — a different decision from the one this
        # file measures, and one nobody made.
        expect(
            f"{where} confirmed untouched",
            row["confirmed_days_gated"] == row["confirmed_days_ungated"],
            f"the gate moved the Confirmed count from {row['confirmed_days_ungated']} to "
            f"{row['confirmed_days_gated']}; it is assigned before the probability is read",
        )

        # Every in-season figure is drawn from the same days as its `all` row, so none of them
        # can exceed it. A larger in-season count is a scope filter applied to the wrong set.
        if row["scope"] == IN_SEASON:
            everything = by_key[(int(row["lead_days"]), ALL_DAYS)]
            for column in COLUMNS:
                if column in ("lead_days", "scope", "withheld_dates"):
                    continue
                expect(
                    f"{where} {column}",
                    int(row[column]) <= int(everything[column]),
                    f"in-season {column} is {row[column]} against {everything[column]} overall",
                )

    for failure in failures:
        print(f"  FAIL {failure}")
    print(f"{'ok' if not failures else 'FAILED'} - {len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(check() if "--check" in sys.argv[1:] else main())

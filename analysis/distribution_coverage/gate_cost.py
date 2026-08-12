"""What the height-probability gate costs, in Go Call days rather than in hours.

Ticket #96. `decide` withholds a Go Call when `height_bar_probability` falls under
`GO_CALL_MINIMUM_HEIGHT_PROBABILITY`. `coverage.py` scored that gate by the hour and found the
0.6–0.7 bin — withheld, since the floor is 0.70 — is a band in which **every hour cleared the
height bar**, at every Lead Time. It then said, in as many words, that this is not a count of
lost Go Calls and must not be read as one: the height condition is one of several, and hours are
not days.

This is the count. Same archive, same shipped budget, same model, grouped into the unit a
Traveller acts on.

**Why the number was missing rather than merely unpublished.** `analysis/backtest/` scores the
rule against a Hindcast and passes `decide` no distribution at all, so the gate never fires there
— correctly, because what the ocean did carries no forecast error, and scoring it must not
silently become stricter than the rule it is scoring. But that leaves the published Go Call
figures a ceiling in a respect the sister gate states plainly and this one did not:
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

## What the number is not

**Not a recall, and not a precision.** The archive runs 2025-11-26 to 2026-02-20: one partial
Big-Wave Season holding a single confirmed giant day, 2025-12-13. A day count is what this can
honestly report. Whether the gate is *right* to withhold is a different question and belongs to
#82, which is parked; nothing here moves the floor.

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
sys.path.insert(0, str(ROOT / "analysis" / "forecast_error"))
sys.path.insert(0, str(ROOT / "backend" / "src"))

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

Read here rather than imported from `analysis/backtest/backtest.py`, whose module-level imports
pull in the Hindcast and reanalysis loaders this measurement has no use for. The file is one
JSON object per line and the only field needed is the date.
"""

MODELS_ASSUMED_TO_AGREE = Agreement.AGREED
"""Held on **both** arms, which is the whole reason the difference below is this gate's.

The same assumption `analysis/backtest/` names and for a narrower reason: these archived runs
carry `best_match` alone, so there is no roster here to disagree. Letting agreement vary between
the two arms would report the sum of two gates as the cost of one.
"""

OUTPUT_NAME = "gate_day_cost.csv"


@dataclass(frozen=True)
class DayCost:
    """One Lead Time: the Go Call days each arm admits, and the Gold Days among them."""

    lead: int
    days_scored: int
    go_days_ungated: int
    go_days_gated: int
    confirmed_days_ungated: int
    confirmed_days_gated: int
    """Days whose best call was Confirmed, which the gate cannot touch — and the reason the
    shortest Lead Time shows no Go Calls at all rather than showing a gap.

    `decide` assigns `Status.CONFIRMED` in the branch above the one that consults `probable`,
    so a day inside `CONFIRMED_THROUGH` that holds every Go condition is Confirmed whatever the
    distribution says. Both arms are recorded anyway, and `--check` pins them equal: if the
    probability check ever moves above that branch, this gate would start withholding a
    statement made to someone already travelling, and the pin is what would say so.
    """

    gold_days_scored: int
    gold_days_ungated: int
    gold_days_gated: int
    withheld_dates: tuple[str, ...]
    """Every date the gate took, listed rather than counted.

    A count answers "how much" and a list answers "which", and only the second can be held up
    against the Gold Day list or read for a pattern. There are few enough to name.
    """

    @property
    def days_withheld(self) -> int:
        return self.go_days_ungated - self.go_days_gated

    @property
    def gold_days_withheld(self) -> int:
        return self.gold_days_ungated - self.gold_days_gated


def gold_days() -> set[str]:
    lines = GOLD.read_text(encoding="utf-8").splitlines()
    return {json.loads(line)["date"] for line in lines if line.strip()}


def strongest(statuses: list[Status]) -> Status:
    """The day's call: the best any of its hours earned.

    `analysis/backtest/` ranks a day the same way. The tie-breaks the Pipeline Run applies
    within a status do not matter here — this asks only whether the day reached a Go Call, and
    `strength` is the ordering that answers it.
    """
    best = Status.NONE
    for status in statuses:
        if strength(status) > strength(best):
            best = status
    return best


def cost_at(
    lead: int,
    budget: ErrorBudget,
    model: AmplificationModel,
    sea: Runs,
    winds: Runs,
    swell: dict[str, dict[str, float]],
    height_bar_m: float,
    gold: set[str],
) -> DayCost:
    """Both arms over every archived day, at one Lead Time."""
    gated: dict[str, list[Status]] = {}
    ungated: dict[str, list[Status]] = {}

    by_date = group_by_date([{"at": hour} for hour in sorted(swell)])
    for day, stamps in by_date.items():
        for stamp in stamps:
            hour = stamp["at"]
            features = readings_at(hour, lead, sea, winds, swell)
            if features is None:
                continue
            prediction = model.predict(features)

            # Priced exactly where a Pipeline Run prices one: the hours already clearing every
            # other Go Call condition, which is the only branch this gate can change.
            distribution = (
                budget.distribution(model, features, lead, height_bar_m=height_bar_m)
                if go_call_is_available(prediction, lead)
                else None
            )
            gated.setdefault(day, []).append(
                decide(prediction, lead, MODELS_ASSUMED_TO_AGREE, distribution).status
            )
            ungated.setdefault(day, []).append(
                decide(prediction, lead, MODELS_ASSUMED_TO_AGREE, None).status
            )

    days = sorted(gated)
    with_gate = {day for day in days if strongest(gated[day]) is Status.GO}
    without_gate = {day for day in days if strongest(ungated[day]) is Status.GO}
    confirmed_gated = {day for day in days if strongest(gated[day]) is Status.CONFIRMED}
    confirmed_ungated = {day for day in days if strongest(ungated[day]) is Status.CONFIRMED}

    # The gate can only ever take a Go Call away. One appearing under the gate that the
    # ungated arm did not reach is a wiring fault, not a finding, and must stop the run.
    gained = with_gate - without_gate
    if gained:
        raise RuntimeError(
            f"lead {lead}: the height gate produced Go Calls the ungated rule did not reach "
            f"({sorted(gained)}). It can only withhold, so the two arms are not the same rule"
        )

    scored = set(days)
    return DayCost(
        lead=lead,
        days_scored=len(scored),
        go_days_ungated=len(without_gate),
        go_days_gated=len(with_gate),
        confirmed_days_ungated=len(confirmed_ungated),
        confirmed_days_gated=len(confirmed_gated),
        gold_days_scored=len(scored & gold),
        gold_days_ungated=len(without_gate & gold),
        gold_days_gated=len(with_gate & gold),
        withheld_dates=tuple(sorted(without_gate - with_gate)),
    )


def write(rows: list[DayCost]) -> Path:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / OUTPUT_NAME
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "lead_days",
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
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.lead,
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


def report(rows: list[DayCost]) -> None:
    print(
        f"\n{'lead':>5}  {'days':>5}  {'Go ungated':>11}  {'Go gated':>9}  "
        f"{'withheld':>8}  {'confirmed':>9}  gold"
    )
    for row in rows:
        print(
            f"{row.lead:>4}d  {row.days_scored:>5}  {row.go_days_ungated:>11}  "
            f"{row.go_days_gated:>9}  {row.days_withheld:>8}  "
            f"{row.confirmed_days_gated:>9}  "
            f"{row.gold_days_gated}/{row.gold_days_ungated} of {row.gold_days_scored}"
        )
    taken = sorted({date for row in rows for date in row.withheld_dates})
    print(f"\nDates the gate took at any Lead Time: {', '.join(taken) if taken else 'none'}")


def main() -> int:
    thresholds = load_thresholds()
    height_bar_m = thresholds.minimum_significant_wave_height_m
    budget = ErrorBudget.shipped()
    model = amplification_model()
    gold = gold_days()

    print(f"Pricing the height gate: model {model.name}, height bar {height_bar_m} m")
    sea, winds, swell = waves(), wind(), settled()

    rows = [
        cost_at(lead, budget, model, sea, winds, swell, height_bar_m, gold) for lead in LEAD_TIMES
    ]
    report(rows)
    print(f"\nWrote {write(rows).relative_to(ROOT)}")
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

    expect(
        "leads",
        {int(row["lead_days"]) for row in rows} == set(LEAD_TIMES),
        "the table does not cover exactly the archive's Lead Times",
    )

    for row in rows:
        where = f"lead {row['lead_days']}"
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

        # The gate cannot reach a Confirmed statement: `decide` assigns that status in the
        # branch above the one consulting `probable`. If this ever stops holding, the gate has
        # begun withholding advice given to someone already travelling — a different decision
        # from the one this file measures, and one nobody made.
        expect(
            f"{where} confirmed untouched",
            row["confirmed_days_gated"] == row["confirmed_days_ungated"],
            f"the gate moved the Confirmed count from {row['confirmed_days_ungated']} to "
            f"{row['confirmed_days_gated']}; it is assigned before the probability is read",
        )

    for failure in failures:
        print(f"  FAIL {failure}")
    print(f"{'ok' if not failures else 'FAILED'} - {len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(check() if "--check" in sys.argv[1:] else main())

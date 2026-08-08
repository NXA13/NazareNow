"""What `GO_CALL_CONFIDENCE` costs, priced against the Gold Days it can refuse.

Ticket #15. The Decision Model withholds a Go Call when too little of the incoming reading's
Predictive Distribution clears the calibrated height bar. That floor is a bar like any other
in this project, and it was the only one carrying no measurement — shipped at 0.9 on the
belief that it was inert on the days that matter.

It was not inert, and the belief rested on measuring the wrong quantity. The probability had
been read off the Amplification Model's *output* against a bar that judges the *incoming
reading*; because the model amplifies, every marginal day looked further clear of the bar than
it was. Corrected, 0.9 takes the Go Call from 7 of the 37 Gold Days the height bar admits.

This prices it the way ADR 0010 priced the Watch bar: state what the tier is allowed to cost,
then take the strictest bar that fits the budget. **The budget is that it may cost no Gold
Day.** A rule meant to stop somebody booking a flight on a coin flip must not also stop them
booking one on a day the ocean actually delivered.

**Half of the pricing, and the half that is possible.** ADR 0010 could score the Watch bar in
both directions because the Hindcast supplies outcomes. It contains no forecast error, so how
many *false* Go Calls this floor prevents cannot be scored the same way — that needs a forecast
archive deeper than the one Big-Wave Season beginning 2025-11-16. What is measurable is recall,
and recall is the direction that can lose a Gold Day.

Run, from the repository root:

    .venv/Scripts/python.exe analysis/forecast_error/confidence.py
    .venv/Scripts/python.exe analysis/forecast_error/confidence.py --check

No credentials, no network. Reads the Gold Days, the reanalysis Hindcast the calibration runs
on, and the shipped `forecast_error.json`. The table lands in `output/`.
"""

from __future__ import annotations

import csv
import math
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "analysis" / "calibration"))
sys.path.insert(0, str(ROOT / "backend" / "src"))

import calibrate  # noqa: E402
from nazarenow.decision import GO_CALL_CONFIDENCE  # noqa: E402
from nazarenow.distribution import ErrorBudget  # noqa: E402
from nazarenow.thresholds import load as load_thresholds  # noqa: E402

OUTPUT = Path(__file__).resolve().parent / "output"

STEP = 0.05
"""What the chosen floor is rounded down to.

Following `calibrate.fit_height`, which floors the height bar rather than setting it exactly on
the smallest Gold Day: a bar sitting precisely on the binding day is fitted to that one day,
and the next Gold Day slightly smaller falls straight through it.
"""


@dataclass(frozen=True)
class GoldDay:
    """One Gold Day's own sea, in the units the running system reads."""

    split: str
    date: str
    reanalysis_m: float
    operational_m: float


def gold_day_peaks() -> list[GoldDay]:
    """Every Gold Day's peak Combined Sea, restated into operational units.

    The Hindcast is Copernicus IBI (ADR 0011) and the running system reads Open-Meteo, so the
    peaks are carried across by the same Translation `calibrate.translate` ships the bars
    through. Comparing a reanalysis peak against an operational bar directly would be the
    units conflation the Translations exist to prevent.
    """
    translation = calibrate.measure.fit_translations()["significant_wave_height_m"]
    gold = calibrate.load_gold_days()
    hours = calibrate.reanalysis_hours()
    splits = (
        calibrate.Split(
            "fitting", calibrate.FIT_SPAN, calibrate.split_hours(hours, calibrate.FIT_SEASONS), gold
        ),
        calibrate.Split(
            "held-out",
            calibrate.TEST_SPAN,
            calibrate.split_hours(hours, calibrate.TEST_SEASONS),
            gold,
        ),
    )

    found: list[GoldDay] = []
    for split in splits:
        for day, day_hours in calibrate.group_by_date(split.hours).items():
            if day not in split.gold:
                continue
            peak = max(float(hour["significant_wave_height"]) for hour in day_hours)
            found.append(GoldDay(split.name, day, peak, translation.apply(peak)))
    return sorted(found, key=lambda found: found.operational_m)


def clears_the_bar(sea: float, lead_time_days: int, budget: ErrorBudget, bar: float) -> float:
    """The chance a forecast reading `sea` describes a day that truly clears `bar`.

    The same normal `ErrorBudget.distribution` draws its input side from — the measured drift
    for this Lead Time and regime, widened by the Translation residual, centred on the reading
    after the measured bias correction. Evaluated analytically rather than sampled, because a
    floor being chosen to two decimals should not be read off five hundred draws of noise.

    The ensemble term is deliberately absent. It is measured live from the wave models and no
    archived value exists for a Gold Day in 2016, and it can only ever *widen* — so leaving it
    out states the narrowest case, which is the optimistic direction. A floor priced here is
    therefore priced against the best the forecast can look, and the days it admits it would
    still admit with a wider one only if the ensemble agreed.
    """
    band = budget.forecast.at(lead_time_days)
    if band is None:
        raise ValueError(f"no measured profile at {lead_time_days} days")
    measured = band.for_sea(sea)
    sigma = math.hypot(measured.noise, budget.translation_rmse)
    centre = sea - measured.bias
    return 0.5 * math.erfc((bar - centre) / (sigma * math.sqrt(2)))


def price(days: list[GoldDay], budget: ErrorBudget, bar: float) -> tuple[float, list[GoldDay]]:
    """The strictest floor costing no eligible Gold Day, and the days that set it.

    A Gold Day whose own peak sits *below* the height bar is excluded rather than counted as
    lost. It earns no Go Call at any confidence, because the height condition already refuses
    it — charging this floor for that refusal would price it for a decision it never makes.
    """
    leads = range(1, budget.forecast.measured_through_lead_days + 1)
    eligible = [day for day in days if day.operational_m >= bar]
    worst = {
        day.date: min(clears_the_bar(day.operational_m, lead, budget, bar) for lead in leads)
        for day in eligible
    }
    binding = min(worst.values())
    floor = math.floor(binding / STEP) * STEP
    return floor, [day for day in eligible if worst[day.date] == binding]


def write_csv(days: list[GoldDay], budget: ErrorBudget, bar: float) -> Path:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / "go_call_confidence.csv"
    leads = list(range(1, budget.forecast.measured_through_lead_days + 1))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["date", "split", "reanalysis_m", "operational_m", *(f"lead_{n}" for n in leads)]
        )
        for day in days:
            row = [
                ""
                if day.operational_m < bar
                else f"{clears_the_bar(day.operational_m, lead, budget, bar):.4f}"
                for lead in leads
            ]
            writer.writerow(
                [day.date, day.split, f"{day.reanalysis_m:.2f}", f"{day.operational_m:.2f}", *row]
            )
    return path


def cost_of(floor: float, days: list[GoldDay], budget: ErrorBudget, bar: float) -> int:
    """How many eligible Gold Days a floor would refuse a Go Call at some Lead Time."""
    leads = range(1, budget.forecast.measured_through_lead_days + 1)
    return sum(
        1
        for day in days
        if day.operational_m >= bar
        and min(clears_the_bar(day.operational_m, lead, budget, bar) for lead in leads) < floor
    )


def check() -> int:
    """The arithmetic, offline, with no dependency on the Hindcast download.

    Mirrors `profile.py --check`: the properties that would make the pricing wrong are the
    ones a reader cannot verify by eye, so they are asserted rather than described.
    """
    failures: list[str] = []
    budget = ErrorBudget.shipped()
    bar = load_thresholds().minimum_significant_wave_height_m

    on_the_bar = clears_the_bar(bar, 1, budget, bar)
    if not 0.45 < on_the_bar < 0.55:
        failures.append(
            f"a forecast reading exactly the bar should be near a coin flip, got {on_the_bar:.3f}"
        )

    far_clear = clears_the_bar(bar + 3.0, 7, budget, bar)
    if far_clear < 0.99:
        failures.append(f"a sea 3 m clear of the bar should be near certain, got {far_clear:.3f}")

    rising = [clears_the_bar(3.2, lead, budget, bar) for lead in (1, 3, 5)]
    if not rising[0] > rising[1] > rising[2]:
        failures.append(f"confidence should fall as Lead Time grows, got {rising}")

    for line in failures:
        print(f"  FAIL {line}")
    print("confidence.py --check: " + ("FAILED" if failures else "all checks passed"))
    return 1 if failures else 0


def main() -> int:
    if "--check" in sys.argv:
        return check()

    budget = ErrorBudget.shipped()
    bar = load_thresholds().minimum_significant_wave_height_m
    days = gold_day_peaks()
    below = [day for day in days if day.operational_m < bar]
    floor, binding = price(days, budget, bar)

    print(
        f"{len(days)} Gold Days, operational peaks "
        f"{days[0].operational_m:.2f}-{days[-1].operational_m:.2f} m, against a {bar:g} m bar"
    )
    for day in below:
        print(
            f"  {day.date} peaks at {day.operational_m:.2f} m, below the bar: the height "
            "condition already refuses it, so this floor is not charged for it"
        )

    print(f"\nStrictest floor costing no eligible Gold Day: {floor:.2f}")
    for day in binding:
        print(f"  set by {day.date} at {day.operational_m:.2f} m ({day.split})")

    print("\nWhat other floors would cost, in Gold Days that lose a Go Call somewhere:")
    for candidate in (0.60, 0.70, 0.75, 0.80, 0.85, 0.90):
        print(f"  {candidate:.2f}: {cost_of(candidate, days, budget, bar):2d}")

    print(f"\nShipped: GO_CALL_CONFIDENCE = {GO_CALL_CONFIDENCE:g}")
    if floor < GO_CALL_CONFIDENCE:
        print(
            f"  WARNING: the shipped floor is stricter than {floor:.2f} and costs "
            f"{cost_of(GO_CALL_CONFIDENCE, days, budget, bar)} Gold Days"
        )

    print(f"\nWrote {write_csv(days, budget, bar)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

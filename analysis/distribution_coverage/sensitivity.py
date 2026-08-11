"""What `coverage.py`'s one flattering approximation is actually worth.

Ticket #80. `coverage.py` scores the shipped distribution with the six wave features it does
not perturb taken **settled** rather than forecast, because the Swell partition is not
archived at any Lead Time. That hands the distribution a better-placed centre than a Pipeline
Run has, and every over-coverage result rests on it being a small effect.

This measures it instead of asserting it, in the shape `analysis/forecast_error/
wind_sensitivity.py` established for #68: perturb the omitted inputs by their own measured
drift, rebuild through the shipped sampler, and report the movement as a share of the
plausible range's width. A caveat priced in the same units as the finding it qualifies is one
a reader can weigh; a caveat in words is one they have to take on trust.

**The stand-in, and why it errs upward.** No drift was ever measured for the Swell partition —
that absence is the whole reason those features go unperturbed. What *is* measured, at every
Lead Time, is the Combined Sea partition: `wave_height`, `wave_period` and `wave_direction` in
`analysis/forecast_error/output/drift_by_lead_time.csv`. Those are used here as the Swell
partition's drift. The Combined Sea is Swell plus locally-raised wind sea (CONTEXT.md), and
the wind sea is the part that appears and disappears within a forecast cycle — so the combined
figure moves at least as much as the travelled component it contains. Substituting it makes
this an **upper bound** on the omission, which is the direction a caveat has to err in.

Read from the committed report rather than re-derived, following
`analysis/track_record/publish.py`: a second calculation of the same drift is a second answer.

Run:
    .venv/Scripts/python.exe analysis/distribution_coverage/sensitivity.py
"""

from __future__ import annotations

import csv
import random
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = HERE / "output"

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "analysis" / "forecast_error"))
sys.path.insert(0, str(ROOT / "backend" / "src"))

from profile import load_proxy_target, percentile  # noqa: E402

from coverage import _median, readings_at  # noqa: E402
from download_runs import LEAD_TIMES, Runs, waves, wind  # noqa: E402
from nazarenow.distribution import ErrorBudget  # noqa: E402
from nazarenow.pipeline import amplification_model  # noqa: E402
from nazarenow.thresholds import load as load_thresholds  # noqa: E402
from settled import settled  # noqa: E402

DRIFT = ROOT / "analysis" / "forecast_error" / "output" / "drift_by_lead_time.csv"

STAND_IN = {
    "swell_height": "wave_height",
    "swell_period": "wave_period",
    "swell_direction": "wave_direction",
}
"""Each unperturbed Swell feature, and the Combined Sea variable standing in for its drift."""

CIRCULAR = frozenset({"swell_direction"})
"""Features in degrees, perturbed with a wrap. Adding 8° to 356° is 4°, not 364°."""

SEEDS = (80, 81, 82)
"""Three passes, so the reported figure is not one draw's accident.

Not more, because this is a bound on a caveat rather than a headline: the spread across these
three is reported beside the figure, and if it were wide enough to matter the bound would be
too loose to rest anything on anyway.
"""


def drift_by_lead() -> dict[int, dict[str, float]]:
    """`{lead: {variable: drift}}` for the stand-in variables, from the committed report.

    The `all hours` subset, matching the span `coverage.py` reports its headline on. Drift
    rather than RMSE, for the reason `distribution.py` gives about correcting a centre before
    widening around it: the bias is separately handled and only the width belongs here.
    """
    wanted = set(STAND_IN.values())
    found: dict[int, dict[str, float]] = {}
    with DRIFT.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["subset"] != "all hours" or row["variable"] not in wanted:
                continue
            found.setdefault(int(row["lead_time_days"]), {})[row["variable"]] = float(row["drift"])

    for lead in LEAD_TIMES:
        missing = wanted - set(found.get(lead, {}))
        if missing:
            raise RuntimeError(
                f"{DRIFT.relative_to(ROOT)} carries no drift for {sorted(missing)} at lead "
                f"{lead}; re-run analysis/forecast_error/profile.py"
            )
    return found


def perturbed(
    features: dict[str, float], drifts: dict[str, float], rng: random.Random
) -> dict[str, float]:
    """The same hour with its unperturbed Swell features moved by one draw of their drift."""
    moved = dict(features)
    for feature, stand_in in STAND_IN.items():
        shifted = features[feature] + rng.gauss(0.0, drifts[stand_in])
        moved[feature] = shifted % 360.0 if feature in CIRCULAR else max(0.0, shifted)
    return moved


@dataclass(frozen=True)
class Movement:
    """How far the centre moved at one Lead Time, against the width it moved inside."""

    lead: int
    hours: int
    median_shift_m: float
    p95_shift_m: float
    median_share: float
    p95_share: float
    covered_settled: float
    covered_perturbed: float


def measure(
    budget: ErrorBudget,
    sea: Runs,
    winds: Runs,
    swell: dict[str, dict[str, float]],
    observed: dict[str, float],
    height_bar_m: float,
) -> list[Movement]:
    model = amplification_model()
    drifts = drift_by_lead()
    movements = []

    for lead in LEAD_TIMES:
        shifts: list[float] = []
        shares: list[float] = []
        settled_hits = perturbed_hits = trials = 0

        for hour in sorted(observed):
            features = readings_at(hour, lead, sea, winds, swell)
            if features is None:
                continue
            base = budget.distribution(model, features, lead, height_bar_m=height_bar_m)
            low, high = base.range_m
            half_width = (high - low) / 2.0
            centre = _median(base)
            outcome = observed[hour]

            for seed in SEEDS:
                # Seeded on the hour as well as the pass, so the draw for a given hour is
                # reproducible on its own and does not depend on how many hours preceded it.
                rng = random.Random(f"{seed}:{hour}:{lead}")
                moved = budget.distribution(
                    model, perturbed(features, drifts[lead], rng), lead, height_bar_m=height_bar_m
                )
                moved_low, moved_high = moved.range_m
                shifts.append(abs(_median(moved) - centre))
                shares.append(abs(_median(moved) - centre) / half_width)
                perturbed_hits += moved_low <= outcome <= moved_high
                trials += 1

            settled_hits += low <= outcome <= high

        movements.append(
            Movement(
                lead=lead,
                hours=len(shifts) // len(SEEDS),
                median_shift_m=statistics.median(shifts),
                p95_shift_m=percentile(shifts, 0.95),
                median_share=statistics.median(shares),
                p95_share=percentile(shares, 0.95),
                covered_settled=settled_hits / (len(shifts) // len(SEEDS)),
                covered_perturbed=perturbed_hits / trials,
            )
        )
    return movements


def write(rows: list[Movement]) -> Path:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / "settled_feature_cost.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "lead_days",
                "hours",
                "median_shift_m",
                "p95_shift_m",
                "median_share_of_half_width",
                "p95_share_of_half_width",
                "covered_settled",
                "covered_perturbed",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.lead,
                    row.hours,
                    round(row.median_shift_m, 4),
                    round(row.p95_shift_m, 4),
                    round(row.median_share, 4),
                    round(row.p95_share, 4),
                    round(row.covered_settled, 4),
                    round(row.covered_perturbed, 4),
                ]
            )
    return path


def main() -> int:
    thresholds = load_thresholds()
    budget = ErrorBudget.shipped()
    rows = measure(
        budget,
        waves(),
        wind(),
        settled(),
        load_proxy_target(),
        thresholds.minimum_significant_wave_height_m,
    )

    print("\nWhat taking the Swell partition settled is worth, per Lead Time.")
    print(
        f"{'Lead':<6}{'Hours':>8}{'Median':>10}{'p95':>9}{'Median %':>11}{'p95 %':>9}"
        f"{'Settled':>10}{'Forecast':>10}"
    )
    for row in rows:
        print(
            f"{row.lead}d{'':<4}{row.hours:>8,}{row.median_shift_m:>9.3f}m{row.p95_shift_m:>8.3f}m"
            f"{row.median_share:>11.1%}{row.p95_share:>9.1%}"
            f"{row.covered_settled:>10.1%}{row.covered_perturbed:>10.1%}"
        )

    print(f"\nWrote {write(rows).relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

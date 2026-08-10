"""What perturbing wind would add to the Predictive Distribution, and whether it is worth it.

Ticket #68. #15's first criterion asks that forecast **inputs** be perturbed by the measured
Forecast Error Profile; `ErrorBudget.distribution` perturbs exactly one of the Amplification
Model's eight features, the Combined Sea, and carries the other seven through unchanged.

Four of those seven have no choice about it. ADR 0004's #14 amendment records that the Swell
partition returns HTTP 200 with every value null under a `_previous_dayN` suffix, so there is
no profile to perturb `swell_height_m`, `swell_period_s` or the two swell bearings by.

**Wind does have a choice**, and this script is the measurement that justifies which way it
went. #14 measured a wind profile, and README finding 4 establishes that it is weather out to
four days and a provider artefact past that. So the question is real, and answerable: perturb
wind inside its trustworthy window and read what changes.

The answer is **about 1% of the plausible range's width**, or one to two centimetres on a range
one and a half to two metres wide, at every Lead Time in the window and on both a giant day and
an ordinary one. Two things make it that small. Wind's standardised coefficient is -0.0569
against Combined Sea's 1.0893 (`analysis/amplification_model/output/feature_reliance.csv`), so
even the widest measured wind drift moves a prediction by only about 0.11 m; and that 0.11 m
then joins, in quadrature, terms several times larger than itself — the widths below correspond
to a combined sigma of roughly 0.43 m to 0.68 m at lead 4, against which a quadrature term
counts for its square.

That is the number `distribution.py` cites when it says wind is deliberately not perturbed, and
`backend/tests/test_wind_is_carried_through.py` is what fails if it stops being true.

**The sampler below mirrors `ErrorBudget.distribution` rather than calling it**, because what is
being measured is a version of it that does not exist. The mirrored version is exercised against
the real one in `--check`: with wind perturbation switched off it must reproduce the shipped
distribution exactly, which is what stops this script quietly measuring the difference between
two samplers instead of the difference wind makes.

Run, from the repository root:

    .venv/Scripts/python.exe analysis/forecast_error/wind_sensitivity.py
    .venv/Scripts/python.exe analysis/forecast_error/wind_sensitivity.py --check

No credentials, no network. Reads `output/drift_by_lead_time.csv` and the shipped parameter
files. The table lands in `output/`.
"""

from __future__ import annotations

import csv
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from nazarenow.distribution import SEA, ErrorBudget  # noqa: E402
from nazarenow.models.base import AmplificationModel  # noqa: E402
from nazarenow.models.learned import LearnedAmplification  # noqa: E402

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "output"
DRIFT = OUTPUT / "drift_by_lead_time.csv"

TRUSTWORTHY_THROUGH_LEAD_DAYS = 4
"""Where the wind profile stops being evidence about the weather.

README finding 4: leads 5 and 6 carry a +3 to +9 km/h bias for seven consecutive months and the
error *falls* between six and seven days, which no forecast does. Measuring the value of
perturbing wind at those Lead Times would price a provider artefact.
"""

DRAWS = 20_000
"""Far above the 500 the system ships.

The quantity here is a difference between two ranges, and at 500 draws the sampling wobble in
each is the same size as the difference being measured. This is an offline script asked one
question once, so it can afford to answer it out of the noise.
"""

FIXTURES = {
    # A giant day, in the regime this project exists to call: above the 3 m bar, so every term
    # is read at its big-swell band, and a wind strong enough to matter to the fit.
    "giant": {
        "significant_wave_height": 5.0,
        "swell_height": 4.4,
        "swell_period": 16.0,
        "swell_direction": 300.0,
        "wind_speed": 18.0,
        "wind_direction": 90.0,
    },
    # An ordinary winter day below the bar, reading the all-hours band throughout. Included
    # because the ratio, not the absolute width, is what the conclusion rests on — and the
    # ratio could differ between regimes.
    "ordinary": {
        "significant_wave_height": 2.2,
        "swell_height": 1.8,
        "swell_period": 11.0,
        "swell_direction": 290.0,
        "wind_speed": 12.0,
        "wind_direction": 200.0,
    },
}


def wind_drift() -> dict[tuple[str, int, str], float]:
    """The measured drift for both wind variables, keyed by variable, Lead Time and regime.

    `noise` rather than `rmse`, matching what `forecast_error.json` ships and what
    `ErrorBudget.distribution` perturbs the sea by: the width that survives a constant
    correction.
    """
    if not DRIFT.exists():
        raise SystemExit(f"{DRIFT} is missing; run analysis/forecast_error/profile.py first")

    measured: dict[tuple[str, int, str], float] = {}
    with DRIFT.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["variable"] not in ("wind_speed_10m", "wind_direction_10m"):
                continue
            regime = "big_swell" if row["subset"] == "big swell" else "all_hours"
            measured[(row["variable"], int(row["lead_time_days"]), regime)] = float(row["noise"])
    return measured


def sample(
    budget: ErrorBudget,
    model: AmplificationModel,
    readings: dict[str, float],
    lead_time_days: int,
    *,
    wind: dict[tuple[str, int, str], float] | None,
    draws: int = DRAWS,
    seed: int = 15,
) -> tuple[float, ...]:
    """`ErrorBudget.distribution`'s loop, with wind perturbation available.

    Every term, every ordering and the single shared generator are the shipped ones — see the
    module docstring on why this is a mirror and how `--check` holds it to that. `wind=None` is
    the shipped behaviour exactly.
    """
    sea = float(readings[SEA])
    lead = budget.forecast.at(lead_time_days)
    if lead is None:
        raise SystemExit(f"lead time {lead_time_days} is past the archive; nothing to measure")

    band = lead.for_sea(sea)
    regime = "big_swell" if sea >= lead.big_swell_m else "all_hours"
    input_sigma = math.hypot(band.noise, budget.translation_rmse)
    output_sigma = budget.own_error(sea)
    centre = sea - band.bias

    rng = random.Random(seed)
    samples = []
    for _ in range(draws):
        perturbed = dict(readings)
        perturbed[SEA] = max(0.0, centre + rng.gauss(0.0, input_sigma))
        if wind is not None:
            # Drawn after the sea and before the model's own error, so the shipped draws are
            # untouched in order as well as in distribution when `wind is None`.
            speed_sigma = wind[("wind_speed_10m", lead_time_days, regime)]
            direction_sigma = wind[("wind_direction_10m", lead_time_days, regime)]
            perturbed["wind_speed"] = max(0.0, readings["wind_speed"] + rng.gauss(0.0, speed_sigma))
            perturbed["wind_direction"] = (
                readings["wind_direction"] + rng.gauss(0.0, direction_sigma)
            ) % 360
        predicted = model.predict(perturbed).significant_wave_height
        samples.append(max(0.0, predicted + rng.gauss(0.0, output_sigma)))
    return tuple(samples)


def width(samples: tuple[float, ...]) -> float:
    """The p5-p95 span, by `PredictiveDistribution._percentile`'s own rule."""
    ordered = sorted(samples)
    low = ordered[min(len(ordered) - 1, max(0, round(0.05 * (len(ordered) - 1))))]
    high = ordered[min(len(ordered) - 1, max(0, round(0.95 * (len(ordered) - 1))))]
    return high - low


def check(budget: ErrorBudget, model: AmplificationModel) -> None:
    """The mirror reproduces the shipped sampler exactly when wind is left alone.

    Sample-for-sample, not distribution-for-distribution. A drifted mirror would still produce
    a plausible range, and the difference this script reports would then be part sampler and
    part wind with no way to tell which.
    """
    for name, readings in FIXTURES.items():
        for lead in range(1, TRUSTWORTHY_THROUGH_LEAD_DAYS + 1):
            shipped = budget.distribution(model, readings, lead_time_days=lead, draws=200).samples
            mirrored = sample(budget, model, readings, lead, wind=None, draws=200)
            if shipped != mirrored:
                raise SystemExit(
                    f"the mirrored sampler has drifted from ErrorBudget.distribution on the "
                    f"{name} fixture at lead {lead}; this script can no longer attribute a "
                    "difference to wind"
                )
    print(f"mirror matches ErrorBudget.distribution on {len(FIXTURES)} fixtures, leads 1-4")


def main() -> None:
    budget = ErrorBudget.shipped()
    model = LearnedAmplification()

    if "--check" in sys.argv:
        check(budget, model)
        return

    wind = wind_drift()
    rows = []
    for name, readings in FIXTURES.items():
        for lead in range(1, TRUSTWORTHY_THROUGH_LEAD_DAYS + 1):
            shipped = width(sample(budget, model, readings, lead, wind=None))
            perturbed = width(sample(budget, model, readings, lead, wind=wind))
            regime = "big_swell" if readings[SEA] >= budget.regime_m else "all_hours"
            rows.append(
                {
                    "fixture": name,
                    "significant_wave_height_m": readings[SEA],
                    "regime": regime,
                    "lead_time_days": lead,
                    "wind_speed_noise_kmh": round(wind[("wind_speed_10m", lead, regime)], 4),
                    "wind_direction_noise_deg": round(
                        wind[("wind_direction_10m", lead, regime)], 4
                    ),
                    "width_m": round(shipped, 4),
                    "width_with_wind_m": round(perturbed, 4),
                    "widening_m": round(perturbed - shipped, 4),
                    "widening_share": round((perturbed - shipped) / shipped, 4),
                }
            )

    OUTPUT.mkdir(exist_ok=True)
    destination = OUTPUT / "wind_perturbation.csv"
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    print(f"{'fixture':>9} {'lead':>5} {'width':>8} {'with wind':>10} {'delta':>8} {'share':>7}")
    for row in rows:
        print(
            f"{row['fixture']:>9} {row['lead_time_days']:>5} {row['width_m']:>8.4f} "
            f"{row['width_with_wind_m']:>10.4f} {row['widening_m']:>8.4f} "
            f"{row['widening_share']:>6.2%}"
        )
    worst = max(row["widening_share"] for row in rows)
    print(f"\nwidest effect anywhere in the trustworthy window: {worst:.2%}")
    print(f"wrote {destination}")


if __name__ == "__main__":
    main()

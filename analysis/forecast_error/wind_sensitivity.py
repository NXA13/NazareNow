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

The answer is **0.28% to 0.96% of the plausible range's width** — half a centimetre to one and
a half, on ranges 1.09 m to 2.22 m wide — averaged over twenty seeds, at every Lead Time in the
window and on both a giant day and an ordinary one.

Two things make it that small. The three wind features carry standardised coefficients of
-0.0569, 0.0497 and 0.0334 against Combined Sea's 1.0893
(`analysis/amplification_model/output/feature_reliance.csv`), so even the widest measured drift
for each variable, applied at once and worst-aligned, moves a prediction by only about 0.12 m.
That 0.12 m then joins, in quadrature, terms several times larger: the widths below
correspond to a combined sigma of roughly 0.43 m to 0.68 m at lead 4, against which a
quadrature term counts for its square.

That is the number `distribution.py` cites when it says wind is deliberately not perturbed, and
`backend/tests/test_wind_is_carried_through.py` is what fails if it stops being true.

**The sampler below mirrors `ErrorBudget.distribution` rather than calling it**, because what is
being measured is a version of it that does not exist. The mirrored version is exercised against
the real one in `--check`: with wind perturbation switched off it must reproduce the shipped
distribution exactly, which is what stops this script quietly measuring the difference between
two samplers instead of the difference wind makes.

**Two things `--check` cannot see, both of which make the figure conservative.** It exercises
only the `wind=None` arm, so it would not have caught the unpaired estimator `sample` documents
— that took comparing seeds, which is now what `SEEDS` does on every run. And the mirror takes
the drift straight off the band, where `ErrorBudget.distribution` puts it through
`_drift_floor` first: in production an ensemble may raise the drift, which widens the baseline
this effect is a share *of*. `_drift_floor`'s own figures have the ensemble carrying lead 1
(0.263 m of sigma against 0.130 m of drift), so the shares here are if anything overstated at
short Lead Times, and understated nowhere.

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
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from nazarenow.distribution import SEA, ErrorBudget  # noqa: E402
from nazarenow.forecast_error import LeadTime  # noqa: E402
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

The quantity here is a difference between two ranges, and even paired it is a fraction of the
width being differenced. This is an offline script asked one question once, so it can afford
the draws.
"""

SEEDS = tuple(range(101, 121))
"""The measurement is repeated under twenty seeds and reported with its spread.

One seed produces one number and says nothing about how much of it was the seed. That is not
a hypothetical worry here: the unpaired first version of this script reported 0.86% at seed 15
and had a standard deviation of about 0.8 percentage points across seeds, so the published
figure was mostly a draw. Pairing fixes the estimator; reporting the spread is what makes a
future breakage of it visible rather than a number that merely looks precise.
"""

WIND_STREAM_SEED = 68_000
"""Offset for the wind generator, keeping it clear of the shipped stream's seeds.

Arbitrary, and only required to be stable — see `sample` for why wind must not draw from the
generator the shipped sampler owns.
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


def regime_of(significant_wave_height_m: float, lead: LeadTime) -> str:
    """Which of the two measured bands a sea of this size reads.

    One function rather than a repeated conditional, and it takes the bar off the profile —
    `LeadTime.big_swell_m`, which is what split the drift rows being looked up. `ErrorBudget`
    carries a `regime_m` of its own for the *Amplification* residual; the two are both 3.0 m
    today and are not the same bar. A row labelled by one and sampled under the other would
    describe a measurement nobody made.
    """
    return "big_swell" if significant_wave_height_m >= lead.big_swell_m else "all_hours"


def wind_drift() -> dict[tuple[str, int, str], float]:
    """The measured drift for both wind variables, keyed by variable, Lead Time and regime.

    `drift` rather than `rmse`, matching what `forecast_error.json` ships and what
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
            measured[(row["variable"], int(row["lead_time_days"]), regime)] = float(row["drift"])
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

    Every term and every ordering is the shipped one — see the module docstring on why this is
    a mirror and how `--check` holds it to that. `wind=None` reproduces the shipped sampler
    exactly, generator included.

    **Wind draws come from a second generator, and that is the whole measurement.** Taking them
    from `rng` would advance it two draws per iteration, so the sea and the model's own error
    would differ between the two arms from the first draw onward — and the difference in width
    would then be two independent samples minus each other, with wind somewhere inside it. The
    first version of this script did that at 20,000 draws and reported an effect the size of
    its own sampling error: individual seeds put wind's contribution anywhere from -0.9% to
    +1.3%, including seeds where perturbing wind appeared to *narrow* the range. Sharing the
    sea and output draws across the two arms — common random numbers — is what leaves the
    difference attributable to wind at all.
    """
    sea = float(readings[SEA])
    lead = budget.forecast.at(lead_time_days)
    if lead is None:
        raise SystemExit(f"lead time {lead_time_days} is past the archive; nothing to measure")

    band = lead.for_sea(sea)
    regime = regime_of(sea, lead)
    input_sigma = math.hypot(band.drift, budget.translation_rmse)
    output_sigma = budget.own_error(sea)
    centre = sea - band.bias

    rng = random.Random(seed)
    # Offset rather than derived from `rng`, so this stream exists independently of how many
    # draws the shipped one takes and cannot be perturbed by a change to it.
    wind_rng = random.Random(WIND_STREAM_SEED + seed)
    samples = []
    for _ in range(draws):
        perturbed = dict(readings)
        perturbed[SEA] = max(0.0, centre + rng.gauss(0.0, input_sigma))
        if wind is not None:
            speed_sigma = wind[("wind_speed_10m", lead_time_days, regime)]
            direction_sigma = wind[("wind_direction_10m", lead_time_days, regime)]
            perturbed["wind_speed"] = max(
                0.0, readings["wind_speed"] + wind_rng.gauss(0.0, speed_sigma)
            )
            perturbed["wind_direction"] = (
                readings["wind_direction"] + wind_rng.gauss(0.0, direction_sigma)
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
            lead_time = budget.forecast.at(lead)
            if lead_time is None:  # pragma: no cover - the loop stops inside the archive
                raise SystemExit(f"lead time {lead} is past the archive")
            regime = regime_of(float(readings[SEA]), lead_time)

            widths = []
            widenings = []
            shares = []
            for seed in SEEDS:
                shipped = width(sample(budget, model, readings, lead, wind=None, seed=seed))
                perturbed = width(sample(budget, model, readings, lead, wind=wind, seed=seed))
                widths.append(shipped)
                widenings.append(perturbed - shipped)
                shares.append((perturbed - shipped) / shipped)

            rows.append(
                {
                    "fixture": name,
                    "significant_wave_height_m": readings[SEA],
                    "regime": regime,
                    "lead_time_days": lead,
                    "seeds": len(SEEDS),
                    "wind_speed_drift_kmh": round(wind[("wind_speed_10m", lead, regime)], 4),
                    "wind_direction_drift_deg": round(
                        wind[("wind_direction_10m", lead, regime)], 4
                    ),
                    "width_m": round(statistics.fmean(widths), 4),
                    "widening_m": round(statistics.fmean(widenings), 4),
                    "widening_share": round(statistics.fmean(shares), 4),
                    "widening_share_sd": round(statistics.stdev(shares), 4),
                    "widening_share_min": round(min(shares), 4),
                    "widening_share_max": round(max(shares), 4),
                }
            )

    OUTPUT.mkdir(exist_ok=True)
    destination = OUTPUT / "wind_perturbation.csv"
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    print(f"{len(SEEDS)} seeds x {DRAWS:,} draws, paired\n")
    print(
        f"{'fixture':>9} {'lead':>5} {'width':>8} {'delta':>8} {'share':>8} {'sd':>7} {'range':>16}"
    )
    for row in rows:
        print(
            f"{row['fixture']:>9} {row['lead_time_days']:>5} {row['width_m']:>8.4f} "
            f"{row['widening_m']:>8.4f} {row['widening_share']:>7.2%} "
            f"{row['widening_share_sd']:>6.2%} "
            f"{row['widening_share_min']:>7.2%} to {row['widening_share_max']:.2%}"
        )
    print(
        f"\nwidest mean effect in the trustworthy window: "
        f"{max(row['widening_share'] for row in rows):.2%}"
    )
    print(
        f"widest single-seed effect anywhere: {max(row['widening_share_max'] for row in rows):.2%}"
    )
    print(f"wrote {destination}")


if __name__ == "__main__":
    main()

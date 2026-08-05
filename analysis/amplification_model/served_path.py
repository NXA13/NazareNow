"""Scoring both models on the path the running system takes, not the path the fit was scored on.

`train.py` scores the baseline and the learned model on IBI reanalysis rows, in reanalysis
units. That is the right comparison for judging the *fit*, and the wrong one for predicting
what the site will show, because the Pipeline Run consumes Open-Meteo. The two models meet
that skew differently:

- The **baseline** returns the forecast's own Significant Wave Height unchanged. Served, that
  is an Open-Meteo number offered as a prediction of the Proxy Target, carrying the whole
  IBI/Open-Meteo difference uncorrected. Nothing in `train.py` sees this, because there the
  baseline is handed an IBI row.
- The **learned model** inverts the translation first (`LearnedAmplification._restate`), which
  is correct in expectation and costs the translation's residual scatter — 0.130 m on Hs since
  #58 refitted it on every overlapping hour (0.217 m before), still larger than the whole
  +0.047 m held-out MAE gain at >= 3 m. Those two numbers are less comparable than they look:
  the inversion is unbiased, so symmetric scatter raises both models' error together and
  mostly cancels in the difference. `translation_shape.py` measures it at 0.002 m in the
  3-4 m band.

That asymmetry is why the served comparison cannot be assumed to look like the scored one, in
either direction. A code review of #13 flagged the scored/served gap; this module measures it
rather than leaving it as a caveat.

**This is a bound, not an observation.** Open-Meteo has no historical archive in this project
— that is the same absence ADR 0002 introduced a Proxy Target for — so what Open-Meteo *would*
have read is generated from the measured translation plus noise at its measured residual RMSE:

    operational = slope x reanalysis + intercept + noise(0, residual_rmse)

The assumption is that the residual is independent of sea state. If it is instead correlated
with size, these numbers move, and only an operational archive would settle it. The assumption
is conservative for the learned model in one specific way: independent noise is the *worst*
case for a model that has to invert it, while the baseline's exposure is a fixed offset that
no noise assumption changes.

`--check` pins the arithmetic by reproducing `output/held_out_scores.csv` from this module's
own feature construction. Those two agreeing to 4 dp is what makes the served numbers below
comparable with the scored ones rather than a separate calculation that happens to look alike.

Run:
    .venv/Scripts/python.exe analysis/amplification_model/served_path.py

    # Reproduces the published scored table from this module's arithmetic.
    .venv/Scripts/python.exe analysis/amplification_model/served_path.py --check
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent

sys.path.insert(0, str(ROOT / "backend" / "src"))

from nazarenow.models.learned import FEATURES  # noqa: E402

DATASET = ROOT / "analysis" / "training_dataset" / "output" / "training_dataset.csv"
PARAMETERS = ROOT / "backend" / "src" / "nazarenow" / "amplification.json"
SCORED = HERE / "output" / "held_out_scores.csv"
OUTPUT = HERE / "output" / "served_path_scores.csv"

HELD_OUT_SEASONS = range(2020, 2026)
"""The same held-out span `train.py` uses. Both models are out of sample on it."""

TRIALS = 200
SEED = 20260803
"""Fixed, because a committed CSV that moved on every run would be unreviewable."""

NEEDED = (
    "proxy_target_height_m",
    "hindcast_combined_sea_height_m",
    "swell_height_m",
    "swell_period_s",
    "swell_direction_deg",
    "wind_speed_kmh",
    "wind_direction_deg",
)


def load():
    parameters = json.loads(PARAMETERS.read_text(encoding="utf-8"))
    frame = pd.read_csv(DATASET)
    frame = frame[frame["season"].isin(HELD_OUT_SEASONS)].dropna(subset=list(NEEDED))
    return parameters, frame


def build_features(hs, period, frame):
    """numpy mirrors of `models.learned.FEATURES`, which are scalar `math.*` lambdas.

    A third encoding of the feature vector is exactly the defect `train.py --check` exists to
    catch between the other two, so this one is pinned the same way: `check()` reproduces the
    published scored table, which cannot happen if a column is built differently here.
    """
    swell = np.radians(frame["swell_direction_deg"].to_numpy())
    wind = np.radians(frame["wind_direction_deg"].to_numpy())
    built = {
        "combined_sea_m": hs,
        "swell_height_m": frame["swell_height_m"].to_numpy(),
        "swell_period_s": period,
        "swell_direction_sin": np.sin(swell),
        "swell_direction_cos": np.cos(swell),
        "wind_speed_kmh": frame["wind_speed_kmh"].to_numpy(),
        "wind_direction_sin": np.sin(wind),
        "wind_direction_cos": np.cos(wind),
        "combined_sea_x_period": hs * period,
    }
    if set(built) != set(FEATURES):
        raise ValueError(
            "this module builds a different feature set from models/learned.py: "
            f"{sorted(set(built) ^ set(FEATURES))}"
        )
    return built


def predict(parameters, hs, period, frame):
    """The shipped dot product, on inputs already in reanalysis units."""
    built = build_features(hs, period, frame)
    out = np.full(len(hs), float(parameters["intercept"]))
    for name, coefficient in zip(parameters["features"], parameters["coefficients"], strict=True):
        out = out + float(coefficient) * np.asarray(built[name], dtype=float)
    # Floored exactly as `LearnedAmplification.predict` floors it.
    return np.maximum(out, 0.0)


def subsets(frame, target):
    """The bands `train.py` reports, so the two tables can be read side by side."""
    combined = frame["hindcast_combined_sea_height_m"].to_numpy()
    return {
        "all hours": np.ones(len(target), dtype=bool),
        "Combined Sea >= 3 m": combined >= 3.0,
        "measured target under 2 m": target < 2.0,
        "measured target 2-3 m": (target >= 2.0) & (target < 3.0),
        "measured target 3-4 m": (target >= 3.0) & (target < 4.0),
        "measured target 4-5 m": (target >= 4.0) & (target < 5.0),
        "measured target 5-6 m": (target >= 5.0) & (target < 6.0),
        "measured target 6 m and above": target >= 6.0,
    }


def scored(parameters, frame, target):
    """Both models as `train.py` scores them: IBI in, no translation step."""
    hs = frame["hindcast_combined_sea_height_m"].to_numpy()
    period = frame["swell_period_s"].to_numpy()
    return hs, predict(parameters, hs, period, frame)


def served(parameters, frame, target, trials=TRIALS):
    """Both models as `run_pipeline` runs them: Open-Meteo in, each meeting the skew its way."""
    translations = parameters["translations"]
    height = translations["significant_wave_height_m"]
    swell_period = translations["swell_period_s"]
    ibi_hs = frame["hindcast_combined_sea_height_m"].to_numpy()
    ibi_period = frame["swell_period_s"].to_numpy()
    rng = np.random.default_rng(SEED)

    bands = subsets(frame, target)
    collected = {name: {"baseline": [], "learned": []} for name in bands}

    for _ in range(trials):
        operational_hs = (
            height["slope"] * ibi_hs
            + height["intercept"]
            + rng.normal(0.0, height["residual_rmse"], len(ibi_hs))
        )
        operational_period = (
            swell_period["slope"] * ibi_period
            + swell_period["intercept"]
            + rng.normal(0.0, swell_period["residual_rmse"], len(ibi_period))
        )
        # The baseline carries its reading through untouched — including the offset.
        baseline = operational_hs
        # The learned model restates first. This is `_restate`, inverted the same way.
        learned = predict(
            parameters,
            (operational_hs - height["intercept"]) / height["slope"],
            (operational_period - swell_period["intercept"]) / swell_period["slope"],
            frame,
        )
        for name, mask in bands.items():
            collected[name]["baseline"].append(np.abs(baseline[mask] - target[mask]).mean())
            collected[name]["learned"].append(np.abs(learned[mask] - target[mask]).mean())
    return bands, collected


def build() -> int:
    parameters, frame = load()
    target = frame["proxy_target_height_m"].to_numpy()
    baseline_scored, learned_scored = scored(parameters, frame, target)
    bands, collected = served(parameters, frame, target)

    rows = []
    for name, mask in bands.items():
        scored_baseline = float(np.abs(baseline_scored[mask] - target[mask]).mean())
        scored_learned = float(np.abs(learned_scored[mask] - target[mask]).mean())
        gains = np.array(collected[name]["baseline"]) - np.array(collected[name]["learned"])
        low, high = np.percentile(gains, [5, 95])
        rows.append(
            {
                "subset": name,
                "rows": int(mask.sum()),
                "scored_baseline_mae": round(scored_baseline, 4),
                "scored_learned_mae": round(scored_learned, 4),
                "scored_gain_m": round(scored_baseline - scored_learned, 4),
                "served_baseline_mae": round(float(np.mean(collected[name]["baseline"])), 4),
                "served_learned_mae": round(float(np.mean(collected[name]["learned"])), 4),
                "served_gain_m": round(float(np.mean(gains)), 4),
                "served_gain_p5": round(float(low), 4),
                "served_gain_p95": round(float(high), 4),
            }
        )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    print(f"Held-out rows: {len(frame):,}   Monte Carlo trials: {TRIALS}\n")
    print(f"{'subset':<32}{'scored gain':>13}{'served gain':>13}   served 5-95%")
    for row in rows:
        print(
            f"{row['subset']:<32}{row['scored_gain_m']:>+13.4f}{row['served_gain_m']:>+13.4f}"
            f"   {row['served_gain_p5']:+.4f} to {row['served_gain_p95']:+.4f}"
        )
    print(f"\nwrote {OUTPUT.relative_to(ROOT)}")
    return 0


def check() -> int:
    """Reproduce the published scored table from this module's own arithmetic."""
    failures: list[str] = []

    def expect(condition: bool, message: str) -> None:
        if not condition:
            failures.append(message)

    if not DATASET.exists():
        print(f"FAILED - {DATASET.relative_to(ROOT)} is missing; run training_dataset/build.py")
        return 1

    parameters, frame = load()
    target = frame["proxy_target_height_m"].to_numpy()
    baseline_scored, learned_scored = scored(parameters, frame, target)
    bands = subsets(frame, target)

    published = {row["subset"].removeprefix("held-out: "): row for row in _published()}
    for name, mask in bands.items():
        if name not in published:
            continue
        row = published[name]
        expect(
            int(row["rows"]) == int(mask.sum()),
            f"{name}: {mask.sum()} rows here against {row['rows']} published",
        )
        for label, computed in (
            ("baseline_mae", np.abs(baseline_scored[mask] - target[mask]).mean()),
            ("learned_mae", np.abs(learned_scored[mask] - target[mask]).mean()),
        ):
            expect(
                abs(float(row[label]) - computed) < 5e-5,
                f"{name} {label}: {computed:.4f} here against {row[label]} published — "
                "this module builds the feature vector differently from train.py",
            )

    for failure in failures:
        print(f"  FAIL {failure}")
    print(f"{'ok' if not failures else 'FAILED'} - {len(failures)} failure(s)")
    return 1 if failures else 0


def _published():
    with SCORED.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    if "--check" in sys.argv[1:]:
        return check()
    return build()


if __name__ == "__main__":
    raise SystemExit(main())

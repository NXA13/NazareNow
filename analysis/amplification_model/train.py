"""Fitting the first learned Amplification Model, and reporting honestly what it is worth.

Ticket #13. The dataset from #9 is paired here with a least-squares fit, scored against the
Heuristic Baseline on Big-Wave Seasons neither of them was fitted on, and — if it earns it —
exported to `backend/src/nazarenow/amplification.json` for the running system to read.

**What is actually being learned is not Amplification, and this module does not call it
that.** `analysis/training_dataset/README.md` limitation 1 is the reason: IBI's nearest wet
node sits 1.12 km from Monican02 and the live system already samples Open-Meteo at Monican02's
coordinates, so a model mapping the Hindcast's Combined Sea onto the Proxy Target learns the
*reanalysis's local error at one mooring*. The canyon's transformation toward the beach is a
different quantity, in Face Height, with no historical archive — which is why ADR 0002
introduced a Proxy Target at all. CONTEXT.md's definition of Amplification is specific, and
naming this that would be the confident, plausible, wrong number ADR 0006 exists to prevent.
The component is called the Amplification Model because that is the interface slot it fills.

**The comparison is against a pass-through, because that is what the baseline does.**
`HeuristicBaseline.predict` returns the forecast's own Significant Wave Height unchanged —
deliberately, since inventing a factor would manufacture a number. So the question this fit
asks is exact: does a fitted correction predict the Proxy Target better than carrying the
Hindcast's Combined Sea straight through? Both are scored on the same hours, per ADR 0006,
and neither is reported alone.

**Fitted in reanalysis units, served operational ones.** The training features are IBI, and
the running Pipeline Run consumes Open-Meteo, which `analysis/overlap/README.md` measured
reads about half a second shorter on swell period with a compressed range (slope ~0.85). That
is a second train/serve skew on top of the one ADR 0004 anticipated, and #9's README warned
#13 not to assume the ADR covers it. It is handled the way `backtest.py` already handles it:
the fit stays in its native units, and the two translated quantities are `Translation.invert`
-ed from operational into reanalysis units at inference. The constants ride in the exported
JSON so the backend needs no analysis code to apply them.

**The split is on Big-Wave Seasons, and it is the same boundary `calibrate.py` used.** Rows
are hourly and heavily autocorrelated — 73,601 rows are nowhere near 73,601 independent
observations — so a split on rows would leak badly (#9's README, limitation 3). Reusing #12's
boundary matters for more than consistency: the shipped thresholds were fitted on 2011/12 to
2019/20, so scoring both models on 2020/21 onward is the only way the baseline is held out
too. Scoring a learned model held-out against a baseline fitted on the same hours would flatter
the learned model for free.

Run:
    .venv/Scripts/python.exe analysis/amplification_model/train.py

    # The fit, the split, the encoding and the export, self-tested offline.
    .venv/Scripts/python.exe analysis/amplification_model/train.py --check
"""

from __future__ import annotations

import csv
import json
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUTPUT = HERE / "output"

sys.path.insert(0, str(ROOT / "analysis" / "overlap"))
sys.path.insert(0, str(ROOT / "analysis" / "training_dataset"))
sys.path.insert(0, str(ROOT / "backend" / "src"))

import build as training_dataset  # noqa: E402
import measure  # noqa: E402

DATASET = ROOT / "analysis" / "training_dataset" / "output" / "training_dataset.csv"
MODEL_PATH = ROOT / "backend" / "src" / "nazarenow" / "amplification.json"

# Seasons are named by the calendar year they begin in, matching the dataset's `season`
# column; `season_label` renders them the way CONTEXT.md and calibrate.py write them.
TRAIN_SEASONS = tuple(range(2011, 2018))
TUNE_SEASONS = (2018, 2019)
HELD_OUT_SEASONS = tuple(range(2020, 2026))

"""Three splits, not two, because the acceptance criterion says "never seen during training
*or tuning*".

`calibrate.py` needed only a fit and a held-out split: it sweeps one scalar per tier against
an explicit budget, so there is nothing to select between. This fit chooses among candidate
feature sets and weightings, and a candidate chosen on the held-out seasons would make those
seasons part of the fit while still being reported as held out.

So selection happens on 2018/19-2019/20 and nothing else, the chosen candidate is refitted on
all nine fitting seasons, and 2020/21 onward is read exactly once, at the end. The tuning
seasons rejoin the training data for that refit — they were used to pick a shape, not to fit
coefficients, and holding them out of the final fit would throw away two seasons for nothing.
"""

BIG_SWELL_M = 3.0
"""The regime the system exists to call, and the regime candidates are selected in.

Defined on the *input* Combined Sea rather than on the measured target, because that is what
is knowable at serving time — selecting on the target would tune the model against a subset it
cannot identify when it runs. It is the same 3 m `analysis/overlap/measure.py` fits its
**swell period** translation on, and for the same reason: the relationship is not the same at
1 m. It is no longer the bar the *height* translation is fitted on — since #58 that one is
fitted on every overlapping hour, because the argument above holds for a transform that
decides at 3 m and fails for one inverted on every hour the model serves.

Same number and, since #60, the same series. This bar is applied to `combined_sea_m` — the
hindcast's Combined Sea — and `measure.FITTINGS` now selects the swell period subset on
reanalysis Combined Sea too. Until #60 it read Open-Meteo's *Swell* height, so the sentence
above was true of the number and false of the quantity, and the two modules meant different
things by "the regime". They mean one thing now.

Deliberately not the baseline's `minimum_significant_wave_height_m`. That bar is applied to
offshore swell in a forecast; this is Combined Sea at a mooring, and #9's README calls the
conflation load-bearing.
"""


def season_label(season: int) -> str:
    """2011 -> "2011/12". A Big-Wave Season is never a calendar year (CONTEXT.md)."""
    return f"{season}/{(season + 1) % 100:02d}"


@dataclass(frozen=True)
class Row:
    """One hour, reduced to what a model may see and what it is scored against."""

    day: str
    season: int
    combined_sea_m: float
    swell_height_m: float
    swell_period_s: float
    swell_direction_deg: float
    wind_speed_kmh: float
    wind_direction_deg: float
    proxy_target_m: float


FEATURE_NAMES = (
    "combined_sea_m",
    "swell_height_m",
    "swell_period_s",
    "swell_direction_sin",
    "swell_direction_cos",
    "wind_speed_kmh",
    "wind_direction_sin",
    "wind_direction_cos",
    "combined_sea_x_period",
)
"""Every feature the widest candidate can use, in the order a coefficient vector carries them.

**Bearings are split into sine and cosine rather than used raw.** A linear term on degrees
says 359 deg and 1 deg are 358 apart, when they are two degrees apart on the same swell. The
encoding is what lets a direction preference be expressed at all, and it costs one extra
column per bearing.

**The interaction is Combined Sea times swell period.** Long-period energy shoals differently
from short-period chop of the same height, so the correction the model is fitting has no
reason to be constant in period. It is a candidate rather than an assumption — `CANDIDATES`
includes sets with and without it, and the tuning split decides.
"""


def features(row: Row) -> dict[str, float]:
    """The full feature vector for one row, by name.

    One function, used by the fit, by the report and by `--check`. The backend builds the
    same vector from serving readings in `models/learned.py`; `test_learned.py` pins the two
    against each other, because a feature order that drifts between fit and serve is a bug no
    test of either side alone can see.
    """
    swell = math.radians(row.swell_direction_deg)
    wind = math.radians(row.wind_direction_deg)
    return {
        "combined_sea_m": row.combined_sea_m,
        "swell_height_m": row.swell_height_m,
        "swell_period_s": row.swell_period_s,
        "swell_direction_sin": math.sin(swell),
        "swell_direction_cos": math.cos(swell),
        "wind_speed_kmh": row.wind_speed_kmh,
        "wind_direction_sin": math.sin(wind),
        "wind_direction_cos": math.cos(wind),
        "combined_sea_x_period": row.combined_sea_m * row.swell_period_s,
    }


CANDIDATES: dict[str, tuple[str, ...]] = {
    "combined-sea-only": ("combined_sea_m",),
    "sea-and-swell": ("combined_sea_m", "swell_height_m", "swell_period_s"),
    "sea-swell-direction": (
        "combined_sea_m",
        "swell_height_m",
        "swell_period_s",
        "swell_direction_sin",
        "swell_direction_cos",
    ),
    "all-readings": (
        "combined_sea_m",
        "swell_height_m",
        "swell_period_s",
        "swell_direction_sin",
        "swell_direction_cos",
        "wind_speed_kmh",
        "wind_direction_sin",
        "wind_direction_cos",
    ),
    "all-readings-with-interaction": FEATURE_NAMES,
}
"""Nested feature sets, smallest first.

Nested on purpose: each adds one idea to the one above it, so a candidate winning says which
idea earned its place rather than that some arbitrary bundle scored well. The simplest is a
slope and an intercept on Combined Sea — a bias correction and nothing more — which is the
floor a richer model has to clear before its extra columns are worth carrying.
"""

WEIGHTINGS = ("uniform", "big-swell-weighted")
"""How the rarity of large swell is addressed, as a choice the tuning split makes.

Least squares minimises mean squared error over every row it is given, and #9's README counts
what it is given: 47.2% of rows are under 2 m and 1.0% are at or above 6 m. Fitted uniformly,
the coefficients are chosen almost entirely by ordinary seas, and the fit is free to trade
away accuracy exactly where the system earns its keep — a model can look excellent overall
and be worthless on the days somebody would fly to Portugal for.

`big-swell-weighted` reweights each row by its Combined Sea so the tail carries proportionate
influence. It is not assumed to be better: it buys the tail at the expense of the bulk, and
which trade wins is measured on the tuning split rather than asserted here. Whichever wins,
every reported figure is also broken down by size band, because a single aggregate number over
this distribution mostly describes small seas.
"""


def weights_for(rows: list[Row], weighting: str) -> np.ndarray:
    """Row weights for a weighting scheme.

    `big-swell-weighted` uses the Combined Sea itself, floored at 1 m so a flat calm cannot
    reach zero weight and drop out of the fit entirely. Weighting by an indicator instead —
    "count big rows ten times" — would put a discontinuity at an arbitrary height and let the
    fit see a cliff that is not in the ocean.
    """
    if weighting == "uniform":
        return np.ones(len(rows))
    if weighting == "big-swell-weighted":
        return np.array([max(row.combined_sea_m, 1.0) for row in rows])
    raise ValueError(f"unknown weighting {weighting!r}; expected one of {WEIGHTINGS}")


def design_matrix(rows: list[Row], columns: tuple[str, ...]) -> np.ndarray:
    """Rows by features, with a leading column of ones for the intercept."""
    built = [features(row) for row in rows]
    matrix = np.ones((len(rows), len(columns) + 1))
    for index, column in enumerate(columns, start=1):
        matrix[:, index] = [row[column] for row in built]
    return matrix


@dataclass(frozen=True)
class Fit:
    """A fitted model: which columns, in which order, with which coefficients."""

    columns: tuple[str, ...]
    weighting: str
    intercept: float
    coefficients: tuple[float, ...]
    rows_fitted: int

    def predict(self, rows: list[Row]) -> np.ndarray:
        matrix = design_matrix(rows, self.columns)
        return matrix @ np.array((self.intercept, *self.coefficients))


def fit(rows: list[Row], columns: tuple[str, ...], weighting: str) -> Fit:
    """Weighted least squares, solved with `lstsq` rather than the normal equations.

    `lstsq` is SVD-based and stays well behaved when two columns are nearly collinear, which
    these are: Combined Sea and swell height measure overlapping parts of the same sea, and
    the interaction column is a product of two others. Forming `XᵀX` and inverting it would
    square the condition number and can return large, opposite-signed coefficients that fit
    the training rows and generalise to nothing.

    Weights are applied as their square root to both sides, which is the standard reduction
    of weighted least squares to the ordinary problem: minimising `Σ wᵢ(yᵢ - ŷᵢ)²` is
    minimising the ordinary residual of `√w · y` against `√w · X`.
    """
    matrix = design_matrix(rows, columns)
    target = np.array([row.proxy_target_m for row in rows])
    root = np.sqrt(weights_for(rows, weighting))
    solution, *_ = np.linalg.lstsq(matrix * root[:, None], target * root, rcond=None)
    return Fit(
        columns=columns,
        weighting=weighting,
        intercept=float(solution[0]),
        coefficients=tuple(float(value) for value in solution[1:]),
        rows_fitted=len(rows),
    )


@dataclass(frozen=True)
class Score:
    """What a set of predictions was worth on a set of rows."""

    label: str
    rows: int
    mae: float
    rmse: float
    bias: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "subset": self.label,
            "rows": self.rows,
            "mae": round(self.mae, 4),
            "rmse": round(self.rmse, 4),
            "bias": round(self.bias, 4),
        }


def score(label: str, predicted: np.ndarray, rows: list[Row]) -> Score:
    """Mean absolute error, root mean squared error and bias, all in metres.

    Bias is signed and reported beside the magnitudes because they answer different
    questions. A model reading 0.3 m low on every big day is wrong in a way a user could be
    warned about; one that is 0.3 m out in both directions at random is not. Averaging them
    into a single accuracy number hides which of the two this is.
    """
    if not rows:
        return Score(label=label, rows=0, mae=float("nan"), rmse=float("nan"), bias=float("nan"))
    actual = np.array([row.proxy_target_m for row in rows])
    error = predicted - actual
    return Score(
        label=label,
        rows=len(rows),
        mae=float(np.mean(np.abs(error))),
        rmse=float(np.sqrt(np.mean(error**2))),
        bias=float(np.mean(error)),
    )


def baseline_prediction(rows: list[Row]) -> np.ndarray:
    """What `HeuristicBaseline.predict` returns: the input Combined Sea, carried through.

    Not a reimplementation of the rule — the rule's *conditions* are untouched here. This is
    the one line of it that emits a height, and `test_learned.py` pins the claim by driving
    the real `HeuristicBaseline` and checking it returns its own input.
    """
    return np.array([row.combined_sea_m for row in rows])


def load_rows() -> list[Row]:
    """The dataset, reduced to rows a model can both be fitted on and served.

    **Rows without wind are dropped.** Open-Meteo always serves wind, so a model that took a
    wind feature and met a missing value at serving time would have no defined behaviour;
    dropping them at fit time keeps training and serving over the same space. It costs the 763
    rows #9 counted — 747 of them the 2025 tail where ERA5 stops before the buoy does, and 16
    autumn fold hours — against 73,601, and the count is reported rather than assumed small.

    Monican01 is not read at all. It is present on 57.7% of rows and, more decisively, the
    live system has no access to it: an Offshore Observation is a measurement, not a forecast,
    so a model leaning on it could not be served. #9's README limitation 4 left the question
    open; this is the answer for #13, and it is a serving constraint rather than a finding
    about whether the column would have helped.
    """
    if not DATASET.exists():
        raise SystemExit(
            f"{DATASET} is missing. Rebuild it with:\n"
            "  .venv/Scripts/python.exe analysis/training_dataset/build.py"
        )
    rows: list[Row] = []
    with DATASET.open(encoding="utf-8", newline="") as handle:
        for record in csv.DictReader(handle):
            if record["wind_present"] != "true":
                continue
            rows.append(
                Row(
                    day=record["day"],
                    season=int(record["season"]),
                    combined_sea_m=float(record["hindcast_combined_sea_height_m"]),
                    swell_height_m=float(record["swell_height_m"]),
                    swell_period_s=float(record["swell_period_s"]),
                    swell_direction_deg=float(record["swell_direction_deg"]),
                    wind_speed_kmh=float(record["wind_speed_kmh"]),
                    wind_direction_deg=float(record["wind_direction_deg"]),
                    proxy_target_m=float(record["proxy_target_height_m"]),
                )
            )
    return rows


def split(rows: list[Row], seasons: tuple[int, ...]) -> list[Row]:
    return [row for row in rows if row.season in seasons]


BANDS: tuple[tuple[str, float, float], ...] = (
    ("under 2 m", 0.0, 2.0),
    ("2-3 m", 2.0, 3.0),
    ("3-4 m", 3.0, 4.0),
    ("4-5 m", 4.0, 5.0),
    ("5-6 m", 5.0, 6.0),
    ("6 m and above", 6.0, float("inf")),
)
"""Size bands on the *measured* Proxy Target, for reporting only.

Reporting bands is not the same act as selecting in a regime: `BIG_SWELL_M` is defined on the
input because a model must be able to identify its own regime at serving time, but a report
is written after the fact and can say what the sea actually did. Banding on the input instead
would let a model that systematically mistakes big seas for small ones hide in the wrong row.
"""


def band_of(target: float) -> str:
    for label, low, high in BANDS:
        if low <= target < high:
            return label
    return BANDS[-1][0]


def big_swell(rows: list[Row]) -> list[Row]:
    """The rows whose input Combined Sea puts them in the regime the system calls on."""
    return [row for row in rows if row.combined_sea_m >= BIG_SWELL_M]


def select(train: list[Row], tune: list[Row]) -> tuple[Fit, list[dict[str, Any]]]:
    """Choose a feature set and a weighting on the tuning split, and report every candidate.

    Selected on MAE over the tuning split's big-swell rows. The system exists to call the days
    somebody would fly for, so a candidate that wins on the 47% of hours under 2 m and loses
    at 5 m has won the wrong contest — and with this distribution, overall MAE is very nearly
    a measurement of the small-sea bulk.

    Every candidate's overall score is recorded beside its big-swell one, so a reader can see
    what the choice cost in the regime it was not made on.
    """
    tuning_big = big_swell(tune)
    if not tuning_big:
        raise RuntimeError(
            f"no tuning rows at or above {BIG_SWELL_M:g} m of Combined Sea, so a candidate "
            "cannot be selected in the regime it will be used in"
        )

    trials: list[dict[str, Any]] = []
    best: tuple[float, Fit] | None = None
    for name, columns in CANDIDATES.items():
        for weighting in WEIGHTINGS:
            candidate = fit(train, columns, weighting)
            big = score("tuning big swell", candidate.predict(tuning_big), tuning_big)
            overall = score("tuning overall", candidate.predict(tune), tune)
            trials.append(
                {
                    "candidate": name,
                    "weighting": weighting,
                    "features": len(columns),
                    "tuning_big_swell_mae": round(big.mae, 4),
                    "tuning_big_swell_bias": round(big.bias, 4),
                    "tuning_overall_mae": round(overall.mae, 4),
                    "tuning_overall_bias": round(overall.bias, 4),
                }
            )
            if best is None or big.mae < best[0]:
                best = (big.mae, candidate)

    assert best is not None
    return best[1], trials


def reliance(chosen: Fit, train: list[Row], held_out: list[Row]) -> list[dict[str, Any]]:
    """Which inputs the model actually leans on, measured two ways that can disagree.

    A raw coefficient is not an importance: swell period is measured in seconds around 12 and
    Combined Sea in metres around 2, so the same physical dependence produces coefficients an
    order of magnitude apart. The **standardised** coefficient — scaled by the feature's own
    standard deviation on the fitting rows — is in metres of predicted target per standard
    deviation of input, which is comparable across columns.

    It is still only a statement about the fitted surface, and with collinear columns it can
    be large for a feature the model does not need. So each feature is also **ablated**: the
    model is refitted without it and rescored on the held-out big-swell rows. The delta is
    what the column is worth in the regime that matters, and a column with a big standardised
    coefficient and no ablation cost is one whose work another column can do.

    Ablation refits rather than zeroing the coefficient. Zeroing asks "what if this feature
    vanished from a model built assuming it", which no model would ever be; refitting asks
    what a model built without it would have done, which is the question.
    """
    held_out_big = big_swell(held_out)
    baseline_mae = score("with", chosen.predict(held_out_big), held_out_big).mae
    deviations = {
        name: float(np.std([features(row)[name] for row in train])) for name in chosen.columns
    }

    reported: list[dict[str, Any]] = []
    for index, name in enumerate(chosen.columns):
        remaining = tuple(column for column in chosen.columns if column != name)
        if remaining:
            ablated = fit(train, remaining, chosen.weighting)
            without = score("without", ablated.predict(held_out_big), held_out_big).mae
        else:
            without = score("without", baseline_prediction(held_out_big), held_out_big).mae
        reported.append(
            {
                "feature": name,
                "coefficient": round(chosen.coefficients[index], 6),
                "standardised_coefficient": round(chosen.coefficients[index] * deviations[name], 4),
                "held_out_big_swell_mae_without": round(without, 4),
                "ablation_cost_m": round(without - baseline_mae, 4),
            }
        )
    reported.sort(key=lambda entry: -abs(entry["ablation_cost_m"]))

    # Every feature but the Combined Sea, ablated as a group.
    #
    # Necessary because the one-at-a-time numbers above understate them and would mislead on
    # their own. These columns are collinear — swell height and Combined Sea measure
    # overlapping parts of the same sea — so each can be dropped with the others absorbing its
    # work, and each therefore looks worthless. Dropping them together is the only way to ask
    # what the group is worth, and it is the difference between the shipped model and a plain
    # rescale of the Hindcast.
    if len(chosen.columns) > 1 and "combined_sea_m" in chosen.columns:
        alone = fit(train, ("combined_sea_m",), chosen.weighting)
        without = score("sea only", alone.predict(held_out_big), held_out_big).mae
        reported.append(
            {
                "feature": "(every feature except combined_sea_m, as a group)",
                "coefficient": "",
                "standardised_coefficient": "",
                "held_out_big_swell_mae_without": round(without, 4),
                "ablation_cost_m": round(without - baseline_mae, 4),
            }
        )
    return reported


def inference_cost(chosen: Fit, translations: dict[str, measure.Translation]) -> dict[str, Any]:
    """What one prediction costs, measured through the shipped path rather than through numpy.

    ADR 0004 requires the model be cheap because #15 runs it hundreds of times per forecast
    date. Timing `Fit.predict` would answer the wrong question — that is a vectorised numpy
    call over the whole array, and the running system evaluates one hour at a time in pure
    Python. So this imports the backend's own `LearnedAmplification`, built from the exported
    parameters, and times single `predict` calls the way `run_pipeline` makes them.
    """
    from nazarenow.models.learned import LearnedAmplification

    model = LearnedAmplification(parameters=exported(chosen, translations))
    readings = {
        "significant_wave_height": 4.2,
        "swell_height": 3.6,
        "swell_period": 14.0,
        "swell_direction": 292.0,
        "wind_speed": 11.0,
        "wind_direction": 95.0,
    }
    model.predict(readings)  # Warm the import and any first-call work out of the measurement.

    iterations = 20_000
    started = time.perf_counter()
    for _ in range(iterations):
        model.predict(readings)
    elapsed = time.perf_counter() - started

    per_call_us = elapsed / iterations * 1_000_000
    # #15's shape: a Predictive Distribution per date, for every date in a forecast range.
    evaluations = 500 * 14
    return {
        "iterations": iterations,
        "per_prediction_us": round(per_call_us, 2),
        "predictions_per_second": int(iterations / elapsed),
        "modelled_run_evaluations": evaluations,
        "modelled_run_seconds": round(per_call_us * evaluations / 1_000_000, 3),
    }


def residual_widths(chosen: Fit, held_out: list[Row]) -> dict[str, Any]:
    """How wide the model's own error is, on held-out rows, in the units #15 needs.

    **RMSE rather than MAE, and the distinction is the reason this exists.** Every accuracy
    figure this module publishes is an MAE, because MAE is what a reader should judge the
    model by — it is in metres and it is not dominated by the worst hours. A Predictive
    Distribution needs something else: a *width*, to combine with the Translation's
    `residual_rmse` and the Forecast Error Profile's `noise`, both of which are RMSEs. Mixing
    an MAE into that sum is an apples-to-oranges error worth roughly 25% on a Gaussian, and
    it would narrow the published range without appearing anywhere as a mistake.

    Both regimes, because the model's error grows with the sea and #15 serves both. The
    big-swell figure is the one that matters — it is the dominant term of the three at every
    Lead Time, which `analysis/forecast_error/README.md` names as the term to size first.

    Held out, not fitted. A residual measured on the rows the coefficients were chosen from
    would be optimistic exactly in the way ADR 0004 built this separation to avoid.
    """
    big = big_swell(held_out)
    return {
        "all_hours": score("held-out all hours", chosen.predict(held_out), held_out).as_dict(),
        "big_swell": score("held-out big swell", chosen.predict(big), big).as_dict(),
        "regime_m": BIG_SWELL_M,
        "measured_on": "held-out seasons, against the Proxy Target",
        "is_a_width": (
            "RMSE, for combining with translations.residual_rmse and the Forecast Error "
            "Profile's noise. The mae beside it is the reader's figure, not the width."
        ),
    }


def exported(
    chosen: Fit,
    translations: dict[str, measure.Translation],
    held_out_gold_days: int | None = None,
    residual: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The parameter file the backend reads, with the provenance of the fit beside it.

    Shaped after `thresholds.json`: numbers the running system needs, plus enough method for a
    reader to tell where they came from and what they rest on. A parameter file that carried
    only coefficients would be a set of magic numbers within a week.

    The translations ride along because inference has to apply them and the backend must not
    import analysis code to do it. They are recorded with the hours they were fitted on, so a
    reader can see the correction is measured rather than assumed.
    """
    return {
        "model": "learned-amplification",
        "quantity": "significant_wave_height_m",
        "target": "proxy_target_height_m",
        "features": list(chosen.columns),
        "intercept": chosen.intercept,
        "coefficients": list(chosen.coefficients),
        "weighting": chosen.weighting,
        "translations": {
            name: {
                "slope": translation.slope,
                "intercept": translation.intercept,
                "fitted_on_hours": translation.n,
                # Which hours those were. Since #58 the two quantities are fitted on
                # different subsets, so the count alone no longer identifies the subset —
                # and a reader who found 35064 against 4941 with nothing to explain the gap
                # would have to go to the source to learn whether that was deliberate.
                # Since #60 the string also names the *quantity* the subset is selected on,
                # because 3 m of Combined Sea and 3 m of Swell are different sets of hours.
                "fitted_on": translation.regime,
                "residual_rmse": translation.residual_rmse,
            }
            for name, translation in translations.items()
        },
        # The third and largest of the three terms a Predictive Distribution stacks (#15).
        # The other two already ship: `translations.residual_rmse` here, and `noise` in
        # `forecast_error.json`. This one had no home, so #15 could reach the two smaller
        # terms and not the one that dominates them both.
        "residual": residual,
        "method": {
            "ticket": 13,
            "fitted_on": f"{season_label(TRAIN_SEASONS[0])}-{season_label(TUNE_SEASONS[-1])}",
            "held_out": f"{season_label(HELD_OUT_SEASONS[0])}-{season_label(HELD_OUT_SEASONS[-1])}",
            "rows_fitted": chosen.rows_fitted,
            "selected_on": f"{season_label(TUNE_SEASONS[0])}-{season_label(TUNE_SEASONS[-1])}",
            # The number a reader needs to weigh the Gold Day figures, carried with the
            # numbers rather than left in a README. #12 set this precedent for the
            # thresholds and the reason is the same: a claim that travels without its
            # sample size gets quoted without it.
            "held_out_gold_days": held_out_gold_days,
            "selection_metric": (f"MAE on tuning rows with Combined Sea >= {BIG_SWELL_M:g} m"),
            "units": (
                "Fitted on the Copernicus IBI reanalysis. Serving readings arrive from "
                "Open-Meteo and are restated in reanalysis units by `translations` before "
                "the coefficients are applied (analysis/overlap/README.md)."
            ),
            "not_amplification": (
                "This fits the reanalysis's local error at Monican02, not the canyon's "
                "transformation toward Praia do Norte. See analysis/amplification_model/"
                "README.md and analysis/training_dataset/README.md limitation 1."
            ),
        },
    }


def _cell(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def write_csv(path: Path, header: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        for row in rows:
            writer.writerow([_cell(row[name]) for name in header])


def build() -> int:
    rows = load_rows()
    train = split(rows, TRAIN_SEASONS)
    tune = split(rows, TUNE_SEASONS)
    held_out = split(rows, HELD_OUT_SEASONS)

    print(
        f"{len(rows)} rows with wind: "
        f"{len(train)} training, {len(tune)} tuning, {len(held_out)} held out"
    )
    if not train or not tune or not held_out:
        raise SystemExit("a split is empty; the dataset does not cover the seasons this expects")

    chosen, trials = select(train, tune)
    print(f"chosen: {chosen.columns} weighted {chosen.weighting}")

    fitting = train + tune
    chosen = fit(fitting, chosen.columns, chosen.weighting)

    gold_days = training_dataset.read_gold_days()
    held_out_gold = [row for row in held_out if row.day in gold_days]
    subsets: list[tuple[str, list[Row]]] = [
        ("held-out: all hours", held_out),
        (f"held-out: Combined Sea >= {BIG_SWELL_M:g} m", big_swell(held_out)),
        ("held-out: Gold Day hours", held_out_gold),
    ]
    for label, low, high in BANDS:
        subsets.append(
            (
                f"held-out: measured target {label}",
                [row for row in held_out if low <= row.proxy_target_m < high],
            )
        )

    comparison: list[dict[str, Any]] = []
    for label, subset in subsets:
        learned = score(label, chosen.predict(subset), subset)
        baseline = score(label, baseline_prediction(subset), subset)
        comparison.append(
            {
                "subset": label,
                "rows": learned.rows,
                "baseline_mae": round(baseline.mae, 4),
                "learned_mae": round(learned.mae, 4),
                "mae_improvement_m": round(baseline.mae - learned.mae, 4),
                "baseline_bias": round(baseline.bias, 4),
                "learned_bias": round(learned.bias, 4),
                "baseline_rmse": round(baseline.rmse, 4),
                "learned_rmse": round(learned.rmse, 4),
            }
        )

    translations = measure.fit_translations()
    parameters = exported(
        chosen,
        translations,
        held_out_gold_days=len({row.day for row in held_out_gold}),
        residual=residual_widths(chosen, held_out),
    )
    MODEL_PATH.write_text(json.dumps(parameters, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {MODEL_PATH.relative_to(ROOT)}")

    write_csv(
        OUTPUT / "candidates.csv",
        (
            "candidate",
            "weighting",
            "features",
            "tuning_big_swell_mae",
            "tuning_big_swell_bias",
            "tuning_overall_mae",
            "tuning_overall_bias",
        ),
        trials,
    )
    write_csv(
        OUTPUT / "held_out_scores.csv",
        (
            "subset",
            "rows",
            "baseline_mae",
            "learned_mae",
            "mae_improvement_m",
            "baseline_bias",
            "learned_bias",
            "baseline_rmse",
            "learned_rmse",
        ),
        comparison,
    )
    write_csv(
        OUTPUT / "feature_reliance.csv",
        (
            "feature",
            "coefficient",
            "standardised_coefficient",
            "held_out_big_swell_mae_without",
            "ablation_cost_m",
        ),
        reliance(chosen, fitting, held_out),
    )

    cost = inference_cost(chosen, translations)
    write_csv(OUTPUT / "inference_cost.csv", tuple(cost), [cost])

    for entry in comparison:
        print(
            f"  {entry['subset']:<48} n={entry['rows']:<6} "
            f"baseline {entry['baseline_mae']:.3f} -> learned {entry['learned_mae']:.3f} "
            f"({entry['mae_improvement_m']:+.3f} m)"
        )
    print(f"  inference: {cost['per_prediction_us']} us per prediction")
    days = len({row.day for row in held_out_gold})
    print(f"  {len(held_out_gold)} held-out Gold Day hours, across {days} Gold Days")
    return 0


SAMPLE = Row(
    day="2018-01-18",
    season=2017,
    combined_sea_m=6.4,
    swell_height_m=5.9,
    swell_period_s=15.3,
    swell_direction_deg=291.0,
    wind_speed_kmh=13.0,
    wind_direction_deg=84.0,
    proxy_target_m=6.1,
)


def check() -> int:
    """Self-tests the arithmetic, the split and the export, with no dataset and no network.

    The fit itself cannot be asserted — #11 established why an accuracy figure in a test gets
    disabled within weeks. What is checkable is everything around it: that least squares
    recovers a relationship it was given, that the splits do not overlap, that a bearing near
    north behaves, and above all that the two encodings of the feature vector agree.
    """
    failures: list[str] = []

    def expect(condition: bool, message: str) -> None:
        if not condition:
            failures.append(message)

    # --- least squares recovers a relationship it was handed -------------------------------
    rng = np.random.default_rng(13)
    synthetic = [
        Row(
            day="synthetic",
            season=2011,
            combined_sea_m=float(sea),
            swell_height_m=float(sea) * 0.9,
            swell_period_s=float(period),
            swell_direction_deg=290.0,
            wind_speed_kmh=10.0,
            wind_direction_deg=90.0,
            # A known line: target = 0.4 + 1.15 x sea. Nothing else contributes.
            proxy_target_m=0.4 + 1.15 * float(sea),
        )
        for sea, period in zip(rng.uniform(0.5, 8.0, 400), rng.uniform(6.0, 18.0, 400), strict=True)
    ]
    recovered = fit(synthetic, ("combined_sea_m",), "uniform")
    expect(
        abs(recovered.intercept - 0.4) < 1e-6 and abs(recovered.coefficients[0] - 1.15) < 1e-6,
        f"least squares did not recover the planted line: {recovered}",
    )

    # A weighting must not change a fit the data determines exactly. If it does, the square
    # roots are being applied to one side only.
    weighted = fit(synthetic, ("combined_sea_m",), "big-swell-weighted")
    expect(
        abs(weighted.coefficients[0] - recovered.coefficients[0]) < 1e-6,
        "weighting changed a fit that the data determines exactly, so the weights are not "
        "being applied symmetrically to both sides",
    )
    expect(
        list(weights_for(synthetic[:3], "uniform")) == [1.0, 1.0, 1.0],
        "uniform weighting is not uniform",
    )
    expect(
        min(weights_for(synthetic, "big-swell-weighted")) >= 1.0,
        "big-swell weighting drops a calm row to below unit weight, which lets it leave the fit",
    )

    # --- the splits are disjoint and exhaustive over the seasons they name ------------------
    fitting = set(TRAIN_SEASONS) | set(TUNE_SEASONS)
    expect(
        not (set(TRAIN_SEASONS) & set(TUNE_SEASONS)),
        "the training and tuning splits share a Big-Wave Season",
    )
    expect(
        not (fitting & set(HELD_OUT_SEASONS)),
        "a fitting season also appears in the held-out split, so the evaluation is not held out",
    )
    expect(
        max(fitting) < min(HELD_OUT_SEASONS),
        "the held-out seasons are not strictly later than the fitting ones, so the model would "
        "be evaluated on its own past",
    )
    expect(season_label(2011) == "2011/12", "season labels do not match CONTEXT.md's form")
    expect(season_label(1999) == "1999/00", "a season crossing a century renders wrongly")

    # --- reporting bands cover the line without gaps or overlaps ----------------------------
    expect(band_of(0.0) == "under 2 m", "the lowest band does not start at zero")
    expect(band_of(1.999) == "under 2 m" and band_of(2.0) == "2-3 m", "band boundary is wrong")
    expect(band_of(99.0) == "6 m and above", "the top band does not absorb the tail")

    # --- scoring arithmetic -----------------------------------------------------------------
    rows = [SAMPLE]
    over = score("over", np.array([SAMPLE.proxy_target_m + 0.5]), rows)
    expect(
        abs(over.mae - 0.5) < 1e-9 and abs(over.bias - 0.5) < 1e-9,
        "a prediction half a metre high does not score as half a metre high and biased up",
    )
    under = score("under", np.array([SAMPLE.proxy_target_m - 0.5]), rows)
    expect(abs(under.bias + 0.5) < 1e-9, "bias is not signed, so it cannot say which way")
    expect(
        abs(score("baseline", baseline_prediction(rows), rows).bias - (6.4 - 6.1)) < 1e-9,
        "the baseline comparison is not the input Combined Sea carried through",
    )

    # --- the two feature encodings agree ----------------------------------------------------
    #
    # The one check here that no test on either side of the seam could make. `train.py` builds
    # the vector from dataset columns and `models/learned.py` builds it from serving readings;
    # if their orders or their trigonometry diverge, every coefficient lands on the wrong
    # column and the model keeps returning entirely plausible numbers.
    from nazarenow.models.learned import FEATURES as SERVED

    served_readings = {
        "significant_wave_height": SAMPLE.combined_sea_m,
        "swell_height": SAMPLE.swell_height_m,
        "swell_period": SAMPLE.swell_period_s,
        "swell_direction": SAMPLE.swell_direction_deg,
        "wind_speed": SAMPLE.wind_speed_kmh,
        "wind_direction": SAMPLE.wind_direction_deg,
    }
    here = features(SAMPLE)
    expect(
        set(SERVED) == set(FEATURE_NAMES),
        f"the backend builds {sorted(set(SERVED) ^ set(FEATURE_NAMES))} and this module does not",
    )
    for name in FEATURE_NAMES:
        if name in SERVED:
            expect(
                abs(SERVED[name](served_readings) - here[name]) < 1e-12,
                f"feature {name!r} differs between the fit and the backend: "
                f"{here[name]} here, {SERVED[name](served_readings)} served",
            )

    # --- a bearing near north is not a cliff ------------------------------------------------
    east = features(Row(**{**SAMPLE.__dict__, "swell_direction_deg": 1.0}))
    west = features(Row(**{**SAMPLE.__dict__, "swell_direction_deg": 359.0}))
    expect(
        abs(east["swell_direction_cos"] - west["swell_direction_cos"]) < 1e-3
        and abs(east["swell_direction_sin"] + west["swell_direction_sin"]) < 1e-3,
        "bearings either side of north do not encode as neighbours",
    )

    # --- the translation inverts what it applies --------------------------------------------
    translation = measure.Translation(
        variable="swell_period_s", slope=0.85, intercept=1.4, n=1, residual_rmse=0.0
    )
    expect(
        abs(translation.invert(translation.apply(13.7)) - 13.7) < 1e-9,
        "Translation.apply and Translation.invert are not inverses",
    )

    # --- the exported file is what the backend will accept ----------------------------------
    from nazarenow.models.learned import LearnedAmplification

    parameters = exported(
        Fit(
            columns=("combined_sea_m",),
            weighting="uniform",
            intercept=0.4,
            coefficients=(1.15,),
            rows_fitted=len(synthetic),
        ),
        {
            "significant_wave_height_m": measure.Translation(
                variable="significant_wave_height_m",
                slope=1.0,
                intercept=0.0,
                n=1,
                residual_rmse=0.0,
            ),
            "swell_period_s": measure.Translation(
                variable="swell_period_s", slope=1.0, intercept=0.0, n=1, residual_rmse=0.0
            ),
        },
    )
    expect(
        json.loads(json.dumps(parameters)) == parameters,
        "the exported parameters do not survive a JSON round trip",
    )
    predicted = LearnedAmplification(parameters=parameters).predict(served_readings)
    expect(
        abs(predicted.significant_wave_height - (0.4 + 1.15 * SAMPLE.combined_sea_m)) < 1e-9,
        "the backend does not reproduce the fit it was handed",
    )

    for failure in failures:
        print(f"  FAIL {failure}")
    print(f"{'ok' if not failures else 'FAILED'} - {len(failures)} failure(s)")
    return 1 if failures else 0


def main() -> int:
    if "--check" in sys.argv[1:]:
        return check()
    return build()


if __name__ == "__main__":
    raise SystemExit(main())

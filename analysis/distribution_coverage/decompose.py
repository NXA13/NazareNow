"""How much error does a Lead Time actually add? Measured, not assembled.

Ticket #82, second half. `ablation.py` found that the shipped budget's excess is almost
entirely a growth-rate error and that `drift` — the only term that grows — is the one carrying
it. What it could not say is **why**, because every column it prints is built from the same
three shipped terms. Removing a term tells you what that term is worth to the budget. It does
not tell you what the sea did.

This asks the question the other way round, and it needs no error budget at all.

**The idea is one subtraction.** Run the Amplification Model on the settled Combined Sea — the
provider's own analysis of the hour, which is the best incoming reading that will ever exist —
and score its prediction against the Proxy Target. That error is everything *except* forecast
error: the model's own residual, the Translation, and however far Monican02 sits from what the
model predicts. Call it the floor. Then run the same model on the **lead-N forecast** of the
same hour and score that. The difference, in quadrature, is what the forecast's Lead Time
actually cost.

    input_contribution(N) = sqrt( rmse(N)^2 - rmse(0)^2 )

That is the quantity `hypot(drift, translation_rmse) * amplification` is supposed to be, and
this measures it directly against outcomes instead of assembling it from two profiles that were
each measured against something else.

## Why this can settle what the ablation left open

`ablation.py` named two candidates for the oversize and could test neither:

**The profile may measure a change of mind rather than an error.** `drift` is the spread of
(lead-N forecast − the provider's own settled analysis). That is how much the forecast *moved*,
and a model revising itself is not the same thing as a model being wrong about the sea. If that
is the cause, `rmse(N)` will grow far more slowly than the shipped drift says, and
`input_contribution` will come out small.

**Or the terms may overlap.** `own_error` was fitted as a held-out residual, and if that fit
already absorbed some of the input error in front of it, adding the two in quadrature counts it
twice — which quadrature is entitled to do only if they are independent. If that is the cause,
`rmse(0)` — the floor, measured with no forecast error in it at all — will come out *below* the
shipped `own_error` it is supposed to correspond to.

The two make opposite predictions about different columns, so one run separates them.

## What this is not

**No sampler, no draws, no seed.** These are point predictions scored against outcomes, so
there is nothing here for a Monte Carlo to be right or wrong about. That is the point: it is
evidence from outside the machinery under test, and it is seconds rather than minutes.

**Both centres are reported, and the corrected one is the fair comparison.** `distribution.py`
centres at `sea - bias`, applying the profile's measured correction before widening anything, so
scoring the raw forecast would charge Lead Time for an error the shipped system already removes.
The raw column is kept beside it because the gap between them *is* what the bias correction is
worth, and #14's amendment records that it could not be applied symmetrically.

**The floor is not `own_error`.** It is `own_error` plus the Translation plus the Proxy Target's
own distance from the model's quantity, which is why it is read as an upper bound on the first
of those three and never as a measurement of it.

**Every caveat from `coverage.py` still applies**, with one that bites less: seven of eight
features are settled here too, but this scores the *same* features at every Lead Time, so the
approximation is common to every row and cannot manufacture a slope. It still flatters the
absolute level.

Run:
    .venv/Scripts/python.exe analysis/distribution_coverage/decompose.py
    .venv/Scripts/python.exe analysis/distribution_coverage/decompose.py --check
"""

from __future__ import annotations

import csv
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = HERE / "output"

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "analysis" / "forecast_error"))
sys.path.insert(0, str(ROOT / "backend" / "src"))

from profile import BIG_SWELL_M, load_proxy_target  # noqa: E402

from coverage import readings_at  # noqa: E402
from download_runs import LEAD_TIMES, Runs, waves, wind  # noqa: E402
from nazarenow.distribution import ErrorBudget  # noqa: E402
from nazarenow.models.base import AmplificationModel  # noqa: E402
from nazarenow.pipeline import amplification_model  # noqa: E402
from settled import settled  # noqa: E402

SETTLED_LEAD = 0
"""The floor's Lead Time. `readings_at` reads the archive's lead-0 entry, which is the
provider's settled analysis of the hour and the best incoming reading that can exist."""


@dataclass(frozen=True)
class Predicted:
    """One hour at one Lead Time, as a point prediction rather than a distribution."""

    hour: str
    lead: int
    observed: float
    raw: float
    """The model's prediction from the forecast as it arrived."""

    corrected: float
    """The same, from a forecast with the profile's measured bias removed first — which is
    where `distribution.py` puts the centre, so this is the column the shipped system earns."""


@dataclass(frozen=True)
class Error:
    """What a Lead Time's predictions cost, over one subset."""

    lead: int
    subset: str
    hours: int
    rmse_raw: float
    rmse: float
    bias: float
    """Mean signed error of the corrected prediction. Separates a centre that has moved from
    a spread that has grown — the same distinction `cover` draws with `below`/`above`."""


def predict_all(
    budget: ErrorBudget,
    model: AmplificationModel,
    sea: Runs,
    winds: Runs,
    swell: dict[str, dict[str, float]],
    observed: dict[str, float],
) -> list[Predicted]:
    """One point prediction per hour per Lead Time, plus the settled floor at lead 0.

    The bias correction is read from the same `ForecastError` the shipped builder reads and
    applied the same way — `sea - bias`, regime-split by `for_sea` — rather than recomputed
    here. A second copy of that rule would be free to disagree with the one under test.
    """
    rows: list[Predicted] = []
    for hour in sorted(swell):
        target = observed.get(hour)
        if target is None:
            continue
        for lead in (SETTLED_LEAD, *LEAD_TIMES):
            features = readings_at(hour, lead, sea, winds, swell)
            if features is None:
                continue
            raw_sea = float(features["significant_wave_height"])

            profile = budget.forecast.at(lead)
            # Lead 0 is the settled analysis, which has no forecast to be biased: `at(0)`
            # returns None by design and the correction is zero rather than extrapolated.
            bias = profile.for_sea(raw_sea).bias if profile is not None else 0.0

            raw = model.predict(features).significant_wave_height
            shifted = dict(features)
            shifted["significant_wave_height"] = max(0.0, raw_sea - bias)
            corrected = model.predict(shifted).significant_wave_height

            rows.append(
                Predicted(hour=hour, lead=lead, observed=target, raw=raw, corrected=corrected)
            )

    if not rows:
        raise RuntimeError("no archived hour carried both a forecast and a Proxy Target")
    return rows


def summarise(lead: int, subset: str, rows: list[Predicted]) -> Error:
    at_lead = [row for row in rows if row.lead == lead]
    if not at_lead:
        raise ValueError(f"lead {lead} ({subset}): nothing to summarise")
    return Error(
        lead=lead,
        subset=subset,
        hours=len(at_lead),
        rmse_raw=_rmse(row.raw - row.observed for row in at_lead),
        rmse=_rmse(row.corrected - row.observed for row in at_lead),
        bias=sum(row.corrected - row.observed for row in at_lead) / len(at_lead),
    )


def _rmse(errors) -> float:
    values = list(errors)
    return math.sqrt(sum(value * value for value in values) / len(values))


def contribution(floor: float, total: float) -> float | None:
    """What the Lead Time added, in quadrature, or `None` where it added nothing measurable.

    A Lead Time scoring *better* than the settled analysis is not a negative error — it is a
    sample in which the forecast happened to sit closer to the buoy than the analysis did, and
    a real quantity cannot be recovered from it. `None` says so rather than returning a zero
    that would read as a measurement.
    """
    if total <= floor:
        return None
    return math.sqrt(total * total - floor * floor)


def shipped_input(budget: ErrorBudget, lead: int, big: bool, amplification: float) -> float:
    """What the shipped budget claims the same Lead Time is worth, on the output side."""
    profile = budget.forecast.at(lead)
    if profile is None:
        return 0.0
    band = profile.big_swell if big else profile.all_hours
    return math.hypot(band.drift, budget.translation_rmse) * amplification


AMPLIFICATION_IS_FITTED_BY = "learned-amplification"
"""The one Amplification Model whose response `amplification_of` can read.

`amplification.json` holds *that* model's fitted coefficients. No other implementation has a
linear coefficient to read — the Heuristic Baseline carries its input through unchanged — so
the file answers for one model by name, not for whichever one the run is using.
"""


def amplification_of(model: AmplificationModel) -> float:
    """The model's linear response to the Combined Sea — how a metre of input error leaves.

    Read off the fitted coefficient rather than assumed, because it is the factor that turns
    an input-side term into the output-side quantity every row here is measured in.

    Refuses any other model rather than answering for it. `amplification_model()` picks its
    implementation from `NAZARENOW_MODEL`, so this function can be handed the Heuristic
    Baseline — and reading the learned coefficients regardless would print a plausible number
    from the wrong source beside a header naming the model it did not come from. That is the
    failure `pipeline.amplification_model` refuses a typo to prevent, and the one this whole
    module was written to correct: see `settled.py` on the merge that lost the forecast.
    """
    if model.name != AMPLIFICATION_IS_FITTED_BY:
        raise SystemExit(
            f"decompose.py measures against {AMPLIFICATION_IS_FITTED_BY!r}, and "
            f"NAZARENOW_MODEL selected {model.name!r}. amplification.json holds no "
            f"coefficient for it, and the run would report one model's error at another's "
            f"amplification. Unset NAZARENOW_MODEL to use the shipped default."
        )

    body = json.loads((ROOT / "backend" / "src" / "nazarenow" / "amplification.json").read_text())
    features = body["features"]
    return float(body["coefficients"][features.index("combined_sea_m")])


def write_errors(rows: list[Error]) -> Path:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / "lead_time_cost.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["lead_days", "subset", "hours", "rmse_raw_m", "rmse_m", "mean_error_m"])
        for row in rows:
            writer.writerow(
                [
                    row.lead,
                    row.subset,
                    row.hours,
                    round(row.rmse_raw, 4),
                    round(row.rmse, 4),
                    round(row.bias, 4),
                ]
            )
    return path


def report(errors: list[Error], budget: ErrorBudget, subset: str, amplification: float) -> None:
    rows = [row for row in errors if row.subset == subset]
    floor = next(row for row in rows if row.lead == SETTLED_LEAD)
    own = budget.own_error_big_swell if subset == "big swell" else budget.own_error_all_hours

    print(f"\n--- {subset} ---")
    print(
        f"Floor at the settled analysis: {floor.rmse:.3f} m over {floor.hours:,} hours "
        f"({floor.rmse_raw:.3f} m uncorrected). Shipped own_error is {own:.3f} m."
    )
    print(
        f"{'Lead':<6}{'RMSE':>9}{'raw':>9}{'mean err':>11}"
        f"{'lead cost':>12}{'budget says':>13}{'ratio':>8}"
    )
    for row in rows:
        if row.lead == SETTLED_LEAD:
            continue
        measured = contribution(floor.rmse, row.rmse)
        claimed = shipped_input(budget, row.lead, subset == "big swell", amplification)
        if measured is None:
            print(
                f"{row.lead}d{'':<4}{row.rmse:>9.3f}{row.rmse_raw:>9.3f}{row.bias:>11.3f}"
                f"{'none':>12}{claimed:>13.3f}{'—':>8}"
            )
            continue
        print(
            f"{row.lead}d{'':<4}{row.rmse:>9.3f}{row.rmse_raw:>9.3f}{row.bias:>11.3f}"
            f"{measured:>12.3f}{claimed:>13.3f}{claimed / measured:>8.2f}"
        )


def main() -> int:
    budget = ErrorBudget.shipped()
    model = amplification_model()
    amplification = amplification_of(model)
    print(f"Decomposing by Lead Time: model {model.name}, amplification {amplification:.4f}")

    observed = load_proxy_target()
    rows = predict_all(budget, model, waves(), wind(), settled(), observed)
    big = {hour for hour, value in observed.items() if value >= BIG_SWELL_M}

    errors: list[Error] = []
    for lead in (SETTLED_LEAD, *LEAD_TIMES):
        errors.append(summarise(lead, "all hours", rows))
        at_big = [row for row in rows if row.hour in big]
        if at_big:
            errors.append(summarise(lead, "big swell", at_big))

    for subset in ("all hours", "big swell"):
        report(errors, budget, subset, amplification)

    print(f"\nWrote {write_errors(errors).relative_to(ROOT)}")
    return 0


def check() -> int:
    """Re-check the committed table offline, in the shape the other two use."""
    failures: list[str] = []

    def expect(label: str, condition: bool, detail: str) -> None:
        if not condition:
            failures.append(f"{label}: {detail}")

    path = OUTPUT / "lead_time_cost.csv"
    if not path.exists():
        print(f"{path.relative_to(ROOT)} is missing; run decompose.py first")
        return 1

    with path.open(newline="", encoding="utf-8") as handle:
        table = list(csv.DictReader(handle))

    expect(
        "leads",
        {int(row["lead_days"]) for row in table} == {SETTLED_LEAD, *LEAD_TIMES},
        "the table does not carry the settled floor and every archived Lead Time",
    )

    for row in table:
        where = f"lead {row['lead_days']} ({row['subset']})"
        expect(
            f"{where} rmse positive",
            float(row["rmse_m"]) > 0.0,
            "an RMSE of zero would mean the model reproduced the buoy exactly",
        )
        expect(
            f"{where} mean error within rmse",
            abs(float(row["mean_error_m"])) <= float(row["rmse_m"]) + 1e-9,
            "a mean error larger than the RMSE it is drawn from is arithmetically impossible",
        )

    # The floor is the best incoming reading there is, so no Lead Time can beat it by much.
    # A forecast scoring *below* the settled analysis is sampling noise; one scoring far below
    # means the lead-0 column was built from the wrong reading, which is the failure that
    # would otherwise look like a clean result.
    for subset in {row["subset"] for row in table}:
        rows = [row for row in table if row["subset"] == subset]
        floor = next(float(r["rmse_m"]) for r in rows if int(r["lead_days"]) == SETTLED_LEAD)
        for row in rows:
            if int(row["lead_days"]) == SETTLED_LEAD:
                continue
            expect(
                f"lead {row['lead_days']} ({subset}) does not beat the settled analysis",
                float(row["rmse_m"]) >= floor * 0.95,
                f"RMSE {row['rmse_m']} against a settled floor of {floor:.4f}",
            )

    for failure in failures:
        print(f"FAIL {failure}")
    print(f"decompose.py --check: {len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(check() if "--check" in sys.argv else main())

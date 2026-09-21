"""Which of the three uncertainty terms is oversized?

Ticket #82. [#80](https://github.com/NXA13/NazareNow/issues/80) measured the assembled
Predictive Distribution against outcomes and found it too wide — 94.0% coverage at one day
against a nominal 90%, 99.4% at seven — and deliberately stopped at measuring. This is the
diagnosis that has to come before any repair.

`coverage.py` establishes that the sampler is doing exactly what the budget tells it: at seven
days the three shipped terms assemble to a total sigma of 0.643 m and a 90% width of 2.12 m,
against a measured median width of 2.19 m. The arithmetic is not in doubt. So one of the three
terms is bigger than the error it stands for, or two of them overlap — and #82 asks the
question the same way `coverage.py` already answers a smaller one, by rebuilding the budget
with a term removed and scoring what comes out.

## What is removed, and what is deliberately left alone

`ErrorBudget.distribution` widens in three places and centres in a fourth:

    input_sigma  = hypot(drift, translation_rmse)      # two input-side terms
    output_sigma = own_error(sea)                      # one output-side term
    centre       = sea - bias                           # not a width

**Only the widths are ablated. `bias` is kept in every variant, including the one that zeroes
the drift.** The two travel together in `Band` and it would be one `replace` to drop both, but
they answer different questions: `bias` moves where the range sits and `drift` moves how wide
it is, and this is a measurement of width against a centre that must therefore hold still.
Zeroing `bias` as well would change the coverage of every variant for a reason that has
nothing to do with the term being tested, and the seven-day correction is -0.230 m — an order
of magnitude above the sampling wobble it would be confounded with.

**Every variant is drawn on the same seed**, which is what makes this a paired comparison
rather than four independent measurements: `ErrorBudget.distribution` defaults to `SEED`, so
two variants scoring the same hour at the same Lead Time draw the same standard normals and
differ in exactly the term named. A per-variant seed would put sampling noise between the
columns and it would be indistinguishable from the effect being measured.

**One term at a time, never two.** Removing two leaves a width that can reach zero, and
`coverage._normalised` raises on a range with no width rather than dividing by it. That is the
right refusal — a budget with one term left is not a smaller budget, it is a different claim —
so the overlap question in #82 is read off the single-term columns rather than asked directly.
See "Reading the result" below.

## Reading the result

Three outcomes, and #82 attaches a different repair to each.

- **One term dominates.** Its column's widening factor lands nearest 1.00 across Lead Times —
  removing it alone very nearly calibrates the range. The repair is to re-measure that term
  against the thing it is supposed to stand for.
- **The terms overlap.** No single column reaches 1.00, but the shipped total sigma exceeds
  what the outcomes justify by more than any one term accounts for. Quadrature claims
  independence; this is the test of that claim against outcomes, which `distribution.py`
  argues for but has never had.
- **No single term.** The columns move together and none approaches 1.00 at every Lead Time,
  which points at the growth *rate* rather than a component — and the honest repair is to fit
  the width against measured coverage per Lead Time rather than assembling it.

`widening_factor` is the number to read, not `covered`. It is the multiple the half-width
would have to be scaled by for 90% of outcomes to fall inside, so 1.00 is calibrated, above 1
is too narrow and below 1 is too wide. Coverage saturates — 99.4% and 99.9% are nearly the
same number and describe very different ranges — while the factor keeps resolving all the way
down. `coverage.cover` computes both and this module reuses it unchanged.

## What this inherits from #80, unchanged

Every caveat on `coverage.py`'s header applies here identically, because this scores the same
hours through the same builder. Two of them flatter the result and one narrows what it can
settle: seven of eight features are settled rather than forecast, no ensemble term is
included, and the span holds one partial Big-Wave Season. The ensemble omission matters most
to how this table is read — it understates the width at short Lead Time and barely at long, so
a term that looks oversized at one day is the one figure here that a live ensemble could
move. It cannot rescue seven days, where the archive overtakes the ensemble by six.

**This runs on the interval join alone** — the 1,593 hours carrying both an archived forecast
and a Proxy Target — and not on the wider join `coverage.py`'s gate table uses. Coverage is
the only question asked here and it is the only join that can answer it.

Run:
    .venv/Scripts/python.exe analysis/distribution_coverage/ablation.py

    # Re-checks the committed table's arithmetic and internal agreement, offline.
    .venv/Scripts/python.exe analysis/distribution_coverage/ablation.py --check
"""

from __future__ import annotations

import csv
import math
import sys
from dataclasses import replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = HERE / "output"

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "analysis" / "forecast_error"))
sys.path.insert(0, str(ROOT / "backend" / "src"))

from profile import load_proxy_target  # noqa: E402

from coverage import (  # noqa: E402
    NOMINAL,
    Coverage,
    Scored,
    _median,
    big_hours,
    cover,
    readings_at,
)
from download_runs import LEAD_TIMES, Runs, waves, wind  # noqa: E402
from nazarenow.distribution import ErrorBudget  # noqa: E402
from nazarenow.models.base import AmplificationModel  # noqa: E402
from nazarenow.pipeline import amplification_model  # noqa: E402
from nazarenow.thresholds import load as load_thresholds  # noqa: E402
from settled import settled  # noqa: E402

SHIPPED = "shipped"
NO_DRIFT = "no drift"
NO_TRANSLATION = "no translation"
NO_OWN_ERROR = "no own_error"

FACTOR_BOUNDARY_BAND = 0.0075
"""How close to 1.00 the widening factor may sit before `--check` stops asking it to agree with
the coverage about direction.

Measured, not chosen: on the corrected table the two rows where the factor and the coverage
disagree sit 0.0029 and 0.0047 from 1.00, and the nearest row that *agrees* sits 0.0108 out.
This falls between them rather than on either edge.

It replaces #144's `COVERAGE_BOUNDARY_BAND`, which read the same exemption off the coverage —
the discriminator that table supported and this one does not. The comment at the use site
carries both measurements and why the guard is not simply given both bands.
"""

VARIANTS = (SHIPPED, NO_DRIFT, NO_TRANSLATION, NO_OWN_ERROR)
"""The shipped budget and the three single-term removals, in the order they are reported.

Named as constants rather than written inline because each string is a CSV value, a print
header and a `--check` assertion — three places for a typo to become a silently missing
column.
"""


def without_drift(budget: ErrorBudget) -> ErrorBudget:
    """The budget with the forecast drift removed and its bias correction kept.

    `Band` carries both, so this rebuilds `by_lead_time` band by band rather than replacing
    the profile wholesale. The header argues why `bias` stays; the mechanical reason it needs
    a loop is that `drift` lives two levels down — `ForecastError.by_lead_time[lead]` holds a
    `LeadTime`, which holds the two `Band`s that `for_sea` chooses between, and both have to
    go to zero or the big-swell hours would keep a term the all-hours ones had lost.
    """
    forecast = budget.forecast
    flattened = {
        lead: replace(
            profile,
            all_hours=replace(profile.all_hours, drift=0.0),
            big_swell=replace(profile.big_swell, drift=0.0),
        )
        for lead, profile in forecast.by_lead_time.items()
    }
    return replace(budget, forecast=replace(forecast, by_lead_time=flattened))


def budgets(shipped: ErrorBudget) -> dict[str, ErrorBudget]:
    """The four budgets to score, each one `replace`d off the shipped one.

    Built by mutating the real budget rather than by constructing four by hand, for the reason
    `coverage.score` gives about its own control: the variants then differ in exactly the term
    named and in nothing else, including every term that gets added to `ErrorBudget` later.
    """
    return {
        SHIPPED: shipped,
        NO_DRIFT: without_drift(shipped),
        NO_TRANSLATION: replace(shipped, translation_rmse=0.0),
        NO_OWN_ERROR: replace(shipped, own_error_all_hours=0.0, own_error_big_swell=0.0),
    }


def score_variants(
    shipped: ErrorBudget,
    model: AmplificationModel,
    sea: Runs,
    winds: Runs,
    swell: dict[str, dict[str, float]],
    observed: dict[str, float],
    height_bar_m: float,
) -> dict[str, list[Scored]]:
    """Build every variant's distribution for every hour that carries a Proxy Target.

    The hour loop is shared across the four budgets rather than run four times, so a variant
    can never be scored on a different set of hours than its neighbours — which would show up
    as a difference in the coverage column and read as an effect of the term.
    """
    variants = budgets(shipped)
    rows: dict[str, list[Scored]] = {name: [] for name in VARIANTS}

    for hour in sorted(swell):
        # The interval join, not the wider gate one: an hour with no Proxy Target cannot
        # answer whether the range held, and building its four distributions would be most of
        # this module's runtime spent on rows that are filtered out before the table.
        target = observed.get(hour)
        if target is None:
            continue
        if sea.readings.get(hour, {}).get(0, {}).get("wave_height") is None:
            continue
        for lead in LEAD_TIMES:
            features = readings_at(hour, lead, sea, winds, swell)
            if features is None:
                continue
            for name in VARIANTS:
                built = variants[name].distribution(
                    model, features, lead, height_bar_m=height_bar_m
                )
                low, high = built.range_m
                rows[name].append(
                    Scored(
                        hour=hour,
                        lead=lead,
                        observed=target,
                        centre=_median(built),
                        p5=low,
                        p95=high,
                        # The gate is not this module's question. `coverage.Scored` requires
                        # both probabilities, so they are carried at their real values for the
                        # shipped variant's sake and never read.
                        gate_probability=built.height_bar_probability or 0.0,
                        gate_probability_drift_only=built.height_bar_probability or 0.0,
                        settled_sea=float(sea.readings[hour][0]["wave_height"]),
                    )
                )

    if not rows[SHIPPED]:
        raise RuntimeError("no archived hour carried both a forecast and a Proxy Target")
    return rows


def collapse(rows: dict[str, list[Scored]]) -> list[tuple[str, Coverage]]:
    """Every variant, at every Lead Time, over both subsets `coverage.py` reports.

    `cover` is imported rather than reimplemented. It is the function whose output #80's
    published table is made of, and a second copy here would be free to disagree with the
    number this ablation is supposed to be read against.
    """
    big = big_hours(rows[SHIPPED])
    out: list[tuple[str, Coverage]] = []
    for name in VARIANTS:
        for lead in LEAD_TIMES:
            at_lead = [row for row in rows[name] if row.lead == lead]
            out.append((name, cover(lead, "all hours", at_lead)))
            big_at_lead = [row for row in at_lead if row.hour in big]
            if big_at_lead:
                out.append((name, cover(lead, "big swell", big_at_lead)))
    return out


def write_ablation(rows: list[tuple[str, Coverage]]) -> Path:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / "term_ablation.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "variant",
                "lead_days",
                "subset",
                "hours",
                "nominal",
                "covered",
                "below_p5",
                "above_p95",
                "median_width_m",
                "median_normalised",
                "widening_factor",
            ]
        )
        for name, row in rows:
            writer.writerow(
                [
                    name,
                    row.lead,
                    row.subset,
                    row.hours,
                    NOMINAL,
                    round(row.covered, 4),
                    round(row.below, 4),
                    round(row.above, 4),
                    round(row.median_width_m, 4),
                    round(row.median_normalised, 4),
                    round(row.widening_factor, 4),
                ]
            )
    return path


def print_table(rows: list[tuple[str, Coverage]], subset: str, column: str) -> None:
    """One variant per column, one Lead Time per row, for the figure named.

    Printed variant-across rather than variant-down because the comparison the ticket asks
    for is between the four at a fixed Lead Time, and a reader should not have to hold seven
    rows in their head to make it.
    """
    print(f"\n{column} — {subset}. Nominal {NOMINAL:.0%}, calibrated factor 1.00.")
    header = f"{'Lead':<6}" + "".join(f"{name:>17}" for name in VARIANTS)
    print(header)
    for lead in LEAD_TIMES:
        cells = []
        for name in VARIANTS:
            found = [
                row
                for key, row in rows
                if key == name and row.lead == lead and row.subset == subset
            ]
            if not found:
                cells.append(f"{'—':>17}")
                continue
            value = getattr(found[0], column_field(column))
            cells.append(f"{value:>17.2f}" if column != "Coverage" else f"{value:>16.1%} ")
        print(f"{lead}d{'':<4}" + "".join(cells))


def column_field(column: str) -> str:
    """The `Coverage` attribute a printed column reads.

    A lookup rather than the column name lowered, so that renaming a heading for a reader
    cannot silently start reading a different field.
    """
    return {
        "Widening factor": "widening_factor",
        "Median width (m)": "median_width_m",
        "Coverage": "covered",
    }[column]


def sigma_table(shipped: ErrorBudget) -> None:
    """The three terms' assembled sigma per Lead Time, on the all-hours band.

    Context for the ablation rather than a result of it: it says what each term is *worth*
    before any outcome is consulted, which is what makes a column that barely moves
    interpretable. Printed for the all-hours band at a sea below the regime bar, matching the
    subset the first table reports.
    """
    print("\nWhat each term contributes, before outcomes. All-hours band, sub-regime sea.")
    print(f"{'Lead':<6}{'drift':>10}{'translation':>14}{'own_error':>12}{'total':>10}")
    for lead in LEAD_TIMES:
        profile = shipped.forecast.at(lead)
        if profile is None:
            continue
        drift = profile.all_hours.drift
        translation = shipped.translation_rmse
        own = shipped.own_error_all_hours
        # The input pair combines in quadrature and is then amplified by the model before
        # `own_error` joins it on the output side, so this total is the input hypot alone
        # beside the output term — not the served sigma, which carries the amplification
        # `coverage.py`'s header works through. It is a ranking of the terms, not a width.
        total = math.hypot(math.hypot(drift, translation), own)
        print(f"{lead}d{'':<4}{drift:>10.3f}{translation:>14.3f}{own:>12.3f}{total:>10.3f}")


def main() -> int:
    thresholds = load_thresholds()
    height_bar_m = thresholds.minimum_significant_wave_height_m
    shipped = ErrorBudget.shipped()
    model = amplification_model()

    print(f"Ablating the shipped budget: model {model.name}, height bar {height_bar_m} m")
    sigma_table(shipped)

    rows = score_variants(
        shipped, model, waves(), wind(), settled(), load_proxy_target(), height_bar_m
    )
    hours = {row.hour for row in rows[SHIPPED]}
    print(f"\n{len(hours):,} hours carrying a Proxy Target, scored under {len(VARIANTS)} budgets")

    collapsed = collapse(rows)
    for subset in ("all hours", "big swell"):
        print_table(collapsed, subset, "Widening factor")
        print_table(collapsed, subset, "Coverage")
        print_table(collapsed, subset, "Median width (m)")

    print(f"\nWrote {write_ablation(collapsed).relative_to(ROOT)}")
    return 0


def check() -> int:
    """Re-check the committed table offline, in the shape `coverage.py --check` established.

    It cannot re-derive the distributions — that needs the archive — so it pins the properties
    a wrong table would break: the shares that must sum, the variants that must all be
    present, and the two internal agreements that would catch a column written from the wrong
    variant.
    """
    failures: list[str] = []

    def expect(label: str, condition: bool, detail: str) -> None:
        if not condition:
            failures.append(f"{label}: {detail}")

    path = OUTPUT / "term_ablation.csv"
    if not path.exists():
        print(f"{path.relative_to(ROOT)} is missing; run ablation.py first")
        return 1

    with path.open(newline="", encoding="utf-8") as handle:
        table = list(csv.DictReader(handle))

    expect(
        "variants",
        {row["variant"] for row in table} == set(VARIANTS),
        "the table does not carry exactly the shipped budget and its three removals",
    )
    expect(
        "leads",
        {int(row["lead_days"]) for row in table} == set(LEAD_TIMES),
        "the table does not cover exactly the archive's Lead Times",
    )

    for row in table:
        where = f"{row['variant']} lead {row['lead_days']} ({row['subset']})"
        covered = float(row["covered"])
        below, above = float(row["below_p5"]), float(row["above_p95"])
        expect(
            f"{where} shares",
            math.isclose(covered + below + above, 1.0, abs_tol=5e-4),
            f"covered + below + above is {covered + below + above:.4f}, not 1",
        )
        expect(
            f"{where} width",
            float(row["median_width_m"]) > 0.0,
            "a stated range with no width means every term was removed at once",
        )
        # The two readings of one fact must not disagree about direction — but only where
        # the coverage is far enough from nominal for there to be a direction to agree about.
        # `coverage.py --check` asserts this unconditionally; that holds for the shipped
        # budget's seven rows and is fragile, and an ablated budget breaks it outright.
        #
        # They measure the miss differently. `covered` counts outcomes outside `[p5, p95]`,
        # which is asymmetric about the centre because the samples are floored at zero on
        # both sides of the model; `widening_factor` is the 90th percentile of the miss
        # expressed *symmetrically* about the median. When a range is genuinely mis-sized
        # the two agree, because the width swamps the skew. When the coverage sits on 90%
        # there is nothing left for the width to say, and which side it falls is decided by
        # the skew alone.
        #
        # **Gated on the factor, not on the coverage**, and that has now moved twice. The guard
        # first used a band of 0.01 on the factor, calibrated against a table the `readings_at`
        # defect had produced. #144 re-derived it on corrected numbers and moved it to the
        # coverage: both disagreements then sat within 0.21 percentage points of nominal while
        # a factor band could not separate them. #145 moves it back, for the same reason in
        # reverse. Over the corrected 56 rows two still disagree — `no translation` at seven
        # days all hours (factor 1.0029, coverage 90.10%) and `no own_error` at four days all
        # hours (factor 0.9953, coverage 88.78%). The second is 1.22 points off nominal, far
        # outside any honest coverage band, while an *agreeing* row sits 0.35 points off; no
        # coverage band separates those. On the factor they separate cleanly — the two
        # disagreements sit 0.0029 and 0.0047 from 1.00 against a nearest agreeing row at
        # 0.0108 — so the factor is the discriminator this table supports.
        #
        # **Deliberately not "either band".** Exempting a row when *either* reading is at its
        # boundary looks like the stable generalisation, and it is strictly weaker: an `or` can
        # only add exemptions. It would have released five rows rather than two, and the three
        # extra are all released by the coverage leg — including `shipped` at seven days in
        # both subsets, which are the rows the one surviving finding rests on. Buying stability
        # against a future table by lifting the direction check off today's published rows is
        # the wrong trade. Re-derive this the next time the table moves; that is what a
        # tripwire is for.
        factor = float(row["widening_factor"])
        if abs(factor - 1.0) > FACTOR_BOUNDARY_BAND:
            expect(
                f"{where} factor agrees with coverage",
                (factor > 1.0) == (covered < NOMINAL),
                f"factor {factor} against coverage {covered:.4f}",
            )

    # Removing a term can only narrow the range. A variant wider than the shipped budget at
    # the same Lead Time means a column was written from the wrong variant — the one failure
    # this check exists to catch, because such a table would still look entirely plausible.
    by_key = {
        (row["variant"], int(row["lead_days"]), row["subset"]): float(row["median_width_m"])
        for row in table
    }
    for (variant, lead, subset), width in by_key.items():
        if variant == SHIPPED:
            continue
        full = by_key.get((SHIPPED, lead, subset))
        if full is None:
            continue
        expect(
            f"{variant} lead {lead} ({subset}) narrows",
            width <= full,
            f"median width {width:.4f} m exceeds the shipped {full:.4f} m, "
            "which removing a term cannot do",
        )

    for failure in failures:
        print(f"FAIL {failure}")
    print(f"ablation.py --check: {len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(check() if "--check" in sys.argv else main())

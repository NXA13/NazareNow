"""Assemble the published track record from the reports that already measured it.

Ticket #16. The site needs to show a reader what the system called and what actually
happened, before asking them to spend money on a Go Call. Every number that answers that is
already committed somewhere in `analysis/` — this script collects them into one file the
backend serves, and computes nothing of its own.

**Nothing here measures anything.** That is the design, not a shortcut. A second calculation
of the same figure is a second answer, and the one on the website would be the one nobody
re-derives. So the inputs are the committed reports, each cited on the field it produced:

| Section | Source | Ticket |
|---|---|---|
| both panels, and the day-by-day record | `analysis/backtest/output/daily_calls.csv` | #11, #87 |
| delivered sea per tier | `analysis/backtest/output/delivery.csv` | #83 |
| scored height accuracy | `analysis/amplification_model/output/held_out_scores.csv` | #13 |
| served height accuracy | `analysis/amplification_model/output/translation_shapes.csv` | #52 |
| range calibration | `analysis/distribution_coverage/output/interval_coverage.csv` | #80, #94 |
| Gold Day split | `backend/src/nazarenow/thresholds.json` | #12 |

**Both panels come from one scoring run, since #87.** They used not to: the held-out block came
from `calibrated_scores.csv` and the whole-record block from `summary.csv`, and those two score
the same record with different bars — the fit's, in reanalysis units, against the shipped ones
translated into Open-Meteo units. The page renders both panels to a reader whose reason for
having two is to compare them. `summary.csv` and `calibrated_scores.csv` are still read, but as
independent references in `--check` rather than as sources; `tier_counts_from_days` has the whole
argument.

**The served figures are #52's, not `served_path.py`'s** — though since #58 the two nearly
agree. `output/served_path_scores.csv` reconstructs the operational series using the shipped
Translation and then scores a model that inverts that same Translation, so any error in the
transform is partly measured against itself.

Before #58 that was worth 0.11 m. The shipped Translation was fitted on the big-swell subset
alone and extrapolated about 0.34 m below its fitted range, handing that error to the baseline
as a free upward shift; its `all hours` and `under 2 m` rows read +0.035 and +0.074 — in the
learned model's favour — where a generator tracking the measured pairing read **-0.077** and
**-0.126**. Publishing the first pair would have put the most flattering number on the page and
had it be an artefact of the transform under test.

#58 refitted the height Translation on all 35,064 overlapping hours, so the shipped line now
nearly *is* a generator that tracks the measured pairing: `served_path.py` reads -0.014 and
-0.033 against this module's -0.016 and -0.035. The indirection is kept anyway, because it costs
nothing and the guarantee it provides — that the published number is not scored against its own
generator — should not depend on the two happening to agree.

The rows taken here are `translation_shapes.csv` filtered to the shipped candidate under the
`regime-aware` generator with a flat residual, which is what
`analysis/amplification_model/README.md` prints as the *fair generator* column.

**Rates are not written.** The file carries counts and the backend divides, so a recall on
the page cannot disagree with the counts beside it. See `backend/src/nazarenow/track_record.py`.

`--check` runs offline against the committed reports and needs no credentials and no
download. It pins the joins that would silently publish a wrong number: the season counts
against the rates `calibrate.py` published independently; the served rows against the
generator they must come from; the Gold Day split against the shipped threshold file; #83's
delivered sea against the flagged-day count the waste figure beside it divides by; and, since
#87, both published panels against the two summary reports that describe them — exactly, for
the one scored with the same bars, and by recall alone for the one scored with the fit's.

Run:
    .venv/Scripts/python.exe analysis/track_record/publish.py

    # Self-tests every join, offline.
    .venv/Scripts/python.exe analysis/track_record/publish.py --check
"""

from __future__ import annotations

import csv
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

CALIBRATED = ROOT / "analysis" / "calibration" / "output" / "calibrated_scores.csv"
SUMMARY = ROOT / "analysis" / "backtest" / "output" / "summary.csv"
DAILY = ROOT / "analysis" / "backtest" / "output" / "daily_calls.csv"
SCORED = ROOT / "analysis" / "amplification_model" / "output" / "held_out_scores.csv"
SHAPES = ROOT / "analysis" / "amplification_model" / "output" / "translation_shapes.csv"
DELIVERY = ROOT / "analysis" / "backtest" / "output" / "delivery.csv"
COVERAGE = ROOT / "analysis" / "distribution_coverage" / "output" / "interval_coverage.csv"
THRESHOLDS = ROOT / "backend" / "src" / "nazarenow" / "thresholds.json"

DESTINATION = ROOT / "backend" / "src" / "nazarenow" / "track_record.json"

PANEL = "reanalysis"
"""The backtest panel the whole-record figures come from.

This and the two names below are `daily_calls.csv`'s own column values, quoted so the join
matches — not this project's vocabulary for what they hold. What the panel actually carries
is the Hindcast; `CONTEXT.md` bars the report's spelling as a name for it, and nothing
published from here uses it.

`daily_calls.csv` also carries an `operational (diagnostic)` panel over 2022-2025 and a
superseded `reconstructed` one. Mixing panels would double-count days: the same date appears
in more than one, scored against a different product each time.
"""

HELD_OUT_FROM = "2020/21"
"""The first held-out Big-Wave Season, matching `thresholds.json`'s `validated_on`.

Seasons sort lexicographically because they are named `YYYY/YY` from the year they begin, so
a string comparison is the chronological one. `--check` pins the resulting count against the
per-season rates `calibrate.py` published from its own split.
"""

SERVED_GENERATOR = "regime-aware"
SERVED_CANDIDATE = "shipped"
SERVED_SCATTER = "flat"
"""The shipped transform, measured under a generator that tracks the real IBI/Open-Meteo
pairing at every size. See the module docstring for why the other generator's rows are not
publishable."""

TIERS = ("watch_or_better", "go_call")
"""The two tiers, under the names both the reports and the backend use. #16 requires them
reported separately and never as one figure."""

DELIVERED_TIERS = TIERS
"""The tiers whose delivered sea is published — both, since #87.

#83 adds what the flagged days *did* — the sea they peaked at — beside what the Gold Days say
about them, because the Gold Day figure alone reads as 79% waste on a Go Call tier where every
held-out call landed on a day the sea passed 2.8 m. It reads as **94%** on the Watch tier, which
needs the counterweight more, not less.

It shipped with the Go Call alone because the Watch tier's denominator disagreed between the two
reports the page was assembled from, 199 against 193. #87 removed the disagreement by counting
both panels from one scoring run rather than by reconciling two, so the join now holds for both
tiers. `delivered_for` still refuses a mismatch; there is simply no longer one.
"""

DELIVERY_LADDER = (3.0, 4.0, 5.0, 6.0)
"""The thresholds published from `delivery.csv`, named here rather than read off its header.

The same rule `BAND_LABELS` follows: a column this script has no name for is a report that
changed shape, and passing it through would put a threshold nobody chose on the page. Stated as
a tuple so the order on the page is this file's decision and not the CSV writer's.
"""

RANGE_SUBSETS = {"all hours": "all_hours", "big swell": "big_swell"}
"""`interval_coverage.csv`'s two subsets, mapped to the names the record publishes them under.

Both travel on every Lead Time, as named fields rather than a list, for the reason `TIERS`
gives: the `big swell` rows cover the bigger seas and are the more flattering of the two, so a
record that could carry one subset alone would render the kinder number under a heading that
reads as the whole finding.
"""

BIG_SWELL_M = 3.0
"""The Significant Wave Height the `big swell` subset is drawn at, published rather than typed.

A copy of `analysis/forecast_error/profile.py`'s constant of the same name, which
`coverage.py` imports and scores the subset with, and `--check` pins the two together.
Published so the page states the bar from the record instead of carrying a literal that
survives the report changing underneath it.

**It is not the height bar a Go Call rests on.**
`thresholds.json` sets that at 2.75 m [now:minimum_significant_wave_height_m], and
`analysis/distribution_coverage/README.md` is explicit that 3 m is an analysis choice, drawn
there "rather than at a Gold Day". Calling this subset the sea a Go Call is issued on would
state something false about the one number a reader is being asked to spend money on — which
is the failure this whole section was added to end rather than to commit again.
"""

BIG_SWELL_SOURCE = ROOT / "analysis" / "forecast_error" / "profile.py"
"""Where `BIG_SWELL_M` is defined. Read as text by `--check`: importing it would drag in the
profile module's dependencies for one float, and the pin only needs the literal."""

RANGE_UNDERSTATES_BECAUSE = (
    "The range this system actually prints is wider still. Every distribution measured here "
    "was built without the wave models' disagreement term, which only ever widens a range, so "
    "the real coverage at short notice is higher than the figures above and the gap is larger "
    "than they show."
)
"""Why the measurement is a floor rather than an estimate.

`analysis/distribution_coverage/README.md`, "What this cannot settle": every distribution in
that run was built with `model_spread=None`, because no per-Lead-Time ensemble archive exists,
and `_drift_floor` can only raise the drift. So this moves finding 1 in the direction it
already points. It lives in that README's prose and `--check` cannot verify it, which is the
same position `GOLD_DAY_CAVEAT` is in.
"""

RANGE_RESTS_ON = (
    "It rests on one partial Big-Wave Season. The 1,593 hours run from 2025-11-26 to "
    "2026-02-20 and cluster into a few dozen swells rather than standing as independent "
    "chances to be wrong, and the window holds a single confirmed giant day. Nothing here "
    "says how the range behaves on the days this system exists for."
)
"""The evidence behind the table, stated where the table is rather than at the foot of a page.

Same README, same section. The hours are correlated, the span is one winter, and the only Gold
Day inside it is 2025-12-13. A reader who takes "1,593 hours" as the sample size has been told
the flattering half of a two-part fact — the same failure `TierRow` exists to prevent.
"""

GOLD_DAY_CAVEAT = (
    "120 hours across only 5 Gold Days — the held-out seasons hold 13, but training also "
    "requires the buoy to have been reporting and the wind to be present, and only 5 survive "
    "both."
)
"""The one figure on the page that is typed here rather than joined from a report.

`analysis/amplification_model/README.md` says of the Gold Day row: "Five days is far too few
to carry the headline on its own", and "that is the number to hold this claim to". The count
lives only in that README's prose — `held_out_scores.csv` carries hours, not distinct days —
so `--check` cannot verify it and this constant cites its source instead. Dropping the row
was the alternative, and it is the row #16 most asks for.
"""

SENSITIVITY_CAVEAT = (
    "Not robust to the reconstruction assumption: under a residual that grows with the sea "
    "this aggregate falls from {flat:+.3f} to {proportional:+.3f}, keeping its sign but "
    "losing most of its size. It should not be quoted without this beside it."
)
"""#52's explicit warning, attached to the one row it applies to.

"Do not quote the ≥ 3 m aggregate as robust to the reconstruction assumption" — and it is
the *shipped* fit that is fragile there, not an alternative. Both numbers are read from
`translation_shapes.csv` rather than typed, so the caveat cannot drift from the table it
qualifies.

**Reworded by #58, because the old wording is now false.** It used to end "The per-band rows
below it hold their sign under all three assumptions; this one does not" — true when the
shipped fit read +0.027 flat and -0.004 proportional. Refitting the height Translation moved
those to +0.022 and +0.006, so the row now does hold its sign and the sentence contradicted
the numbers printed immediately before it. What survives is the collapse in magnitude, which
is the part that should stop anyone quoting the figure bare.
"""

SENSITIVITY_BAND = "Combined Sea >= 3 m"
SENSITIVITY_SCATTER = "proportional"
"""The band the warning is about, and the residual assumption that breaks it."""

BAND_LABELS = {
    "held-out: all hours": "all hours",
    "held-out: Combined Sea >= 3 m": "Combined Sea 3 m and above",
    "held-out: Gold Day hours": "Gold Day hours",
    "held-out: measured target under 2 m": "under 2 m",
    "held-out: measured target 2-3 m": "2-3 m",
    "held-out: measured target 3-4 m": "3-4 m",
    "held-out: measured target 4-5 m": "4-5 m",
    "held-out: measured target 5-6 m": "5-6 m",
    "held-out: measured target 6 m and above": "6 m and above",
}
"""Report spellings mapped to what a reader is shown.

The reports prefix every subset with `held-out:` because they sit beside fitting-split rows.
On the page every row is held out, so the prefix is noise — but the mapping is explicit
rather than a string operation, because a subset appearing under a name this dictionary does
not know is a report that changed shape, and silently passing its raw spelling through is how
a page starts quoting a band nobody chose.
"""

SERVED_BAND_LABELS = {
    "all hours": "all hours",
    "Combined Sea >= 3 m": "Combined Sea 3 m and above",
    "measured target under 2 m": "under 2 m",
    "measured target 2-3 m": "2-3 m",
    "measured target 3-4 m": "3-4 m",
    "measured target 4-5 m": "4-5 m",
    "measured target 5-6 m": "5-6 m",
    "measured target 6 m and above": "6 m and above",
}
"""`translation_shapes.csv` names the same bands without the prefix, and carries no Gold Day
row — #52 measured the served path per band of sea state, not per day. The page says so
rather than leaving the reader to notice a row missing from one table."""


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def seasons_in(daily: list[dict[str, str]], *, held_out: bool | None = None) -> list[str]:
    """The Big-Wave Seasons the backtest panel covers, optionally only the held-out ones.

    Counted from the day-by-day record rather than taken from a rate, so the divisor behind
    "flags per season" is derived from the same rows the numerator is.
    """
    found = {row["season"] for row in daily}
    if held_out is True:
        found = {season for season in found if season >= HELD_OUT_FROM}
    elif held_out is False:
        found = {season for season in found if season < HELD_OUT_FROM}
    return sorted(found)


def tier_counts(
    rows_in: list[dict[str, str]], path: Path, column: str, value: str
) -> dict[str, dict[str, int]]:
    """Both tiers' counts from one summary report, selecting the panel or split by one column.

    **No longer a source for the page** (#87). Both published panels are counted from the day
    record by `tier_counts_from_days`; this survives so `--check` can hold the summary reports
    up against them, which is the join whose absence let the two panels disagree for a month.

    The refusal stays as it was: a report missing a tier must stop the build rather than let a
    page quote one tier's figures under both headings.
    """
    by_tier = {row["tier"]: row for row in rows_in if row[column] == value}
    missing = [tier for tier in TIERS if tier not in by_tier]
    if missing:
        raise SystemExit(f"{path} has no {missing} row for {column}={value!r}")
    return {
        tier: {
            "gold_days_called": int(by_tier[tier]["gold_days_called"]),
            "days_flagged": int(by_tier[tier]["days_flagged"]),
        }
        for tier in TIERS
    }


TIER_CALLS = {
    "watch_or_better": ("watch", "go"),
    "go_call": ("go",),
}
"""Each published tier, and the `call` values in the day record that make it up.

`daily_calls.csv` records the **strongest** call a day received, so its `watch` rows are
Watch-and-not-Go. Reading them as the Watch tier would publish a tier that excludes its own
best days. The same mapping is stated in `analysis/backtest/delivery.py`, which counts the
delivered sea over exactly these days — and `--check` pins the two together by requiring the
delivery's total to equal the count derived here.
"""


def tier_counts_from_days(
    daily: list[dict[str, str]], *, held_out: bool | None = None
) -> dict[str, dict[str, int]]:
    """Both tiers' counts, derived from the day-by-day record (#87).

    **One scoring run behind both published panels.** Before this, the held-out block came
    from `calibrated_scores.csv` and the whole-record block from `summary.csv`, and the two
    are not scored with the same bars: `calibrate.py` drives the Heuristic Baseline with the
    candidate thresholds from its own sweep, fitted in reanalysis units, while `backtest.py`
    scores with whatever `load_thresholds()` ships — the same fit translated into Open-Meteo
    units. A lower period bar admits more days, so the held-out Watch tier read 193 in one
    report and 199 in the other, and the page rendered both panels to one reader whose whole
    reason for having two is to compare them.

    Neither number was wrong. They answer different questions, correctly, and the page was
    asking only one: **what would the running system have called.** That is what every other
    figure here describes and what a reader is being asked to trust, so it is the day record —
    scored with the shipped bars — that both panels now come from.

    Only one published figure moved: held-out Watch days, 193 to 199. Every Gold Day count,
    both spans and the whole-record block were already identical, which is why this was
    invisible without a join and why `--check` grew one.
    """
    inside = (
        daily
        if held_out is None
        else [row for row in daily if (row["season"] >= HELD_OUT_FROM) == held_out]
    )
    counts = {}
    for tier, calls in TIER_CALLS.items():
        flagged = [row for row in inside if row["call"] in calls]
        counts[tier] = {
            "gold_days_called": len({row["date"] for row in flagged if row["gold_day"] == "yes"}),
            "days_flagged": len(flagged),
        }
    return counts


def delivered_for(
    delivery: list[dict[str, str]], split: str, tier: str, days_flagged: int
) -> dict[str, Any] | None:
    """What one tier's flagged days delivered, joined hard against the tier's own count.

    `None` for a tier outside `DELIVERED_TIERS`, which is the Watch tier and why.

    **The join is the whole point of this function.** The delivered figure and the Gold Day
    figure are rendered as two statements about one set of days, so if they were counted over
    different sets the page would contradict itself in adjacent sentences and read as more
    confident for it. `days_flagged` here comes from the same block the page's waste statement
    divides by, so a disagreement stops the build rather than reaching a reader.
    """
    if tier not in DELIVERED_TIERS:
        return None

    found = [row for row in delivery if row["split"] == split and row["tier"] == tier]
    if len(found) != 1:
        raise SystemExit(
            f"{DELIVERY} carries {len(found)} rows for split={split!r} tier={tier!r}, not 1"
        )
    row = found[0]

    counted = int(row["days_flagged"])
    if counted != days_flagged:
        raise SystemExit(
            f"{DELIVERY} counts {counted} {tier} days in the {split} split where the published "
            f"call record counts {days_flagged}. The page renders both as statements about one "
            "set of days, so publishing them would contradict itself in adjacent sentences. "
            "See #87."
        )

    expected = {f"days_above_{bar:g}m" for bar in DELIVERY_LADDER}
    carried = {column for column in row if column.startswith("days_above_")}
    if carried != expected:
        raise SystemExit(
            f"{DELIVERY} carries thresholds {sorted(carried)} where this script publishes "
            f"{sorted(expected)}; a threshold nobody chose must not reach the page"
        )

    ladder = [{"metres": bar, "days": int(row[f"days_above_{bar:g}m"])} for bar in DELIVERY_LADDER]
    return {
        "minimum_m": float(row["minimum_m"]),
        "median_m": float(row["median_m"]),
        "maximum_m": float(row["maximum_m"]),
        "above": ladder,
    }


def with_delivery(
    counts: dict[str, dict[str, int]], delivery: list[dict[str, str]], split: str
) -> dict[str, Any]:
    """A panel's tier counts, each carrying its delivered sea where one is published."""
    return {
        tier: {
            **numbers,
            "delivered": delivered_for(delivery, split, tier, numbers["days_flagged"]),
        }
        for tier, numbers in counts.items()
    }


def scored_bands(scores: list[dict[str, str]]) -> list[dict[str, Any]]:
    """The two models' error on identical held-out hours, each reading the Hindcast."""
    published = []
    for row in scores:
        if row["subset"] not in BAND_LABELS:
            raise SystemExit(
                f"{SCORED} carries subset {row['subset']!r}, which this script has no name "
                "for; a band nobody chose must not reach the page under its report spelling"
            )
        name = BAND_LABELS[row["subset"]]
        published.append(
            {
                "name": name,
                "hours": int(row["rows"]),
                "baseline_mae_m": round(float(row["baseline_mae"]), 4),
                "learned_mae_m": round(float(row["learned_mae"]), 4),
                # The one row `analysis/amplification_model/README.md` says must never be
                # quoted bare. It is also the row #16 asks for most directly, so it is
                # published with the qualification rather than dropped.
                "caveat": GOLD_DAY_CAVEAT if name == "Gold Day hours" else None,
            }
        )
    return published


def served_bands(shapes: list[dict[str, str]]) -> list[dict[str, Any]]:
    """The same comparison along the path a Pipeline Run takes, under #52's fair generator."""
    selected = [
        row
        for row in shapes
        if row["generator"] == SERVED_GENERATOR
        and row["candidate"] == SERVED_CANDIDATE
        and row["scatter"] == SERVED_SCATTER
    ]
    if not selected:
        raise SystemExit(
            f"{SHAPES} has no rows for the shipped transform under the {SERVED_GENERATOR!r} "
            "generator; the served figures cannot be published from the shipped generator, "
            "whose reconstruction is what #52 found was measuring itself"
        )

    # #52 scored every candidate under three residual assumptions and found exactly one
    # published row whose *sign* does not survive all three. Looked up rather than typed, so
    # the warning cannot drift from the figure it qualifies.
    alternative = {
        row["band"]: float(row["served_gain_m"])
        for row in shapes
        if row["generator"] == SERVED_GENERATOR
        and row["candidate"] == SERVED_CANDIDATE
        and row["scatter"] == SENSITIVITY_SCATTER
    }

    published = []
    for row in selected:
        if row["band"] not in SERVED_BAND_LABELS:
            raise SystemExit(f"{SHAPES} carries band {row['band']!r}, which has no page name")
        caveat = None
        if row["band"] == SENSITIVITY_BAND:
            if SENSITIVITY_BAND not in alternative:
                raise SystemExit(
                    f"{SHAPES} has no {SENSITIVITY_SCATTER!r} row for {SENSITIVITY_BAND!r}, so "
                    "#52's warning that this aggregate is not robust cannot be published "
                    "beside it — and the figure must not be published without it"
                )
            caveat = SENSITIVITY_CAVEAT.format(
                flat=float(row["served_gain_m"]),
                proportional=alternative[SENSITIVITY_BAND],
            )
        published.append(
            {
                "name": SERVED_BAND_LABELS[row["band"]],
                "hours": int(row["rows"]),
                "baseline_mae_m": round(float(row["served_baseline_mae"]), 4),
                "learned_mae_m": round(float(row["served_learned_mae"]), 4),
                "caveat": caveat,
            }
        )
    # Report order, so the page's two tables read down the same bands in the same sequence.
    order = list(SERVED_BAND_LABELS.values())
    return sorted(published, key=lambda band: order.index(band["name"]))


def range_calibration(coverage: list[dict[str, str]]) -> dict[str, Any]:
    """What the printed range claims to hold, and what it actually held (#80, #94).

    The one figure on this page measured against outcomes rather than against Gold Days. The
    interface states a range in metres, `interval_coverage.csv` scored it, and until #94 the
    page said nothing about the result — which left the single published claim with a
    measurement behind it as the only one carrying no qualification.

    **Nothing here says which way the miss runs.** The columns are the claim and the
    measurement, side by side; whatever renders them derives the direction. That is not
    fastidiousness: #82 exists to narrow this distribution, and a sentence typed here saying
    "wider than the outcomes justify" would survive the refit that makes it false. The two
    caveats are directional and typed, because they are prose about *this* run and are
    rewritten with it.
    """
    claimed = {row["nominal"] for row in coverage}
    if len(claimed) != 1:
        raise SystemExit(
            f"{COVERAGE} scores against more than one nominal share ({sorted(claimed)}); the "
            "page states one claim the whole table is measured against"
        )

    by_lead: dict[int, dict[str, Any]] = {}
    for row in coverage:
        if row["subset"] not in RANGE_SUBSETS:
            raise SystemExit(
                f"{COVERAGE} carries subset {row['subset']!r}, which this script has no name "
                "for; a subset nobody chose must not reach the page under its report spelling"
            )
        lead = int(row["lead_days"])
        subset = RANGE_SUBSETS[row["subset"]]
        if subset in by_lead.setdefault(lead, {}):
            raise SystemExit(f"{COVERAGE} carries {row['subset']!r} twice at {lead} days")
        by_lead[lead][subset] = {
            "hours": int(row["hours"]),
            "covered": round(float(row["covered"]), 4),
            "median_width_m": round(float(row["median_width_m"]), 4),
            "widening_factor": round(float(row["widening_factor"]), 4),
        }

    leads = []
    for lead in sorted(by_lead):
        missing = [name for name in RANGE_SUBSETS.values() if name not in by_lead[lead]]
        if missing:
            raise SystemExit(
                f"{COVERAGE} has no {missing} row at {lead} days. Both subsets are published "
                "together or neither is: the big-swell rows cover the bigger seas and are the "
                "kinder of the two"
            )
        leads.append({"lead_days": lead, **by_lead[lead]})

    return {
        "claimed": float(next(iter(claimed))),
        "big_swell_from_m": BIG_SWELL_M,
        "understates_because": RANGE_UNDERSTATES_BECAUSE,
        "rests_on": RANGE_RESTS_ON,
        "leads": leads,
    }


def recorded_days(daily: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Every Gold Day, and every day the system issued a Go Call for.

    The two together are what a reader needs to judge the system in both directions: the days
    that mattered and whether it saw them, and the days it told someone to travel for whether
    they mattered or not. Days it stayed quiet about and that turned out to be ordinary are
    the overwhelming majority and carry no information — they are counted in the panels rather
    than listed.
    """
    published = []
    for row in daily:
        gold = row["gold_day"] == "yes"
        if not gold and row["call"] != "go":
            continue
        published.append(
            {
                "date": row["date"],
                "season": row["season"],
                "call": row["call"],
                "peak_significant_wave_height_m": round(
                    float(row["peak_significant_wave_height_m"]), 2
                ),
                "gold_day": gold,
                "gold_tier": row["gold_tier"] or None,
            }
        )
    return sorted(published, key=lambda day: day["date"])


def assemble() -> dict[str, Any]:
    """The whole record, in memory.

    Separated from writing it so `--check` can rebuild the record and compare it against the
    committed file. Without that, a report regenerated after this file was last written
    leaves a stale `track_record.json` in the repository that every check passes — and the
    stale copy is what the backend serves.
    """
    daily = [row for row in rows(DAILY) if row["panel"] == PANEL]
    if not daily:
        raise SystemExit(f"{DAILY} carries no {PANEL!r} panel")

    calibrated = rows(CALIBRATED)
    summary = rows(SUMMARY)
    delivery = rows(DELIVERY)
    thresholds = json.loads(THRESHOLDS.read_text(encoding="utf-8"))
    calibration = thresholds.get("calibration")
    if calibration is None:
        raise SystemExit(
            f"{THRESHOLDS} carries no calibration, so the track record cannot state what the "
            "thresholds behind these calls rest on"
        )

    whole = next(row for row in summary if row["panel"] == PANEL)

    return {
        "published_at": datetime.now(UTC).date().isoformat(),
        "source": "analysis/track_record/publish.py",
        "call_record": {
            "held_out": {
                "span": calibration["validated_on"],
                "basis": "Hindcast",
                "gold_days": int(
                    next(row for row in calibrated if row["split"] == "held-out")[
                        "gold_days_in_split"
                    ]
                ),
                "big_wave_seasons": float(len(seasons_in(daily, held_out=True))),
                "tiers": with_delivery(
                    tier_counts_from_days(daily, held_out=True), delivery, "held_out"
                ),
            },
            "full_record": {
                "span": whole["span"],
                "basis": "Hindcast",
                "gold_days": int(whole["gold_days_in_span"]),
                "big_wave_seasons": float(len(seasons_in(daily))),
                "tiers": with_delivery(tier_counts_from_days(daily), delivery, "full_record"),
            },
        },
        "height_record": {
            "scored": {"bands": scored_bands(rows(SCORED))},
            "served": {"bands": served_bands(rows(SHAPES))},
            "range_calibration": range_calibration(rows(COVERAGE)),
        },
        "gold_days": {
            "fitted": int(calibration["gold_days_fitted"]),
            "validated": int(calibration["gold_days_validated"]),
        },
        "days": recorded_days(daily),
    }


def build() -> int:
    record = assemble()
    DESTINATION.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {DESTINATION.relative_to(ROOT)}")
    print(
        f"  {len(record['days'])} days, "
        f"{record['call_record']['full_record']['big_wave_seasons']:.0f} Big-Wave Seasons "
        f"({record['call_record']['held_out']['big_wave_seasons']:.0f} held out)"
    )
    return 0


def check() -> int:
    """Self-test every join, offline. No credentials, no download.

    Each assertion below is a way this script could publish a number that is individually
    correct and wrong where it lands.
    """
    failures: list[str] = []

    def expect(condition: bool, message: str) -> None:
        if not condition:
            failures.append(message)

    daily = [row for row in rows(DAILY) if row["panel"] == PANEL]
    calibrated = rows(CALIBRATED)
    summary = rows(SUMMARY)
    thresholds = json.loads(THRESHOLDS.read_text(encoding="utf-8"))
    calibration = thresholds["calibration"]

    # 1. The season counts. `calibrate.py` published a per-season rate from its own split;
    #    this script counts the seasons from the day-by-day record instead. The two agreeing
    #    is what makes "flags per Big-Wave Season" on the page the same quantity #12 reported,
    #    rather than the same words over a different divisor.
    held_out_seasons = len(seasons_in(daily, held_out=True))
    for row in calibrated:
        if row["split"] != "held-out":
            continue
        derived = int(row["days_flagged"]) / held_out_seasons
        expect(
            abs(derived - float(row["flags_per_season"])) < 0.05,
            f"held-out {row['tier']}: {derived:.1f} flags per season over "
            f"{held_out_seasons} seasons against {row['flags_per_season']} published — the "
            "season split here is not the one calibrate.py fitted on",
        )

    # 2. The held-out Gold Day count has to be the same days the calibration was validated
    #    on. The backend refuses a file where these disagree; catching it here names which
    #    report moved.
    held_out_gold = next(row for row in calibrated if row["split"] == "held-out")
    expect(
        int(held_out_gold["gold_days_in_split"]) == int(calibration["gold_days_validated"]),
        f"calibrated_scores.csv holds {held_out_gold['gold_days_in_split']} held-out Gold "
        f"Days against thresholds.json's {calibration['gold_days_validated']}",
    )
    whole = next(row for row in summary if row["panel"] == PANEL)
    expect(
        int(whole["gold_days_in_span"])
        == int(calibration["gold_days_fitted"]) + int(calibration["gold_days_validated"]),
        f"the backtest spans {whole['gold_days_in_span']} Gold Days against the "
        "calibration's fitted plus validated",
    )

    # 3. The served rows must come from the fair generator. Reading them from the shipped
    #    generator is not an error that shows up as a missing file — it publishes eight
    #    plausible numbers.
    #
    #    **This pin is weaker since #58 and deliberately kept.** It used to separate -0.0774
    #    from the shipped generator's +0.035, a margin of 0.11 m. #58 refitted the height
    #    Translation so the shipped generator no longer flatters anything, and the two now sit
    #    0.002 m apart — still four times the tolerance below, but no longer a gap anyone would
    #    notice by eye. It catches the same wiring mistake; it no longer proves the mistake
    #    would have mattered.
    served = served_bands(rows(SHAPES))
    by_name = {band["name"]: band for band in served}
    for name, expected_gain in (("all hours", -0.0162), ("under 2 m", -0.0350)):
        band = by_name.get(name)
        if band is None:
            failures.append(f"served table has no {name!r} band")
            continue
        gain = band["baseline_mae_m"] - band["learned_mae_m"]
        expect(
            abs(gain - expected_gain) < 5e-4,
            f"served {name}: gain {gain:+.4f} against #52's {expected_gain:+.4f} — these rows "
            "are the shipped generator's, whose reconstruction measures its own transform",
        )

    # 4. Both tiers survive the join from every source. A tier silently dropped leaves a page
    #    reporting one tier's figures under both headings, which is the shape of #12's
    #    collapse rather than a visible gap.
    for label, counts in (
        ("held-out", tier_counts(calibrated, CALIBRATED, "split", "held-out")),
        ("whole record", tier_counts(summary, SUMMARY, "panel", PANEL)),
    ):
        expect(
            set(counts) == set(TIERS),
            f"{label} lost a tier in the join: {sorted(counts)}",
        )
        expect(
            counts["watch_or_better"]["days_flagged"] >= counts["go_call"]["days_flagged"],
            f"{label}: the Watch tier flagged fewer days than the Go Call tier, which is the "
            "table with its columns swapped",
        )

    # 4a. The join whose absence let the two panels disagree for a month (#87). Both are now
    #     counted from the day record, so the summary reports become independent references
    #     rather than sources — and each has to be held up against what it claims to describe.
    published = assemble()["call_record"]

    #     `summary.csv` scores the same panel with the same shipped bars, so it must agree
    #     exactly. A divergence means the day record and the headline table came from
    #     different runs of the backtest, and the page would be quoting the older one.
    for tier, counts in tier_counts(summary, SUMMARY, "panel", PANEL).items():
        for field, value in counts.items():
            expect(
                published["full_record"]["tiers"][tier][field] == value,
                f"whole record {tier} {field}: the day record gives "
                f"{published['full_record']['tiers'][tier][field]} and {SUMMARY.name} gives "
                f"{value}; the two must be one scoring run",
            )

    #     `calibrated_scores.csv` scores with the bars the fit chose in reanalysis units, not
    #     the translated ones the system ships, so its *cost* may legitimately differ — and
    #     only in one direction, since a translated-down period bar cannot admit fewer days.
    #     Its **recall** may not differ at all: if a Gold Day count moves, the two are no
    #     longer describing one calibration and the held-out panel's caption stops being true.
    for tier, counts in tier_counts(calibrated, CALIBRATED, "split", "held-out").items():
        shipped = published["held_out"]["tiers"][tier]
        expect(
            shipped["gold_days_called"] == counts["gold_days_called"],
            f"held-out {tier}: the shipped bars catch {shipped['gold_days_called']} Gold Days "
            f"where the fit's own bars catch {counts['gold_days_called']}. The two are meant "
            "to be one calibration in two unit systems, so a recall moving means they are not",
        )
        expect(
            shipped["days_flagged"] >= counts["days_flagged"],
            f"held-out {tier}: the shipped bars flag {shipped['days_flagged']} days where the "
            f"fit's bars flag {counts['days_flagged']}. The shipped period bar is the lower of "
            "the two, so it cannot admit fewer days — see #87",
        )

    # 4b. The delivered sea is counted over the same days the waste figure divides by (#83).
    #     `delivered_for` already raises on a mismatched total, so this covers what a total
    #     agreeing cannot: a ladder counting more big days than there were calls, or one that
    #     rises as the bar rises. Both would make the page claim more than the record holds,
    #     and both are arithmetic a reader cannot check.
    for label, panel in published.items():
        for tier, numbers in panel["tiers"].items():
            delivered = numbers["delivered"]
            expect(
                (delivered is not None) == (tier in DELIVERED_TIERS),
                f"{label} {tier}: delivered is published for exactly {DELIVERED_TIERS}",
            )
            if delivered is None:
                continue
            flagged = numbers["days_flagged"]
            for step in delivered["above"]:
                expect(
                    step["days"] <= flagged,
                    f"{label} {tier}: {step['days']} days over {step['metres']:g} m out of "
                    f"{flagged} flagged",
                )
            expect(
                all(
                    low["days"] >= high["days"]
                    for low, high in zip(delivered["above"], delivered["above"][1:], strict=False)
                ),
                f"{label} {tier}: a higher threshold admits more days than a lower one",
            )
            expect(
                delivered["minimum_m"] <= delivered["median_m"] <= delivered["maximum_m"],
                f"{label} {tier}: minimum, median and maximum are not in order",
            )

    # 5. Every day published is one of the two kinds it claims to be, and no day appears
    #    twice. A Gold Day the system issued a Go Call for is in both sets, and a union built
    #    by concatenation would list it once per set — doubling the most important rows.
    published = recorded_days(daily)
    dates = [day["date"] for day in published]
    expect(len(dates) == len(set(dates)), "the day-by-day record repeats a date")
    expect(
        all(day["gold_day"] or day["call"] == "go" for day in published),
        "the day-by-day record carries a day that is neither a Gold Day nor a Go Call",
    )
    gold_in_daily = sum(1 for row in daily if row["gold_day"] == "yes")
    expect(
        sum(1 for day in published if day["gold_day"]) == gold_in_daily,
        f"the day-by-day record lost Gold Days: {sum(1 for d in published if d['gold_day'])} "
        f"of {gold_in_daily}",
    )
    go_in_daily = sum(1 for row in daily if row["call"] == "go")
    expect(
        sum(1 for day in published if day["call"] == "go") == go_in_daily,
        "the day-by-day record lost Go Calls",
    )

    # 6. The whole-record counts have to be the day-by-day record's own. These come from
    #    different files, and #11 writing one without the other is exactly how a summary
    #    starts describing a backtest that has since been re-run.
    counted = {
        "watch_or_better": sum(1 for row in daily if row["call"] in ("watch", "go")),
        "go_call": sum(1 for row in daily if row["call"] == "go"),
    }
    for tier, flagged in tier_counts(summary, SUMMARY, "panel", PANEL).items():
        expect(
            counted[tier] == flagged["days_flagged"],
            f"whole record {tier}: summary.csv says {flagged['days_flagged']} days flagged, "
            f"daily_calls.csv holds {counted[tier]}",
        )

    # 7. #52's warning is attached to the row it is about. The aggregate reverses sign under
    #    a residual grown with the sea, and it is the *shipped* fit that does — every
    #    alternative stays positive there. Publishing it bare is the one way this page could
    #    quote a figure #52 explicitly said not to quote.
    fragile = by_name.get(SERVED_BAND_LABELS[SENSITIVITY_BAND])
    expect(
        fragile is not None and bool(fragile["caveat"]),
        f"the served {SENSITIVITY_BAND!r} row carries no caveat; #52 measured it falling from "
        "+0.027 to -0.004 under a size-weighted residual and said not to quote it as robust",
    )
    expect(
        all(band["caveat"] is None for band in served if band is not fragile),
        "a served row other than the fragile aggregate carries a caveat, which would spread a "
        "warning onto rows that hold their sign under every assumption",
    )

    # 7a. The range calibration (#94). Two kinds of check, and the difference matters.
    #
    #     The first are joins: a subset dropped, a Lead Time missing, a width that shrinks as
    #     the forecast reaches further. Each would publish an ordinary-looking table describing
    #     a distribution that does not exist.
    calibration_rows = range_calibration(rows(COVERAGE))
    leads = calibration_rows["leads"]
    claim = calibration_rows["claimed"]

    expect(
        [lead["lead_days"] for lead in leads] == list(range(1, len(leads) + 1)),
        f"the range table skips a Lead Time: {[lead['lead_days'] for lead in leads]}. The page "
        "reads down it as a progression, and a gap reads as a forecast that reaches less far",
    )

    #     The subset's bar is copied from the module that scores it, so the two must agree. A
    #     page stating a threshold the report did not use describes a subset that was never
    #     measured — and this one is the bar a reader will take for the Go Call's, which it is
    #     not (`thresholds.json` sets that at 2.75 m [now:minimum_significant_wave_height_m]).
    defined = re.search(
        r"^BIG_SWELL_M\s*=\s*([0-9.]+)", BIG_SWELL_SOURCE.read_text(encoding="utf-8"), re.MULTILINE
    )
    expect(
        defined is not None and float(defined.group(1)) == BIG_SWELL_M,
        f"{BIG_SWELL_SOURCE.relative_to(ROOT)} defines BIG_SWELL_M as "
        f"{defined.group(1) if defined else 'nothing this can read'} where this script "
        f"publishes {BIG_SWELL_M}; the page would state a bar the subset was not scored at",
    )
    for lead in leads:
        expect(
            lead["big_swell"]["hours"] <= lead["all_hours"]["hours"],
            f"{lead['lead_days']} d: the big-swell subset holds {lead['big_swell']['hours']} "
            f"hours against {lead['all_hours']['hours']} for all hours, so it is not a subset",
        )
    for subset in RANGE_SUBSETS.values():
        widths = [lead[subset]["median_width_m"] for lead in leads]
        expect(
            all(later > earlier for earlier, later in zip(widths, widths[1:], strict=False)),
            f"{subset}: the range does not widen with Lead Time ({widths}). Uncertainty that "
            "falls as the forecast reaches further is a column read in the wrong order",
        )

    #     The second are directional, and they are pinned on purpose even though #82 exists to
    #     change them. Today every row says the same thing: the range holds the outcome more
    #     often than it claims to, at every Lead Time, and increasingly so. The page derives
    #     that direction from the numbers rather than asserting it — but the two caveats
    #     published beside them are written for a range that runs wide, and a refit that
    #     reverses the finding must not slip past with the old prose still attached.
    for lead in leads:
        for subset in RANGE_SUBSETS.values():
            measured = lead[subset]
            expect(
                measured["covered"] >= claim,
                f"{lead['lead_days']} d {subset}: the range held {measured['covered']:.1%} of "
                f"outcomes against the {claim:.0%} it claims. If this is a genuine refit "
                "(#82), RANGE_UNDERSTATES_BECAUSE and RANGE_RESTS_ON are written for a range "
                "that runs wide and no longer describe it",
            )
            expect(
                measured["widening_factor"] < 1.0,
                f"{lead['lead_days']} d {subset}: widening factor "
                f"{measured['widening_factor']}, so the range is at or under the width the "
                "outcomes justify — see the note above",
            )
    for subset in RANGE_SUBSETS.values():
        expect(
            leads[-1][subset]["widening_factor"] < leads[0][subset]["widening_factor"],
            f"{subset}: the excess width no longer grows with Lead Time "
            f"({leads[0][subset]['widening_factor']} at 1 d against "
            f"{leads[-1][subset]['widening_factor']} at {leads[-1]['lead_days']} d). That "
            "growth is #80's sharper finding and the reason a single scale factor is not the "
            "repair",
        )

    # 8. The committed file is the one this script would write now. Everything above checks
    #    the joins; none of it looks at DESTINATION, so a report regenerated after the last
    #    publish leaves a stale record that every other check passes — and the stale record is
    #    what the backend serves. `published_at` is excluded because it moves by design.
    fresh = assemble()
    try:
        committed = json.loads(DESTINATION.read_text(encoding="utf-8"))
    except OSError as error:
        committed = None
        failures.append(f"cannot read the committed record at {DESTINATION}: {error}")
    if committed is not None:
        volatile = "published_at"
        expect(
            {key: value for key, value in fresh.items() if key != volatile}
            == {key: value for key, value in committed.items() if key != volatile},
            f"{DESTINATION.relative_to(ROOT)} is not what this script would write now — a "
            "report has moved since it was last published. Re-run without --check",
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

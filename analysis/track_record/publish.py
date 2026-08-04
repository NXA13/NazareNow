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
| held-out call record | `analysis/calibration/output/calibrated_scores.csv` | #12 |
| whole-record call record | `analysis/backtest/output/summary.csv` | #11 |
| day-by-day record | `analysis/backtest/output/daily_calls.csv` | #11 |
| scored height accuracy | `analysis/amplification_model/output/held_out_scores.csv` | #13 |
| served height accuracy | `analysis/amplification_model/output/translation_shapes.csv` | #52 |
| Gold Day split | `backend/src/nazarenow/thresholds.json` | #12 |

**The served figures are #52's, not `served_path.py`'s.** `output/served_path_scores.csv`
reconstructs the operational series using the shipped Translation, which extrapolates about
0.34 m below the range it was fitted on and hands that error to the baseline as a free upward
shift. Its `all hours` and `under 2 m` rows therefore read +0.035 and +0.074 — in the learned
model's favour — where a generator tracking the measured pairing reads **-0.077** and
**-0.126**. Publishing the first pair would put the most flattering number on the page and
have it be an artefact of the transform under test. The rows taken here are
`translation_shapes.csv` filtered to the shipped candidate under the `regime-aware` generator
with a flat residual, which is what `analysis/amplification_model/README.md` prints as the
*fair generator* column.

**Rates are not written.** The file carries counts and the backend divides, so a recall on
the page cannot disagree with the counts beside it. See `backend/src/nazarenow/track_record.py`.

`--check` runs offline against the committed reports and needs no credentials and no
download. It pins the three joins that would silently publish a wrong number: the season
counts against the rates `calibrate.py` published independently, the served rows against the
generator they must come from, and the Gold Day split against the shipped threshold file.

Run:
    .venv/Scripts/python.exe analysis/track_record/publish.py

    # Self-tests every join, offline.
    .venv/Scripts/python.exe analysis/track_record/publish.py --check
"""

from __future__ import annotations

import csv
import json
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
    "this aggregate falls from {flat:+.3f} to {proportional:+.3f}. The per-band rows below "
    "it hold their sign under all three assumptions; this one does not."
)
"""#52's explicit warning, attached to the one row it applies to.

"Do not quote the ≥ 3 m aggregate as robust to the reconstruction assumption" — and it is
the *shipped* fit that fails there, not an alternative. Both numbers are read from
`translation_shapes.csv` rather than typed, so the caveat cannot drift from the table it
qualifies.
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
    """Both tiers' counts from one report, selecting the panel or split by one column.

    The held-out figures come from `calibrated_scores.csv` keyed on `split` and the
    whole-record ones from `summary.csv` keyed on `panel`, but the join is the same shape
    and the refusal has to be: a report missing a tier must stop the build rather than
    publish a page that quotes one tier's figures under both headings.
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
                "tiers": tier_counts(calibrated, CALIBRATED, "split", "held-out"),
            },
            "full_record": {
                "span": whole["span"],
                "basis": "Hindcast",
                "gold_days": int(whole["gold_days_in_span"]),
                "big_wave_seasons": float(len(seasons_in(daily))),
                "tiers": tier_counts(summary, SUMMARY, "panel", PANEL),
            },
        },
        "height_record": {
            "scored": {"bands": scored_bands(rows(SCORED))},
            "served": {"bands": served_bands(rows(SHAPES))},
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
    #    plausible numbers, two of which flatter the learned model by more than the whole
    #    effect being reported.
    served = served_bands(rows(SHAPES))
    by_name = {band["name"]: band for band in served}
    for name, expected_gain in (("all hours", -0.0774), ("under 2 m", -0.1258)):
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

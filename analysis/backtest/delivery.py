"""What the sea actually did on the days each tier flagged.

Ticket #83. The track record scores a Go Call against the Gold Days — days ratified giant by a
contest or a world record — and publishes the result the unkind way round, as "at most N of M
trips would have been wasted". That number is true, it is deliberately conservative because it
asks somebody to spend money, and on its own it badly understates the rule: almost nothing
clears the Gold Day bar, so almost everything reads as waste.

This measures the other half of the same question. Not "was it a day the world recorded" but
**"did the ocean show up"** — which is answerable, in a measured quantity, on every flagged day
rather than on thirty-eight of them.

**It computes nothing new.** `backtest.py` already wrote what each called day peaked at, into
`output/daily_calls.csv`, and nothing has ever read that column. This groups it. Re-running the
backtest to produce the same figure a second time would be a second answer to one question, which
is the rule `analysis/track_record/publish.py` states about itself and the reason this is a
separate module rather than an extra table inside `backtest.py`.

**The ladder is round numbers, not the system's bars.** A reader holding "above 4 m" needs no
units lecture; a reader holding "above the calibrated height bar" needs the whole of
`thresholds.json`'s translation note, and would still be reading a reanalysis peak against a bar
shipped in operational units. Three metres is the exception and is not arbitrary — it is
`BIG_SWELL_M`, the regime bar the model, the profile and the backtest all already split on.

**The minimum is the headline, not a ladder row.** "No Go Call in six unseen seasons landed on a
day the sea peaked below 2.82 m" is the strongest true sentence available here, and it is a single
number rather than a percentage that invites a reader to wonder about the other tail.

Run:
    .venv/Scripts/python.exe analysis/backtest/delivery.py
    .venv/Scripts/python.exe analysis/backtest/delivery.py --check
"""

from __future__ import annotations

import csv
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = HERE / "output"

DAILY = OUTPUT / "daily_calls.csv"
DESTINATION = OUTPUT / "delivery.csv"

PANEL = "reanalysis"
"""The one panel that spans the whole record.

`daily_calls.csv` also carries an `operational (diagnostic)` panel and a superseded
`reconstructed` one. Mixing them double-counts days — the same date appears in more than one,
scored against a different product each time — which is the same refusal `publish.py` makes.
"""

HELD_OUT_FROM = "2020/21"
"""The first held-out Big-Wave Season, matching `thresholds.json`'s `validated_on`.

Duplicated from `publish.py` rather than imported, and `--check` pins the two together. A split
that disagreed between the report and the thing publishing it would put a held-out delivery
figure beside a whole-record waste figure under one heading, which is precisely the comparison
this ticket exists to make trustworthy.
"""

LADDER = (3.0, 4.0, 5.0, 6.0)
"""The thresholds counted. Three metres is `BIG_SWELL_M`; the rest are round steps above it."""

TIERS = {
    "watch_or_better": ("watch", "go"),
    "go_call": ("go",),
}
"""The published tiers, and the `call` values each is made of.

`daily_calls.csv` records the *strongest* call a day received, so its `watch` rows are
Watch-and-not-Go. The track record's tier is `watch_or_better`, which is both. Getting this
backwards would publish a Watch tier that excludes its best days — flattering the Go tier by
comparison, in the one table whose whole purpose is that the two disagree.
"""


@dataclass(frozen=True)
class Delivery:
    """What one tier's flagged days delivered, over one split of the record."""

    split: str
    tier: str
    days_flagged: int
    minimum_m: float
    median_m: float
    maximum_m: float
    above: dict[float, int]


def peaks(daily: list[dict[str, str]], split: str, tier: str) -> list[float]:
    """Every flagged day's peak, for one tier over one split.

    A flagged day carrying no peak **raises**. `backtest.py` scores a day from its hours, so a
    called day with no measured sea would mean the call was issued from something this report
    cannot see — and silently dropping it would shrink the denominator that the Gold Day figure
    beside it still divides by, making the two tables quietly count different days.
    """
    calls = TIERS[tier]
    found = []
    for row in daily:
        if row["panel"] != PANEL or row["call"] not in calls:
            continue
        if split == "held_out" and row["season"] < HELD_OUT_FROM:
            continue
        peak = row["peak_significant_wave_height_m"]
        if not peak:
            raise SystemExit(
                f"{DAILY.relative_to(ROOT)}: {row['date']} was called {row['call']!r} and "
                "carries no peak, so the day cannot be counted in either direction"
            )
        found.append(float(peak))
    if not found:
        raise SystemExit(f"{DAILY.relative_to(ROOT)} has no {tier} day in the {split} split")
    return found


def deliver(daily: list[dict[str, str]], split: str, tier: str) -> Delivery:
    found = peaks(daily, split, tier)
    return Delivery(
        split=split,
        tier=tier,
        days_flagged=len(found),
        minimum_m=min(found),
        median_m=statistics.median(found),
        maximum_m=max(found),
        above={bar: sum(1 for peak in found if peak >= bar) for bar in LADDER},
    )


def measure(daily: list[dict[str, str]]) -> list[Delivery]:
    return [deliver(daily, split, tier) for split in ("held_out", "full_record") for tier in TIERS]


def rows_of(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise SystemExit(
            f"{path.relative_to(ROOT)} is missing. It is written by analysis/backtest/backtest.py."
        )
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write(rows: list[Delivery]) -> Path:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with DESTINATION.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["split", "tier", "days_flagged", "minimum_m", "median_m", "maximum_m"]
            + [f"days_above_{bar:g}m" for bar in LADDER]
        )
        for row in rows:
            writer.writerow(
                [
                    row.split,
                    row.tier,
                    row.days_flagged,
                    round(row.minimum_m, 2),
                    round(row.median_m, 2),
                    round(row.maximum_m, 2),
                ]
                + [row.above[bar] for bar in LADDER]
            )
    return DESTINATION


def print_table(rows: list[Delivery]) -> None:
    ladder = "".join(f"{f'>={bar:g}m':>9}" for bar in LADDER)
    print(f"\n{'Split':<13}{'Tier':<18}{'Days':>6}{'Min':>8}{'Median':>8}{'Max':>8}{ladder}")
    for row in rows:
        counts = "".join(f"{row.above[bar]:>9,}" for bar in LADDER)
        print(
            f"{row.split:<13}{row.tier:<18}{row.days_flagged:>6,}"
            f"{row.minimum_m:>7.2f}m{row.median_m:>7.2f}m{row.maximum_m:>7.2f}m{counts}"
        )


def main() -> int:
    rows = measure(rows_of(DAILY))
    print_table(rows)
    print(f"\nWrote {write(rows).relative_to(ROOT)}")
    return 0


def check() -> int:
    """Re-derive the committed table from the day record and pin the joins that would lie.

    Offline and from the repository alone, like `publish.py --check`. This one *can* re-derive,
    because the input is committed — so it checks the values themselves rather than only their
    shape, and additionally pins the two facts a wrong table would rest on.
    """
    failures: list[str] = []

    def expect(label: str, condition: bool, detail: str) -> None:
        if not condition:
            failures.append(f"{label}: {detail}")

    if not DESTINATION.exists():
        print(f"{DESTINATION.relative_to(ROOT)} is missing; run delivery.py first")
        return 1

    daily = rows_of(DAILY)
    fresh = {(row.split, row.tier): row for row in measure(daily)}
    committed = rows_of(DESTINATION)

    expect(
        "row count",
        len(committed) == len(fresh),
        f"the table carries {len(committed)} rows against {len(fresh)} derivable",
    )

    for row in committed:
        key = (row["split"], row["tier"])
        where = f"{row['split']} {row['tier']}"
        if key not in fresh:
            failures.append(f"{where}: the table carries a split/tier pair nothing derives")
            continue
        derived = fresh[key]
        expect(
            f"{where} days flagged",
            int(row["days_flagged"]) == derived.days_flagged,
            f"table says {row['days_flagged']}, the day record says {derived.days_flagged}",
        )
        for bar in LADDER:
            counted = int(row[f"days_above_{bar:g}m"])
            expect(
                f"{where} above {bar:g}m",
                counted == derived.above[bar],
                f"table says {counted}, the day record says {derived.above[bar]}",
            )
            # A ladder count above the tier's own flagged days is the arithmetic that would
            # let the page claim more big days than calls, which is #79's worst survivor in
            # a new place.
            expect(
                f"{where} above {bar:g}m is a subset",
                counted <= int(row["days_flagged"]),
                f"{counted} days over {bar:g}m out of {row['days_flagged']} flagged",
            )
        expect(
            f"{where} ladder falls",
            all(
                int(row[f"days_above_{low:g}m"]) >= int(row[f"days_above_{high:g}m"])
                for low, high in zip(LADDER, LADDER[1:], strict=False)
            ),
            "a higher threshold admits more days than a lower one",
        )
        expect(
            f"{where} minimum bounds the ladder",
            float(row["minimum_m"]) <= float(row["median_m"]) <= float(row["maximum_m"]),
            "minimum, median and maximum are not in order",
        )

    # The split must mean what `publish.py` means by it, or the page pairs a held-out delivery
    # figure with a held-out waste figure counted over different seasons.
    held = {(row["split"], row["tier"]): row for row in committed}
    for tier in TIERS:
        expect(
            f"{tier} held-out is a subset of the whole record",
            int(held[("held_out", tier)]["days_flagged"])
            <= int(held[("full_record", tier)]["days_flagged"]),
            "the held-out split flags more days than the record containing it",
        )
    expect(
        "watch_or_better contains go_call",
        all(
            int(held[(split, "watch_or_better")]["days_flagged"])
            >= int(held[(split, "go_call")]["days_flagged"])
            for split in ("held_out", "full_record")
        ),
        "the Watch tier flags fewer days than the Go tier inside it",
    )

    for failure in failures:
        print(f"FAIL {failure}")
    print(f"delivery.py --check: {len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(check() if "--check" in sys.argv else main())

"""Build the training dataset the Amplification Model will learn from.

Ticket #9. ADR 0004 settles the shape: the Amplification Model learns the physical
relationship from clean inputs — Hindcast Offshore Conditions paired with the Proxy Target —
and forecast unreliability is characterised separately in #14 rather than baked into the
training data. This script builds that pairing, once, reproducibly, from the raw archives the
earlier tickets already download.

**Nothing here fetches anything.** #2's `download_observations.py` retrieves the buoys, #39's
`reanalysis.py` retrieves the Copernicus IBI Hindcast, and #11's `hindcast.py` retrieves ERA5
wind. Each caches into `data/raw/`, each is gitignored, and each is re-runnable. This script
reads those caches and joins them. Keeping retrieval out means the build is deterministic by
construction: it cannot pick up a different ocean between two runs.

**The join key is the UTC hour, not the local stamp.** `reanalysis.py` explains why at length
and the same trap applies here — when Lisbon leaves summer time, 00:00 and 01:00 UTC both
render as 01:00 local, so a dict keyed on the local string silently keeps one of them. That is
one hour a year, every year, in late October, which is inside the Big-Wave Season. UTC is
unique by construction; the Nazaré local stamp, local day, and the season that day falls in
(ADR 0008) are carried as fields, all derived from the local moment rather than the UTC one.

**Gaps are excluded and counted, never filled.** #2 found five effectively dead Big-Wave
Seasons and outages running to 488 days. Interpolating across those would manufacture a
training signal out of nothing and the model would learn it. So an hour enters the dataset
only when the Proxy Target and the whole Hindcast are genuinely present at that hour; every
other hour is dropped, and `output/coverage_by_season.csv` reports where the drops fell.

Run:
    .venv/Scripts/python.exe analysis/training_dataset/build.py
    .venv/Scripts/python.exe analysis/training_dataset/build.py --check
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "analysis" / "backtest"))
sys.path.insert(0, str(ROOT / "analysis" / "buoy_coverage"))

import analyse_coverage  # noqa: E402
import hindcast  # noqa: E402
import reanalysis  # noqa: E402

from platforms import MONICAN01, MONICAN02  # noqa: E402

OUTPUT = Path(__file__).parent / "output"

DATASET = OUTPUT / "training_dataset.csv"
COVERAGE = OUTPUT / "coverage_by_season.csv"

# The Hindcast variables, in IBI's names, and what this project calls them. The mapping is
# #39's, measured in `analysis/overlap/`: the **height** that corresponds to what the live
# system reads as `swell_wave_height` is the combined partition field, not SW1 alone, so
# `swell_height_m` is the root sum of squares of the two trains. The **period** has no such
# combination — a period threshold is inherently about one train — so the primary train's is
# carried and the secondary's is carried beside it rather than merged into it.
HINDCAST_COLUMNS = (
    "swell_height_m",
    "swell_period_s",
    "swell_direction_deg",
    "secondary_swell_height_m",
    "secondary_swell_period_s",
    "secondary_swell_direction_deg",
    "hindcast_combined_sea_height_m",
)

WIND_COLUMNS = ("wind_speed_kmh", "wind_direction_deg")

# Monican01 is an **Offshore Observation**, never a target (CONTEXT.md). It is a measured
# rather than modelled reading of the swell arriving at the coast, 55 km out, and it is
# carried as an input the learned model may or may not find useful. It is optional: its
# outages are largely uncorrelated with Monican02's, so requiring it would throw away hours
# where the target and the Hindcast are both perfectly good.
OFFSHORE_COLUMNS = (
    "offshore_observed_height_m",
    "offshore_observed_period_s",
    "offshore_observed_direction_deg",
)

TARGET_COLUMN = "proxy_target_height_m"

# #145. An hour the instrument got wrong is not the same thing as an hour it did not report,
# and the file has to be able to say which. The target goes empty so that every consumer's
# existing presence test drops it, `proxy_target_suspect` records that the emptiness was a
# decision, and the reading itself is carried rather than deleted — the judgement stays
# reviewable, and reversible, by whoever reads the file next.
SUSPECT_COLUMN = "proxy_target_suspect"
RAW_TARGET_COLUMN = "proxy_target_raw_m"

COLUMNS = (
    "at_utc",
    "at_local",
    "day",
    "season",
    *HINDCAST_COLUMNS,
    *WIND_COLUMNS,
    "wind_present",
    *OFFSHORE_COLUMNS,
    "offshore_observation_present",
    TARGET_COLUMN,
    SUSPECT_COLUMN,
    RAW_TARGET_COLUMN,
)

# Written to this many decimals, always, so the file is byte-identical between runs on
# machines whose float repr differs in the last place. Three is past the precision any of
# these instruments claims — the buoy reports Hs in centimetres — so nothing real is lost.
DECIMALS = 3


# What "large-swell conditions" means, reported as a distribution rather than a count above
# one bar. The obvious bar to reach for is the Heuristic Baseline's
# `minimum_significant_wave_height_m`, and it is the wrong one: that threshold is applied to
# *offshore swell height* in a forecast, and the Proxy Target is the *Combined Sea* measured
# at a mooring. CONTEXT.md holds those apart deliberately and CLAUDE.md calls the conflation
# load-bearing. Bands avoid inventing a threshold at all, and let a reader put the line
# wherever their question needs it.
TARGET_BANDS = (2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0)

# How far above the Hindcast's Combined Sea a Proxy Target reading may sit before it stops
# being a believable amplification and starts being an instrument fault (#145). The
# Amplification Model's coefficient on the Combined Sea is 1.10, so 1.5 is well clear of the
# transformation the canyon actually performs.
SUSPECT_RATIO = 1.5

# What the sea cannot do in an hour. Measured over the 73,412 consecutive-hour pairs in the
# whole 14-year record: the median change is 0.103 m, the 99th percentile 0.791 m, and the
# largest change the buoy has ever legitimately recorded is 2.33 m, on 2014-12-11. The
# 2026-01 cluster's *smallest* excursion is 4.17 m. Any threshold between those two isolates
# the fault and nothing else; 3.0 sits in the middle of that gap rather than at its edge.
CONTINUITY_BREAK_M_PER_HOUR = 3.0

GOLD_DAYS = ROOT / "analysis" / "gold_days" / "gold_days.jsonl"


@dataclass(frozen=True)
class Counts:
    """What one Big-Wave Season contributed, and what it lost on the way.

    Reported per season rather than as one total because #2's central finding was that the
    record is not uniform: nine of Monican02's sixteen seasons exceed 50% coverage, five sit
    between 16% and 37%, and two recorded nothing at all. A single "73,000 rows" headline
    would hide that entirely, and #13 has to split on seasons that actually hold data.
    """

    season: int
    hindcast_hours: int
    target_hours: int
    paired: int
    target_withheld: int
    in_season: int
    with_wind: int
    with_offshore_observation: int
    gold_day_rows: int
    bands: dict[float, int]

    @property
    def target_hours_unpaired(self) -> int:
        """Hours the buoy reported that no Hindcast hour matched."""
        return self.target_hours - self.paired


def local_moment(key: str) -> dt.datetime:
    """The Nazaré local moment a UTC hour key names.

    ADR 0008 makes the domain day a Nazaré local day, so which season an hour belongs to and
    whether it falls inside the Big-Wave Season are questions about the local calendar rather
    than the UTC one. Portugal runs an hour ahead through late October and late March, which
    is precisely where the season boundaries sit: `2016-09-30T23:00Z` is local
    `2016-10-01T00:00` and opens the 2016 season, though its UTC month still says September.
    Asking this once, here, is what keeps `season` from disagreeing with `day` in the same row.
    """
    return dt.datetime.fromisoformat(reanalysis.local_stamp(dt.datetime.fromisoformat(key)))


def season_of(moment: dt.datetime) -> int:
    """The Big-Wave Season a moment belongs to, named by the year it begins in.

    Takes a **local** moment — see `local_moment`.

    October to December belong to the season starting that year; January to March belong to
    the one that started the previous year. April to September belong to no season, and are
    labelled by the same rule so that the summer either side of a season is not silently
    folded into it — a caller filtering to the Big-Wave Season months does that filtering
    explicitly.

    Duplicated from `analyse_coverage.season_of` in behaviour but not in signature: that one
    is vectorised over a pandas index, this one takes a single moment, and the vectorised
    version cannot be reused without pulling the whole frame representation through this
    module.
    """
    return moment.year if moment.month >= analyse_coverage.SEASON_START_MONTH else moment.year - 1


def is_big_wave_season(moment: dt.datetime) -> bool:
    """Whether a **local** moment falls in the October-to-March window — see `local_moment`."""
    return moment.month in analyse_coverage.SEASON_MONTHS


def _round(value: float) -> float:
    """Always a float, so a provider returning a whole number does not write a bare integer.

    Open-Meteo returns wind direction as an integer, which `_cell` would then render as `267`
    beside `266.500` from the next source. Same value, two shapes, in one column.
    """
    return round(float(value), DECIMALS)


def read_hindcast() -> dict[str, dict[str, float]]:
    """The Copernicus IBI Hindcast, keyed by UTC hour, in this project's variable names.

    IBI rather than WAVERYS because #36 and #39 made it the primary: 1/36° against 1/5°,
    hourly against 3-hourly, and its nearest wet node sits 1.12 km from the Proxy Target
    against WAVERYS's 4.53 km. `reanalysis.read` has already validated units, the wet node
    and the cadence, and has already dropped any hour carrying a NaN in any variable — so an
    hour present here is complete.
    """
    series = reanalysis.read(reanalysis.IBI)
    rows: dict[str, dict[str, float]] = {}
    for key, reading in series.readings.items():
        rows[key] = {
            "swell_height_m": reanalysis.combined_swell_height(
                reading["VHM0_SW1"], reading["VHM0_SW2"]
            ),
            "swell_period_s": reading["VTM01_SW1"],
            "swell_direction_deg": reading["VMDR_SW1"],
            "secondary_swell_height_m": reading["VHM0_SW2"],
            "secondary_swell_period_s": reading["VTM01_SW2"],
            "secondary_swell_direction_deg": reading["VMDR_SW2"],
            "hindcast_combined_sea_height_m": reading["VHM0"],
        }
    return rows


def read_wind() -> tuple[dict[str, dict[str, float]], set[str]]:
    """ERA5 wind, keyed by the Nazaré **local** stamp, with the ambiguous hours named.

    Open-Meteo is asked for local timestamps and answers with them, so unlike every other
    source in this build the wind cannot be keyed by UTC — the response does not carry it.
    That is fine for lookup, except at the autumn fold, where two distinct UTC hours share
    one local stamp and the response holds only one row for the pair.

    Rather than pick one of the two UTC hours to give the wind to, or give the same wind to
    both, the fold's stamps are returned as a second value and the caller leaves wind absent
    on those hours. It is one or two hours a year against roughly seventy thousand, and the
    alternative is a small deliberate lie inside a dataset whose whole claim is that nothing
    in it was filled in.
    """
    series = hindcast.wind()
    rows = {
        at: {
            "wind_speed_kmh": reading["wind_speed_10m"],
            "wind_direction_deg": reading["wind_direction_10m"],
        }
        for at, reading in series.readings.items()
    }
    return rows, ambiguous_local_stamps(rows.keys())


def ambiguous_local_stamps(stamps: Iterable[str]) -> set[str]:
    """Local stamps that name two different UTC hours — the autumn summer-time fold.

    Found by asking the timezone rather than by hardcoding late October: the rule that sets
    the fold has changed before and is set by legislation, not by arithmetic.
    """
    fold: set[str] = set()
    for stamp in stamps:
        moment = dt.datetime.fromisoformat(stamp)
        earlier = moment.replace(tzinfo=reanalysis.NAZARE, fold=0)
        later = moment.replace(tzinfo=reanalysis.NAZARE, fold=1)
        if earlier.utcoffset() != later.utcoffset():
            fold.add(stamp)
    return fold


def read_buoy(code: str, wanted: dict[str, str]) -> dict[str, dict[str, float]]:
    """One mooring's wave record, quality-controlled, keyed by UTC hour.

    `wanted` maps the source variable to the column it becomes, and its first entry must be
    `VHM0` — an hour the instrument did not give a usable Significant Wave Height for is not
    an hour of record at all, whatever else it carried.

    Quality control is `analyse_coverage`'s and deliberately not reimplemented: flags 1 and 2
    only, and the surface DEPTH level rather than index 0, which is the trap that silently
    returns an empty column. #2 measured the rejection rate at 0.047% for Monican02, so this
    removes very little — but what it removes is exactly the readings the instrument itself
    doubts.

    Readings land on the hour they were taken, truncated to the hour. 99.8% of intervals are
    exactly 60 minutes, so this is a labelling step rather than a resampling one; where two
    readings share an hour the first is kept, matching `load_platform`'s own rule for
    duplicated stamps.
    """
    frame, _ = analyse_coverage.load_platform(code)
    if frame is None:
        raise FileNotFoundError(
            f"no downloaded record for platform {code} in {analyse_coverage.SOURCE}. Run "
            "analysis/buoy_coverage/download_observations.py first."
        )

    rows: dict[str, dict[str, float]] = {}
    for stamp, row in frame.iterrows():
        height = row.get("VHM0")
        if height is None or height != height:  # NaN: rejected by QC or never recorded
            continue
        key = stamp.to_pydatetime().replace(minute=0, second=0, microsecond=0).isoformat()
        if key in rows:
            continue
        reading: dict[str, float] = {}
        for source, column in wanted.items():
            value = row.get(source)
            if value is not None and value == value:
                reading[column] = float(value)
        rows[key] = reading
    return rows


def pair(
    hindcast_rows: dict[str, dict[str, float]],
    wind_rows: dict[str, dict[str, float]],
    ambiguous: set[str],
    target_rows: dict[str, dict[str, float]],
    offshore_rows: dict[str, dict[str, float]],
) -> list[dict[str, Any]]:
    """Join the sources on the UTC hour into the dataset's rows.

    **An hour qualifies when the Proxy Target and the Hindcast are both present.** Those two
    are what ADR 0004 says the model learns from, and an hour missing either teaches nothing.
    Wind and the Offshore Observation are carried where they exist and left empty where they
    do not, with a flag saying which — a row is never dropped because a secondary input was
    out, and a missing value is never stood in for.

    Rows come out ordered by UTC hour, which is what makes the output byte-stable.
    """
    rows: list[dict[str, Any]] = []
    for key in sorted(target_rows.keys() & hindcast_rows.keys()):
        moment = dt.datetime.fromisoformat(key)
        target = target_rows[key]
        if TARGET_COLUMN not in target:
            continue

        at_local = reanalysis.local_stamp(moment)
        row: dict[str, Any] = {
            "at_utc": key,
            "at_local": at_local,
            "day": at_local[:10],
            "season": season_of(dt.datetime.fromisoformat(at_local)),
        }
        for column, value in hindcast_rows[key].items():
            row[column] = _round(value)

        wind = None if at_local in ambiguous else wind_rows.get(at_local)
        row["wind_present"] = wind is not None
        for column in WIND_COLUMNS:
            row[column] = _round(wind[column]) if wind else None

        offshore = offshore_rows.get(key)
        # Present means the height is there. The period and direction ride along and are
        # left empty individually when the instrument dropped one of them, which #2 measured
        # at 6.5% of Monican01's readings for direction.
        row["offshore_observation_present"] = offshore is not None
        for column in OFFSHORE_COLUMNS:
            value = offshore.get(column) if offshore else None
            row[column] = _round(value) if value is not None else None

        row[TARGET_COLUMN] = _round(target[TARGET_COLUMN])
        rows.append(row)
    return rows


def suspect_target_hours(rows: list[dict[str, Any]]) -> set[str]:
    """The UTC hours whose Proxy Target reading is an instrument fault rather than a sea.

    Ticket #145. Monican02 read 14.00 m against a 4.98 m offshore analysis on 2026-01-25,
    rejoining the Hindcast on either side of the excursion.

    **Two legs, and neither works alone.** Continuity says *which day the instrument was in
    trouble* — a change the sea cannot perform is the only signal that separates the fault
    from a buoy the canyon is genuinely amplifying. The ratio then says *which hours inside
    that day* to withhold, because the surrounding hours are usually a real swell and
    dropping them would throw away exactly the big-sea data the model is short of. Applied
    to the whole record, continuity alone flags three days and nothing else in fourteen
    years, while the ratio alone flags 248 hours across 77 days.
    """
    ordered = sorted(rows, key=lambda row: row["at_utc"])
    in_trouble: set[str] = set()
    for earlier, later in zip(ordered, ordered[1:], strict=False):
        apart = dt.datetime.fromisoformat(later["at_utc"]) - dt.datetime.fromisoformat(
            earlier["at_utc"]
        )
        if apart != dt.timedelta(hours=1):
            continue
        if abs(later[TARGET_COLUMN] - earlier[TARGET_COLUMN]) > CONTINUITY_BREAK_M_PER_HOUR:
            in_trouble.add(earlier["day"])
            in_trouble.add(later["day"])

    return {
        row["at_utc"]
        for row in rows
        if row["day"] in in_trouble
        and row["hindcast_combined_sea_height_m"]
        and row[TARGET_COLUMN] / row["hindcast_combined_sea_height_m"] > SUSPECT_RATIO
    }


def withhold_suspect_targets(rows: list[dict[str, Any]]) -> int:
    """Empty the Proxy Target on the hours the instrument got wrong, and say so. Returns how
    many.

    Every row keeps its place. The Hindcast, the wind and the Offshore Observation on a
    withheld hour are all still good — it is one instrument that failed, not the hour — so
    only the target moves, into `proxy_target_raw_m` where it stays readable.
    """
    suspect = suspect_target_hours(rows)
    for row in rows:
        withheld = row["at_utc"] in suspect
        row[SUSPECT_COLUMN] = withheld
        row[RAW_TARGET_COLUMN] = row[TARGET_COLUMN] if withheld else None
        if withheld:
            row[TARGET_COLUMN] = None
    return len(suspect)


def read_gold_days() -> set[str]:
    """The 38 hand-verified Gold Days, as local day strings.

    Read so the build can report how much of the record sits on a day Praia do Norte is known
    to have gone giant. That count is the one that matters for #13: it is the positive class,
    and ADR 0002 already warns it is a few dozen days across seventeen winters.
    """
    if not GOLD_DAYS.exists():
        return set()
    days: set[str] = set()
    for line in GOLD_DAYS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            days.add(json.loads(line)["date"])
    return days


def count_by_season(
    rows: list[dict[str, Any]],
    hindcast_rows: dict[str, dict[str, float]],
    target_rows: dict[str, dict[str, float]],
    gold_days: set[str],
) -> list[Counts]:
    """What each Big-Wave Season contributed, beside what was available to contribute.

    `hindcast_hours` and `target_hours` are counted from the sources rather than from the
    join, so a season where the two never overlap shows as two healthy numbers and a paired
    count of zero — which is a different failure from a season where neither source has
    anything, and reads differently in the table.
    """
    seasons: dict[int, dict[str, Any]] = {}

    def bucket(season: int) -> dict[str, Any]:
        return seasons.setdefault(
            season,
            {
                "hindcast_hours": 0,
                "target_hours": 0,
                "paired": 0,
                "target_withheld": 0,
                "in_season": 0,
                "with_wind": 0,
                "with_offshore_observation": 0,
                "gold_day_rows": 0,
                "bands": dict.fromkeys(TARGET_BANDS, 0),
            },
        )

    for key in hindcast_rows:
        bucket(season_of(local_moment(key)))["hindcast_hours"] += 1
    for key, reading in target_rows.items():
        if TARGET_COLUMN in reading:
            bucket(season_of(local_moment(key)))["target_hours"] += 1

    for row in rows:
        counts = bucket(int(row["season"]))
        counts["paired"] += 1
        counts["in_season"] += int(is_big_wave_season(dt.datetime.fromisoformat(row["at_local"])))
        counts["with_wind"] += int(bool(row["wind_present"]))
        counts["with_offshore_observation"] += int(bool(row["offshore_observation_present"]))
        counts["gold_day_rows"] += int(row["day"] in gold_days)
        # A withheld hour has no height, so it belongs in no band. It is counted on its own
        # line instead — #145's exclusions are reported where the gap rule's are, because a
        # reading this project threw away should be as visible as one the buoy never took.
        if row.get(SUSPECT_COLUMN):
            counts["target_withheld"] += 1
            continue
        for band in TARGET_BANDS:
            counts["bands"][band] += int(row[TARGET_COLUMN] >= band)

    return [Counts(season=season, **values) for season, values in sorted(seasons.items())]


def _cell(value: Any) -> str:
    """One value as the file will hold it.

    Floats are written to a fixed number of decimals so two runs cannot differ in the last
    place, and booleans as `true`/`false` rather than Python's capitalised repr. `None` is
    the empty string — an absent value, visibly absent, which is the whole point of carrying
    the presence flags beside it.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.{DECIMALS}f}"
    return str(value)


def write_csv(path: Path, header: tuple[str, ...], rows: list[dict[str, Any]]) -> str:
    """Write a table and return its SHA-256.

    `lineterminator="\\n"` because the default is CRLF, which would make the file differ
    between the Windows machine this is developed on and the Linux one CI runs — a
    determinism claim that fails on the first machine that is not the author's is worse than
    no claim.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        for row in rows:
            writer.writerow([_cell(row.get(column)) for column in header])
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> int:
    hindcast_rows = read_hindcast()
    wind_rows, ambiguous = read_wind()
    # Only Hs from Monican02. Its period and direction are real measurements, but they are
    # measurements *of the target*, taken at the same instant the model is asked to predict —
    # an input the serving system could never have. They are left out rather than carried
    # with a warning, because a column present in a training file is a column something will
    # eventually be fitted on.
    target_rows = read_buoy(MONICAN02.code, {"VHM0": TARGET_COLUMN})
    offshore_rows = read_buoy(
        MONICAN01.code,
        dict(zip(("VHM0", "VTPK", "VMDR"), OFFSHORE_COLUMNS, strict=True)),
    )

    rows = pair(hindcast_rows, wind_rows, ambiguous, target_rows, offshore_rows)
    if not rows:
        print(
            "no hour carried both the Proxy Target and the Hindcast — the two archives do "
            "not overlap, which is a download problem rather than a coverage finding",
            file=sys.stderr,
        )
        return 1

    withheld = withhold_suspect_targets(rows)

    gold_days = read_gold_days()
    counts = count_by_season(rows, hindcast_rows, target_rows, gold_days)
    digest = write_csv(DATASET, COLUMNS, rows)

    band_columns = tuple(f"target_ge_{band:g}m" for band in TARGET_BANDS)
    write_csv(
        COVERAGE,
        (
            "season",
            "hindcast_hours",
            "target_hours",
            "paired",
            "target_hours_unpaired",
            "target_withheld",
            "in_big_wave_season",
            "with_wind",
            "with_offshore_observation",
            "gold_day_rows",
            *band_columns,
        ),
        [
            {
                "season": entry.season,
                "hindcast_hours": entry.hindcast_hours,
                "target_hours": entry.target_hours,
                "paired": entry.paired,
                "target_hours_unpaired": entry.target_hours_unpaired,
                "target_withheld": entry.target_withheld,
                "in_big_wave_season": entry.in_season,
                "with_wind": entry.with_wind,
                "with_offshore_observation": entry.with_offshore_observation,
                "gold_day_rows": entry.gold_day_rows,
                **{
                    column: entry.bands[band]
                    for column, band in zip(band_columns, TARGET_BANDS, strict=True)
                },
            }
            for entry in counts
        ],
    )

    with_wind = sum(entry.with_wind for entry in counts)
    with_offshore = sum(entry.with_offshore_observation for entry in counts)
    in_season = sum(entry.in_season for entry in counts)
    gold_rows = sum(entry.gold_day_rows for entry in counts)
    covered_gold = {row["day"] for row in rows} & gold_days
    live = [entry for entry in counts if entry.paired]

    print(f"rows              : {len(rows):,}")
    print(f"span              : {rows[0]['day']} -> {rows[-1]['day']}")
    print(f"seasons with rows : {len(live)} of {len(counts)}")
    print(f"Big-Wave Season   : {in_season:,} rows ({in_season / len(rows):.1%})")
    print(f"with wind         : {with_wind:,} ({with_wind / len(rows):.1%})")
    print(f"with Monican01    : {with_offshore:,} ({with_offshore / len(rows):.1%})")
    # Printed every build, with the dates, because the rule can in principle reach a day
    # nobody has looked at. A rebuild that withholds a different set should be impossible to
    # miss rather than something a reader has to go diffing for.
    withheld_days = sorted({row["day"] for row in rows if row[SUSPECT_COLUMN]})
    print(f"withheld (#145)   : {withheld:,} hours on {', '.join(withheld_days) or 'no days'}")
    print("Proxy Target      :")
    for band in TARGET_BANDS:
        hit = sum(entry.bands[band] for entry in counts)
        print(f"  >= {band:>4.1f} m       : {hit:>6,} rows ({hit / len(rows):5.1%})")
    print(f"Gold Days         : {gold_rows:,} rows on {len(covered_gold)} of {len(gold_days)} days")
    print(f"sha256            : {digest}")
    print(f"wrote             : {DATASET.relative_to(ROOT)}")
    print(f"                    {COVERAGE.relative_to(ROOT)}")
    return 0


def check() -> int:
    """Self-tests for the join, the gap rule and the byte-stability, all offline.

    The seam this analysis can be tested at is arithmetic, not HTTP: there is no API here to
    drive from outside, and the epic's two agreed seams are the backend API and the rendered
    interface. So the same convention as `probe.py --check` and `reanalysis.py --check` —
    every claim the README makes about how hours are joined is exercised here against
    synthetic input, so a reader can run it without credentials or a download.
    """
    failures: list[str] = []

    def expect(label: str, got: object, want: object) -> None:
        if got != want:
            failures.append(f"{label}: expected {want!r}, got {got!r}")

    # A season is named by the year it begins in, and the boundary is October.
    expect("october belongs to the season it starts", season_of(dt.datetime(2016, 10, 1)), 2016)
    expect("september belongs to the previous one", season_of(dt.datetime(2016, 9, 30)), 2015)
    expect("march closes the season before it", season_of(dt.datetime(2017, 3, 31)), 2016)

    # ...and the boundary is the **local** one, per ADR 0008. Portugal is still an hour ahead
    # on 30 September, so 23:00 UTC is 00:00 local on 1 October and opens the 2016 season —
    # the UTC moment on its own says September and gets both answers wrong.
    autumn = "2016-09-30T23:00:00"
    expect("the season boundary is local", season_of(local_moment(autumn)), 2016)
    expect("that hour is in the Big-Wave Season", is_big_wave_season(local_moment(autumn)), True)
    expect("the UTC moment disagrees", season_of(dt.datetime.fromisoformat(autumn)), 2015)

    # The same hour at the closing edge: 23:00 UTC on 31 March is 00:00 local on 1 April, so
    # the season is over even though the UTC month is still March.
    spring = "2017-03-31T23:00:00"
    expect("the closing edge is local too", is_big_wave_season(local_moment(spring)), False)
    expect(
        "where the UTC moment disagrees",
        is_big_wave_season(dt.datetime.fromisoformat(spring)),
        True,
    )

    hour = "2016-11-05T06:00:00"
    hindcast_rows = {
        hour: {
            "swell_height_m": 4.0,
            "swell_period_s": 14.0,
            "swell_direction_deg": 300.0,
            "secondary_swell_height_m": 1.0,
            "secondary_swell_period_s": 8.0,
            "secondary_swell_direction_deg": 280.0,
            "hindcast_combined_sea_height_m": 4.2,
        },
        "2016-11-05T07:00:00": {
            "swell_height_m": 4.1,
            "swell_period_s": 14.1,
            "swell_direction_deg": 301.0,
            "secondary_swell_height_m": 1.1,
            "secondary_swell_period_s": 8.1,
            "secondary_swell_direction_deg": 281.0,
            "hindcast_combined_sea_height_m": 4.3,
        },
    }
    wind_rows = {"2016-11-05T06:00": {"wind_speed_kmh": 12.0, "wind_direction_deg": 90.0}}
    # Two target hours, one of which the Hindcast never covered. That second hour is the
    # unpaired side of the join — the shape the 2,215 hours predating the IBI download take,
    # and the number the coverage table reports as `target_hours_unpaired`.
    unpaired_hour = "2016-11-05T08:00:00"
    target_rows = {hour: {TARGET_COLUMN: 5.5}, unpaired_hour: {TARGET_COLUMN: 3.0}}
    offshore_rows = {hour: {"offshore_observed_height_m": 6.0}}

    rows = pair(hindcast_rows, wind_rows, set(), target_rows, offshore_rows)

    # The Hindcast has two hours and the buoy one. The unmatched hour is dropped, not
    # carried forward from its neighbour — this is the gap rule, and it is the criterion of
    # the ticket that a silent fill would violate.
    expect("an hour without the target is dropped", len(rows), 1)
    expect("the surviving hour is the paired one", rows[0]["at_utc"], hour)
    expect("the target is carried", rows[0][TARGET_COLUMN], 5.5)

    # Present-but-partial: Monican01 reported a height and no period. The height is carried,
    # the period stays empty, and the row still counts as having an Offshore Observation.
    expect("a partial offshore reading is present", rows[0]["offshore_observation_present"], True)
    expect("its height is carried", rows[0]["offshore_observed_height_m"], 6.0)
    expect("its absent period stays empty", rows[0]["offshore_observed_period_s"], None)

    # Wind is matched on the local stamp. November is winter, so 06:00 UTC is 06:00 local.
    expect("wind is joined on the local stamp", rows[0]["wind_present"], True)
    expect("wind speed is carried", rows[0]["wind_speed_kmh"], 12.0)

    # ...and an hour whose local stamp is ambiguous gets no wind rather than a guess.
    folded = pair(hindcast_rows, wind_rows, {"2016-11-05T06:00"}, target_rows, offshore_rows)
    expect("an ambiguous hour gets no wind", folded[0]["wind_present"], False)
    expect("and no speed", folded[0]["wind_speed_kmh"], None)

    # The autumn fold is found by asking the timezone. In 2016 Lisbon went back on 30 October,
    # so 01:00 local names two UTC hours and 02:00 names one.
    fold = ambiguous_local_stamps(["2016-10-30T01:00", "2016-10-30T02:00", "2016-11-05T06:00"])
    expect("the fold hour is ambiguous", "2016-10-30T01:00" in fold, True)
    expect("the hour after it is not", "2016-10-30T02:00" in fold, False)
    expect("an ordinary hour is not", "2016-11-05T06:00" in fold, False)

    # Availability is counted from the sources, not from the join, so a season that lost one
    # instrument reads as a healthy number beside a low paired count rather than as a blank.
    # Both directions are exercised: an hour the Hindcast has and the buoy does not, and an
    # hour the buoy has and the Hindcast does not.
    counts = count_by_season(rows, hindcast_rows, target_rows, gold_days={"2016-11-05"})
    expect("one season is reported", len(counts), 1)
    expect("both Hindcast hours are counted as available", counts[0].hindcast_hours, 2)
    expect("both target hours are counted as available", counts[0].target_hours, 2)
    expect("only one paired", counts[0].paired, 1)
    expect("so one target hour is unpaired", counts[0].target_hours_unpaired, 1)
    expect("november is inside the Big-Wave Season", counts[0].in_season, 1)
    expect("the row lands on its Gold Day", counts[0].gold_day_rows, 1)

    # The bands are inclusive lower bounds, and a 5.5 m target sits in every band up to 5.
    expect("a 5.5 m target clears the 5 m band", counts[0].bands[5.0], 1)
    expect("and does not clear the 6 m band", counts[0].bands[6.0], 0)

    # A day that is not a Gold Day contributes nothing to that count, so the positive class
    # cannot be inflated by a date that merely looks stormy.
    plain = count_by_season(rows, hindcast_rows, target_rows, gold_days=set())
    expect("a non-Gold day counts zero", plain[0].gold_day_rows, 0)

    # How a withheld hour counts. It *was* paired — the Hindcast had it and the buoy reported
    # something — so the pairing figure is unchanged and the join's own story stays honest.
    # What it must not do is enter a Proxy Target band, because the band table is the one a
    # reader uses to judge how much big-sea data the record holds, and a 14 m reading the
    # instrument invented would put a row in a band nothing ever reached.
    faulty_targets = {hour: {TARGET_COLUMN: 5.5}, "2016-11-05T07:00:00": {TARGET_COLUMN: 14.0}}
    faulty = pair(hindcast_rows, wind_rows, set(), faulty_targets, offshore_rows)
    expect("one hour is withheld", withhold_suspect_targets(faulty), 1)
    faulty_counts = count_by_season(faulty, hindcast_rows, faulty_targets, gold_days=set())
    expect("a withheld hour is still a paired hour", faulty_counts[0].paired, 2)
    expect("the season says how many it withheld", faulty_counts[0].target_withheld, 1)
    expect("the invented height reaches no band", faulty_counts[0].bands[8.0], 0)
    expect("the hour beside it still counts", faulty_counts[0].bands[5.0], 1)

    # Byte-stability: the same rows written twice give the same digest, and formatting is
    # fixed rather than repr-dependent.
    scratch = OUTPUT / "_check.csv"
    first = write_csv(scratch, COLUMNS, rows)
    second = write_csv(scratch, COLUMNS, rows)
    expect("writing is deterministic", first, second)
    text = scratch.read_text(encoding="utf-8")
    expect("newlines are LF", "\r\n" in text, False)
    expect("floats carry fixed decimals", "5.500" in text, True)
    expect("absent values are empty", ",," in text, True)
    scratch.unlink()

    expect("a float is formatted, not repr'd", _cell(0.1 + 0.2), "0.300")
    expect("a bool is lowercase", _cell(True), "true")
    expect("None is empty", _cell(None), "")

    # #145 — the Proxy Target's instrument fault. Significant Wave Height is a sea-state
    # statistic over tens of minutes, so it cannot double and halve within an hour.
    # Monican02 did exactly that on 2026-01-24, 25 and 26. These drive the rule against
    # synthetic hours shaped like the real ones, so the claim is checkable without the
    # gitignored dataset.
    def episode(day: str, *readings: tuple[str, float, float]) -> list[dict[str, Any]]:
        """Rows carrying only the three fields the rule reads."""
        return [
            {
                "at_utc": f"{day}T{hour}:00:00",
                "at_local": f"{day}T{hour}:00",
                "day": day,
                "hindcast_combined_sea_height_m": hindcast,
                TARGET_COLUMN: target,
            }
            for hour, target, hindcast in readings
        ]

    # The 25th, as recorded: a smooth Hindcast decay with the buoy tripling through it.
    spike = episode(
        "2026-01-25",
        ("07", 5.71, 5.20),
        ("08", 9.83, 5.08),
        ("09", 14.00, 4.98),
        ("10", 9.67, 4.90),
        ("11", 5.43, 4.83),
    )
    expect(
        "the excursion's own hours are withheld",
        sorted(suspect_target_hours(spike)),
        ["2026-01-25T08:00:00", "2026-01-25T09:00:00", "2026-01-25T10:00:00"],
    )

    # The ratio on its own is not a spike detector and must never be used as one. On a small
    # sea it is simply unstable: 2020-01-13 runs to 4.78 and 2018-01-29 to 3.96 across long
    # *smooth* stretches the buoy recorded perfectly well. Continuity is what separates the
    # fault from the noise, so nothing here may be withheld however high the ratio climbs.
    calm = episode(
        "2020-01-13",
        ("09", 1.84, 0.46),
        ("10", 1.86, 0.47),
        ("11", 1.88, 0.47),
        ("12", 1.85, 0.48),
    )
    expect("a smooth small sea is never withheld", suspect_target_hours(calm), set())

    # The other edge, and the one that actually costs something if it moves. These are
    # 2014-12-11's real readings: a genuine 6-8 m sea the canyon was amplifying hard, with
    # five hours sitting above SUSPECT_RATIO and a 10:00 -> 11:00 fall of 2.33 m that is the
    # largest change in the entire record. Continuity is the only thing holding them, so if
    # CONTINUITY_BREAK_M_PER_HOUR is ever lowered under that figure this goes red and names
    # the five hours it would have thrown away.
    steep = episode(
        "2014-12-11",
        ("08", 5.55, 3.86),
        ("09", 6.20, 4.01),
        ("10", 8.07, 4.09),
        ("11", 5.74, 4.12),
        ("12", 7.68, 4.16),
        ("13", 7.19, 4.18),
        ("14", 6.31, 4.17),
    )
    expect("the record's steepest real hour is kept", suspect_target_hours(steep), set())

    # 2026-01-26 as recorded, gaps and all: the buoy reported six hours out of twenty-four,
    # because a mooring in trouble drops readings. That matters to the rule's shape. 06:00
    # has no neighbour an hour either side, so a continuity test asked to name *hours* would
    # clear it on a technicality — it is 10.47 m against a 4.61 m analysis. Continuity names
    # the day and the ratio names the hours, which is what reaches it.
    intermittent = episode(
        "2026-01-26",
        ("03", 13.76, 5.00),
        ("04", 6.77, 4.87),
        ("06", 10.47, 4.61),
        ("08", 5.00, 4.39),
        ("10", 10.22, 4.12),
        ("11", 4.45, 3.99),
    )
    expect(
        "an excursion marooned between gaps is still withheld",
        sorted(suspect_target_hours(intermittent)),
        ["2026-01-26T03:00:00", "2026-01-26T06:00:00", "2026-01-26T10:00:00"],
    )

    # What a withheld hour looks like in the file. The reading is not deleted — #145 asks for
    # the exclusion to be deliberate and recorded, and a value removed because it disagrees
    # with a model has to stay auditable. So the hour keeps its row, the target goes empty so
    # every consumer's existing "is it present?" test drops it without being taught anything
    # new, the flag says the emptiness was a decision rather than an outage, and the raw
    # reading rides along beside it.
    withheld = episode(
        "2026-01-25",
        ("07", 5.71, 5.20),
        ("08", 9.83, 5.08),
        ("09", 14.00, 4.98),
        ("10", 9.67, 4.90),
        ("11", 5.43, 4.83),
    )
    expect("the count of withheld hours is returned", withhold_suspect_targets(withheld), 3)
    by_hour = {row["at_utc"]: row for row in withheld}
    excluded = by_hour["2026-01-25T09:00:00"]
    expect("a withheld hour carries no target", excluded[TARGET_COLUMN], None)
    expect("it says so", excluded[SUSPECT_COLUMN], True)
    expect("and the reading is preserved", excluded[RAW_TARGET_COLUMN], 14.00)
    kept = by_hour["2026-01-25T11:00:00"]
    expect("an hour either side keeps its target", kept[TARGET_COLUMN], 5.43)
    expect("is not flagged", kept[SUSPECT_COLUMN], False)
    expect("and carries no raw copy", kept[RAW_TARGET_COLUMN], None)

    for failure in failures:
        print(f"FAIL {failure}")
    print(f"{'FAILED' if failures else 'ok'} — {len(failures)} failure(s)")
    return 1 if failures else 0


def main() -> int:
    if "--check" in sys.argv[1:]:
        return check()
    return build()


if __name__ == "__main__":
    raise SystemExit(main())

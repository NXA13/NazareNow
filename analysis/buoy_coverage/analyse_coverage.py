"""Measure what the MONICAN buoys actually recorded, and where the holes are.

ADR 0002 assumes a substantially complete hourly record of Significant Wave Height
from 2009. This script tests that assumption rather than trusting it. It reports
coverage per Big-Wave Season, what the two moorings cover jointly, whether they were
reporting on days Praia do Norte is known to have gone giant, and what can and cannot
be established about changes to the instruments.

Run download_observations.py first.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import xarray as xr

from platforms import PLATFORMS

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402 — must follow the backend selection

SOURCE = Path(__file__).resolve().parents[2] / "data" / "raw" / "buoy"
OUTPUT = Path(__file__).parent / "output"
CANDIDATE_DAYS = Path(__file__).parent / "candidate_xxl_days.csv"

# The wave variables the project might depend on. VHM0 is the Proxy Target itself;
# the others are candidate inputs or sanity checks.
WAVE_VARIABLES = {
    "VHM0": "significant wave height",
    "VTPK": "peak period",
    "VTM02": "mean period",
    "VMDR": "mean direction",
    "VPED": "direction at peak period",
    "VZMX": "maximum wave height",
}

# Copernicus in-situ quality flags: 1 good, 2 probably good, everything else suspect.
GOOD_QC_FLAGS = (1, 2)

# The Big-Wave Season runs October to March. See CONTEXT.md — a season is named by the
# year it begins in and is never a calendar year.
SEASON_MONTHS = (10, 11, 12, 1, 2, 3)
SEASON_START_MONTH = 10

# A Usable Day is one where the instrument reported for at least this fraction of hours.
USABLE_DAY_THRESHOLD = 0.75


def season_of(index: pd.DatetimeIndex) -> np.ndarray:
    """The Big-Wave Season each timestamp belongs to, labelled by its starting year.

    October to December belong to the season starting that year; January to March
    belong to the season that started the previous year. Grouping these by calendar
    year instead splits every season in half and can make a completely dead season
    look partially covered.
    """
    return np.where(index.month >= SEASON_START_MONTH, index.year, index.year - 1)


def surface_level(dataset: xr.Dataset) -> int:
    """Index of the DEPTH level holding surface measurements.

    These files stack several sensor levels on one DEPTH dimension — typically
    -4 m (above water, for the met sensors), 0 m, 0.5 m and 1 m. Wave parameters
    are surface quantities and live at 0 m, which is not index 0. Selecting
    positionally silently returns an entirely empty column.
    """
    depths = dataset["DEPH"].to_numpy()
    return int(np.argmin(np.abs(depths)))


def extract(dataset: xr.Dataset) -> tuple[pd.DataFrame, dict[str, int]]:
    """Pull the wave variables out of one file, applying quality control.

    Returns the frame and a tally of readings present before and after QC, so the
    rejection rate can be reported rather than asserted.
    """
    columns: dict[str, np.ndarray] = {}
    level = surface_level(dataset)
    tally = {"before_qc": 0, "after_qc": 0}

    for name in WAVE_VARIABLES:
        if name not in dataset:
            continue
        values = dataset[name]
        if "DEPTH" in values.dims:
            values = values.isel(DEPTH=level)
        series = values.to_numpy().astype("float64").ravel()

        flag_name = f"{name}_QC"
        if flag_name in dataset:
            flags = dataset[flag_name]
            if "DEPTH" in flags.dims:
                flags = flags.isel(DEPTH=level)
            flags = flags.to_numpy().ravel()
            if name == "VHM0":
                tally["before_qc"] = int(np.isfinite(series).sum())
            series = np.where(np.isin(flags, GOOD_QC_FLAGS), series, np.nan)
            if name == "VHM0":
                tally["after_qc"] = int(np.isfinite(series).sum())

        columns[name] = series

    # Position is recorded per observation, so a redeployment would show up as a jump.
    for name in ("LATITUDE", "LONGITUDE"):
        if name in dataset:
            values = dataset[name].to_numpy().ravel().astype("float64")
            if values.size == 1:
                values = np.repeat(values, dataset.sizes["TIME"])
            columns[name.lower()] = values

    frame = pd.DataFrame(columns, index=pd.to_datetime(dataset["TIME"].to_numpy()))
    frame.index.name = "time"
    return frame, tally


def load_platform(code: str) -> tuple[pd.DataFrame | None, dict[str, int]]:
    """Read every file for one platform into a single time-indexed frame."""
    files = sorted(SOURCE.glob(f"*{code}*.nc"))
    if not files:
        return None, {}

    frames, tally = [], {"before_qc": 0, "after_qc": 0}
    for path in files:
        with xr.open_dataset(path, decode_timedelta=False) as dataset:
            frame, counts = extract(dataset)
            frames.append(frame)
            for key in tally:
                tally[key] += counts.get(key, 0)
    if not frames:
        return None, tally

    combined = pd.concat(frames).sort_index()
    return combined[~combined.index.duplicated(keep="first")], tally


def hourly_presence(frame: pd.DataFrame) -> pd.Series:
    """Whether usable Significant Wave Height exists in each hour of the record."""
    return frame["VHM0"].resample("h").mean().notna()


def usable_days(frame: pd.DataFrame) -> set:
    """The Usable Days within the Big-Wave Season, as dates."""
    present = hourly_presence(frame)
    in_season = present[present.index.month.isin(SEASON_MONTHS)]
    daily = in_season.resample("D").mean()
    return set(daily[daily >= USABLE_DAY_THRESHOLD].index.date)


def coverage_by_season(frame: pd.DataFrame) -> pd.DataFrame:
    """Coverage per Big-Wave Season, against the hours the season actually contains.

    The denominator is the full season, not the span the instrument happened to
    report over. Using the observed span flatters partial seasons — a buoy that dies
    in October would otherwise score near 100% for the season it missed.
    """
    present = hourly_presence(frame)
    in_season = present[present.index.month.isin(SEASON_MONTHS)]
    days = usable_days(frame)

    rows = []
    for season in sorted(set(season_of(in_season.index))):
        mask = season_of(in_season.index) == season
        # October to March, accounting for a February that may have 29 days.
        span_hours = int(
            (pd.Timestamp(season + 1, 4, 1) - pd.Timestamp(season, 10, 1)).total_seconds() // 3600
        )
        usable = int(in_season[mask].sum())
        rows.append(
            {
                "season": f"{season}/{str(season + 1)[2:]}",
                "season_hours": span_hours,
                "hours_usable": usable,
                "coverage_pct": round(100 * usable / span_hours, 1),
                "usable_days": sum(
                    1 for d in days if season_of(pd.DatetimeIndex([d]))[0] == season
                ),
            }
        )
    return pd.DataFrame(rows)


def describe_cadence(frame: pd.DataFrame) -> str:
    """Reporting interval, with enough spread to justify calling it stable or not."""
    gaps = frame.index.to_series().diff().dropna()
    if gaps.empty:
        return "unknown"
    minutes = gaps.dt.total_seconds() / 60
    hourly = 100 * float((minutes.between(59, 61)).mean())
    return (
        f"median {minutes.median():.0f} min; {hourly:.1f}% of intervals are 60 min "
        f"(the remainder are outage gaps, max {minutes.max() / 1440:.0f} days)"
    )


def describe_position(frame: pd.DataFrame) -> str:
    """Position, stated with the precision the source actually provides.

    Coordinates are stored to 0.01 degrees, roughly 1.1 km. Movement smaller than that
    is invisible here, so this can establish that a mooring was not relocated
    substantially — not that it never moved.
    """
    if "latitude" not in frame or frame["latitude"].isna().all():
        return "not recorded per observation"
    # Dropped as a pair, so a row missing either coordinate is discarded whole. Zipping
    # two separately-dropped series would either truncate silently against a malformed
    # frame or raise, and neither is wanted in a reporting script.
    fixes = frame[["latitude", "longitude"]].dropna()
    lat, lon = fixes["latitude"], fixes["longitude"]
    distinct = len(fixes.round(4).drop_duplicates())
    return (
        f"{lat.mean():.2f}N {abs(lon.mean()):.2f}W, {distinct} distinct position(s) "
        f"reported; resolution ~1.1 km, so smaller movement is undetectable"
    )


def describe_instrument(code: str) -> str:
    """What can be said about instrument changes — which is very little.

    The files carry no sensor model, serial number or deployment record, so a swapped
    instrument would be invisible. The data mode flag is the nearest available proxy:
    it distinguishes real-time from delayed-mode processing.
    """
    path = next(iter(sorted(SOURCE.glob(f"*{code}*.nc"))), None)
    if path is None:
        return "no files"
    with xr.open_dataset(path, decode_timedelta=False) as dataset:
        wanted = ("instrument", "sensor", "serial", "device")
        fields = [k for k in dataset.attrs if any(t in k.lower() for t in wanted)]
        modes: set[str] = set()
        if "VHM0_DM" in dataset:
            for value in dataset["VHM0_DM"].to_numpy().ravel():
                text = value.decode() if isinstance(value, bytes) else str(value)
                if text.strip() not in ("", "nan"):
                    modes.add(text.strip())
    if fields:
        return f"instrument metadata present: {fields}"
    return (
        "no instrument metadata in source, so a sensor change would be undetectable; "
        f"data modes present: {'/'.join(sorted(modes)) or 'none'} "
        "(R real-time, D delayed-mode)"
    )


def variable_availability(frame: pd.DataFrame) -> pd.DataFrame:
    total = len(frame)
    rows = []
    for name, description in WAVE_VARIABLES.items():
        present = 100 * frame[name].notna().mean() if name in frame and total else 0.0
        rows.append(
            {"variable": name, "description": description, "present_pct": round(float(present), 1)}
        )
    return pd.DataFrame(rows)


def load_candidate_days() -> list[dict[str, str]]:
    """Provisional dates Praia do Norte is believed to have gone giant. Not Gold Days."""
    if not CANDIDATE_DAYS.exists():
        return []
    with CANDIDATE_DAYS.open(encoding="utf-8") as handle:
        lines = [line for line in handle if not line.startswith("#")]
    return list(csv.DictReader(lines))


def candidate_day_report(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Was each buoy reporting on days known to have been giant, and what did it read?"""
    rows = []
    for entry in load_candidate_days():
        row = {"date": entry["date"], "event": entry["event"], "confidence": entry["confidence"]}
        for name, frame in frames.items():
            day = frame["VHM0"][frame.index.strftime("%Y-%m-%d") == entry["date"]]
            row[name] = round(float(day.max()), 2) if day.notna().any() else None
        rows.append(row)
    return pd.DataFrame(rows)


def joint_coverage(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """How much the two moorings cover together, since their outages differ."""
    days = {name: usable_days(frame) for name, frame in frames.items()}
    names = list(days)
    if len(names) != 2:
        return pd.DataFrame()
    first, second = days[names[0]], days[names[1]]
    return pd.DataFrame(
        [
            {"measure": names[0], "usable_days": len(first)},
            {"measure": names[1], "usable_days": len(second)},
            {"measure": "both on the same day", "usable_days": len(first & second)},
            {"measure": f"only {names[0]}", "usable_days": len(first - second)},
            {"measure": f"only {names[1]}", "usable_days": len(second - first)},
            {"measure": "either buoy", "usable_days": len(first | second)},
        ]
    )


def plot(frames: dict[str, pd.DataFrame], seasons: dict[str, pd.DataFrame]) -> Path:
    """Monthly grid showing where the gaps are, plus coverage per Big-Wave Season."""
    fig, axes = plt.subplots(
        len(frames), 2, figsize=(17, 3.4 * len(frames)), squeeze=False, width_ratios=[3, 2]
    )

    for row, (name, frame) in enumerate(frames.items()):
        monthly = hourly_presence(frame).resample("MS").mean() * 100
        grid = monthly.to_frame("coverage")
        grid["year"], grid["month"] = grid.index.year, grid.index.month
        pivot = grid.pivot_table(index="year", columns="month", values="coverage")
        pivot = pivot.reindex(columns=range(1, 13))

        axis = axes[row, 0]
        image = axis.imshow(
            pivot.to_numpy(),
            aspect="auto",
            cmap="viridis",
            vmin=0,
            vmax=100,
            interpolation="nearest",
        )
        axis.set_yticks(range(len(pivot.index)), pivot.index)
        axis.set_xticks(range(12), ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"])
        axis.set_title(f"{name} — monthly coverage of Significant Wave Height (%)")
        # Divide the Big-Wave Season from the months that do not matter here.
        for boundary in (2.5, 8.5):
            axis.axvline(boundary, color="red", lw=1.5)
        axis.set_xlabel("red lines bound Apr-Sep; outside them is the Big-Wave Season")
        fig.colorbar(image, ax=axis, label="% of hours present")

        axis = axes[row, 1]
        table = seasons[name]
        colours = [
            "#c0392b" if v < 5 else "#e67e22" if v < 50 else "#27ae60"
            for v in table["coverage_pct"]
        ]
        axis.bar(range(len(table)), table["coverage_pct"], color=colours)
        axis.set_xticks(range(len(table)), table["season"], rotation=90, fontsize=8)
        axis.set_ylim(0, 100)
        axis.set_ylabel("% of season hours")
        axis.set_title(f"{name} — coverage per Big-Wave Season (Oct-Mar)")
        axis.axhline(50, color="grey", ls=":", lw=1)

    fig.tight_layout()
    path = OUTPUT / "coverage.png"
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)

    if not SOURCE.exists() or not any(SOURCE.glob("*.nc")):
        print(f"No buoy files in {SOURCE}")
        print("Run download_observations.py first (needs a Copernicus Marine login).")
        return 1

    frames: dict[str, pd.DataFrame] = {}
    seasons: dict[str, pd.DataFrame] = {}
    all_seasons = []

    for platform in PLATFORMS:
        frame, tally = load_platform(platform.code)
        if frame is None or "VHM0" not in frame:
            print(f"\n{platform.name} ({platform.code}): no usable Significant Wave Height found")
            continue
        frames[platform.name] = frame

        rejected = tally["before_qc"] - tally["after_qc"]
        rejected_pct = 100 * rejected / tally["before_qc"] if tally["before_qc"] else 0.0

        print(f"\n{'=' * 74}\n{platform.name} ({platform.code})\n{'=' * 74}")
        print(f"  {platform.note}")
        print(f"  span       : {frame.index.min():%Y-%m-%d} to {frame.index.max():%Y-%m-%d}")
        print(f"  readings   : {len(frame):,}")
        print(f"  cadence    : {describe_cadence(frame)}")
        print(f"  position   : {describe_position(frame)}")
        print(f"  instrument : {describe_instrument(platform.code)}")
        print(
            f"  QC         : {rejected:,} of {tally['before_qc']:,} VHM0 readings rejected "
            f"({rejected_pct:.3f}%)"
        )
        print(f"  highest Hs : {frame['VHM0'].max():.2f} m")

        print("\n  variable availability:")
        for row in variable_availability(frame).itertuples():
            print(f"    {row.variable:<7} {row.description:<26} {row.present_pct:>5.1f}%")

        table = coverage_by_season(frame)
        seasons[platform.name] = table
        table_out = table.copy()
        table_out.insert(0, "platform", platform.name)
        all_seasons.append(table_out)

        print("\n  Big-Wave Season   coverage   Usable Days")
        for row in table.itertuples():
            marker = "   <-- effectively lost" if row.coverage_pct < 5 else ""
            print(f"  {row.season:<16} {row.coverage_pct:>7.1f}%   {row.usable_days:>10}{marker}")
        lost = int((table["coverage_pct"] < 5).sum())
        print(f"\n  seasons recorded: {len(table)}, of which {lost} effectively lost")
        print(f"  total Usable Days: {table['usable_days'].sum()}")

    if not frames:
        return 1

    pd.concat(all_seasons, ignore_index=True).to_csv(OUTPUT / "coverage_by_season.csv", index=False)

    joint = joint_coverage(frames)
    if not joint.empty:
        joint.to_csv(OUTPUT / "joint_coverage.csv", index=False)
        print(f"\n{'=' * 74}\nBoth moorings together (Usable Days in the Big-Wave Season)")
        print("=" * 74)
        for row in joint.itertuples():
            print(f"  {row.measure:<26} {row.usable_days:>6}")

    candidates = candidate_day_report(frames)
    if not candidates.empty:
        candidates.to_csv(OUTPUT / "candidate_xxl_day_readings.csv", index=False)
        print(
            f"\n{'=' * 74}\nSignificant Wave Height on candidate XXL Days (PROVISIONAL, see #10)"
            f"\n{'=' * 74}"
        )
        names = [c for c in candidates.columns if c in frames]
        print(f"  {'date':<12} {'confidence':<10} " + "  ".join(f"{n:>11}" for n in names))
        for row in candidates.itertuples(index=False):
            # A missing reading arrives as NaN once pandas has built the column,
            # so testing against None would report every gap as a value.
            cells = [
                "    missing" if pd.isna(getattr(row, n)) else f"{getattr(row, n):>9.2f} m"
                for n in names
            ]
            print(f"  {row.date:<12} {row.confidence:<10} " + "  ".join(f"{c:>11}" for c in cells))

    image = plot(frames, seasons)

    print(f"\n\nWritten: {OUTPUT / 'coverage_by_season.csv'}")
    print(f"Written: {OUTPUT / 'joint_coverage.csv'}")
    print(f"Written: {OUTPUT / 'candidate_xxl_day_readings.csv'}")
    print(f"Written: {image}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

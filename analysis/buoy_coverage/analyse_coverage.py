"""Measure what the MONICAN buoys actually recorded, and where the holes are.

ADR 0002 assumes a substantially complete hourly record of Significant Wave Height
from 2009. This script tests that assumption rather than trusting it. It reports
coverage per year, coverage during the big-wave season specifically, changes in
position or reporting cadence, and which wave variables can be relied on.

Run download_observations.py first.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import xarray as xr

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402 — must follow the backend selection

SOURCE = Path(__file__).resolve().parents[2] / "data" / "raw" / "buoy"
OUTPUT = Path(__file__).parent / "output"

PLATFORMS = {"6200192": "Monican01", "6200199": "Monican02"}

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

# Nazaré's big-wave season, established during design. Coverage outside it matters
# far less — a buoy that works every August and fails every January is useless here.
WINTER_MONTHS = (10, 11, 12, 1, 2, 3)


def load_platform(code: str) -> pd.DataFrame | None:
    """Read every file for one platform into a single hourly-indexed frame."""
    files = sorted(SOURCE.glob(f"*{code}*.nc"))
    if not files:
        return None

    frames = []
    for path in files:
        with xr.open_dataset(path, decode_timedelta=False) as dataset:
            frames.append(extract(dataset))
    if not frames:
        return None

    combined = pd.concat(frames).sort_index()
    return combined[~combined.index.duplicated(keep="first")]


def surface_level(dataset: xr.Dataset) -> int:
    """Index of the DEPTH level holding surface measurements.

    These files stack several sensor levels on one DEPTH dimension — typically
    -4 m (above water, for the met sensors), 0 m, 0.5 m and 1 m. Wave parameters
    are surface quantities and live at 0 m, which is not index 0. Selecting
    positionally silently returns an entirely empty column.
    """
    depths = dataset["DEPH"].to_numpy()
    return int(np.argmin(np.abs(depths)))


def extract(dataset: xr.Dataset) -> pd.DataFrame:
    """Pull the wave variables out of one file, applying quality control."""
    columns: dict[str, np.ndarray] = {}
    level = surface_level(dataset)

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
            series = np.where(np.isin(flags, GOOD_QC_FLAGS), series, np.nan)

        columns[name] = series

    # Position is recorded per observation, so a redeployment shows up as a jump.
    for name in ("LATITUDE", "LONGITUDE"):
        if name in dataset:
            values = dataset[name].to_numpy().ravel().astype("float64")
            if values.size == 1:
                values = np.repeat(values, dataset.sizes["TIME"])
            columns[name.lower()] = values

    frame = pd.DataFrame(columns, index=pd.to_datetime(dataset["TIME"].to_numpy()))
    frame.index.name = "time"
    return frame


def coverage_by_year(frame: pd.DataFrame) -> pd.DataFrame:
    """Hours of usable wave height per year, overall and during the big-wave season."""
    hourly = frame["VHM0"].resample("h").mean()
    present = hourly.notna()

    winter = present[present.index.month.isin(WINTER_MONTHS)]
    # A winter day counts as usable only if the buoy reported for most of it —
    # three scattered readings tell you nothing about whether the day went XXL.
    daily = present[present.index.month.isin(WINTER_MONTHS)].resample("D").mean()

    rows = []
    for year in sorted(set(present.index.year)):
        in_year = present.index.year == year
        in_winter = winter.index.year == year
        usable_days = daily[(daily.index.year == year) & (daily >= 0.75)]
        rows.append({
            "year": year,
            "hours_expected": int(in_year.sum()),
            "hours_usable": int(present[in_year].sum()),
            "coverage_pct": round(100 * present[in_year].mean(), 1) if in_year.sum() else 0.0,
            "winter_hours_usable": int(winter[in_winter].sum()),
            "winter_coverage_pct": round(100 * winter[in_winter].mean(), 1) if in_winter.sum() else 0.0,
            "usable_winter_days": int(len(usable_days)),
        })
    return pd.DataFrame(rows)


def describe_cadence(frame: pd.DataFrame) -> str:
    gaps = frame.index.to_series().diff().dropna()
    if gaps.empty:
        return "unknown"
    median = gaps.median()
    return f"median {median.total_seconds() / 60:.0f} min between readings"


def describe_position(frame: pd.DataFrame) -> str:
    if "latitude" not in frame or frame["latitude"].isna().all():
        return "not recorded per observation"
    lat, lon = frame["latitude"].dropna(), frame["longitude"].dropna()
    spread_km = max(
        (lat.max() - lat.min()) * 111,
        (lon.max() - lon.min()) * 111 * np.cos(np.radians(lat.mean())),
    )
    return (f"{lat.mean():.3f}N {abs(lon.mean()):.3f}W, "
            f"maximum excursion {spread_km:.1f} km")


def variable_availability(frame: pd.DataFrame) -> pd.DataFrame:
    total = len(frame)
    rows = []
    for name, description in WAVE_VARIABLES.items():
        if name not in frame:
            rows.append({"variable": name, "description": description, "present_pct": 0.0})
            continue
        rows.append({
            "variable": name,
            "description": description,
            "present_pct": round(100 * frame[name].notna().mean(), 1) if total else 0.0,
        })
    return pd.DataFrame(rows)


def plot(frames: dict[str, pd.DataFrame]) -> Path:
    """A monthly coverage grid per buoy — gaps are the blank cells."""
    fig, axes = plt.subplots(len(frames), 1, figsize=(14, 3.2 * len(frames)), squeeze=False)

    for axis, (name, frame) in zip(axes[:, 0], frames.items()):
        hourly = frame["VHM0"].resample("h").mean()
        monthly = hourly.notna().resample("MS").mean() * 100

        grid = monthly.to_frame("coverage")
        grid["year"] = grid.index.year
        grid["month"] = grid.index.month
        pivot = grid.pivot_table(index="year", columns="month", values="coverage")
        pivot = pivot.reindex(columns=range(1, 13))

        image = axis.imshow(pivot.to_numpy(), aspect="auto", cmap="viridis",
                            vmin=0, vmax=100, interpolation="nearest")
        axis.set_yticks(range(len(pivot.index)), pivot.index)
        axis.set_xticks(range(12), ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"])
        axis.set_title(f"{name} — monthly coverage of significant wave height (%)")

        # Outline the big-wave season. A gap in July costs this project nothing;
        # a gap in January costs it a whole winter.
        for month in WINTER_MONTHS:
            axis.axvline(month - 1.5, color="red", lw=1.2, alpha=0.6)
            axis.axvline(month - 0.5, color="red", lw=1.2, alpha=0.6)
        axis.set_xlabel("red-bounded months (Oct-Mar) are the big-wave season")
        fig.colorbar(image, ax=axis, label="% of hours present")

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
    all_coverage = []

    for code, name in PLATFORMS.items():
        frame = load_platform(code)
        if frame is None or "VHM0" not in frame:
            print(f"\n{name} ({code}): no usable wave height data found")
            continue
        frames[name] = frame

        print(f"\n{'=' * 70}\n{name} ({code})\n{'=' * 70}")
        print(f"  span      : {frame.index.min():%Y-%m-%d} to {frame.index.max():%Y-%m-%d}")
        print(f"  readings  : {len(frame):,}")
        print(f"  cadence   : {describe_cadence(frame)}")
        print(f"  position  : {describe_position(frame)}")
        print(f"  max VHM0  : {frame['VHM0'].max():.2f} m")

        print("\n  variable availability:")
        for row in variable_availability(frame).itertuples():
            print(f"    {row.variable:<7} {row.description:<26} {row.present_pct:>5.1f}%")

        coverage = coverage_by_year(frame)
        coverage.insert(0, "platform", name)
        all_coverage.append(coverage)

        print("\n  year   coverage   winter cov   usable winter days")
        for row in coverage.itertuples():
            print(f"  {row.year}   {row.coverage_pct:>6.1f}%   {row.winter_coverage_pct:>8.1f}%   "
                  f"{row.usable_winter_days:>6}")
        print(f"\n  TOTAL usable winter days: {coverage['usable_winter_days'].sum()}")

    if not frames:
        return 1

    combined = pd.concat(all_coverage, ignore_index=True)
    combined.to_csv(OUTPUT / "coverage_by_year.csv", index=False)
    image = plot(frames)

    print(f"\n\nWritten: {OUTPUT / 'coverage_by_year.csv'}")
    print(f"Written: {image}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

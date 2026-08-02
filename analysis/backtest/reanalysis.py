"""Reading the Swell partition from the Copernicus wave reanalyses.

Ticket #39. `hindcast.py` can only offer the real **Swell** partition from 2022 onward,
because the free pre-2022 series it reads — Open-Meteo's `era5_ocean` — carries the
**Combined Sea** only. #36 established that two Copernicus reanalyses carry a genuine Swell
partition back to 1980 and cover all 38 Gold Days; see `analysis/waverys/README.md`. This
module fetches them.

**Two series, deliberately.** `IBI` is the primary: 1/36°, hourly, and its nearest wet node
is 1.12 km from the Proxy Target. `WAVERYS` is the cross-check: 1/5°, 3-hourly, nearest wet
node 4.53 km away. They are independent reanalyses of the same ocean run on the same model
family, so where they agree the number is worth more than either alone, and where they
disagree that is a finding rather than an inconvenience. It is the same download twice on
the same credentials for a few megabytes.

**This is a Hindcast** in the CONTEXT.md sense — IBI runs to M-4, WAVERYS to M-2. Neither
can ever serve a Pipeline Run, and nothing here may be wired into one. Training and
backtesting only.

**Credentials.** The data needs a free Copernicus Marine account; the catalogue and the mask
files do not. The toolbox reads `COPERNICUSMARINE_SERVICE_USERNAME` / `_PASSWORD` from the
environment or falls back to its own configuration file, and no username appears anywhere in
this repository. `require_credentials` fails with a sentence explaining how to fix it rather
than letting the toolbox raise from four frames down.

**The wet node is checked, not assumed.** Both products mask land, and at 1/36° a node
1 km off Praia do Norte is close enough to the coast that the nearest node could plausibly
be dry. Each product's own static mask file settles it — and the two use different
conventions, which is why `Product` carries the rule rather than the code assuming one.

Run:
    .venv/Scripts/python.exe analysis/backtest/reanalysis.py
    .venv/Scripts/python.exe analysis/backtest/reanalysis.py --check
"""

from __future__ import annotations

import datetime as dt
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import xarray as xr

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend" / "src"))

from nazarenow.sources.open_meteo import (  # noqa: E402
    LATITUDE,
    LONGITUDE,
    TIMEZONE,
)

CACHE = Path(__file__).resolve().parents[2] / "data" / "raw" / "reanalysis"
"""Beside `data/raw/hindcast/`, and gitignored for the same reason: raw archives are
reproducible from this script and are not the project's work."""

NAZARE = ZoneInfo(TIMEZONE)

START = "2011-01-01"
"""Matches `hindcast.START`. The first Gold Day is 2011-11-01, and the reanalyses reach
1980 — but 1980-1992 runs with no assimilation and no currents at all (#36, QUID), so
reaching further back would buy years of a materially different series."""

END = "2026-12-31"
"""Past the end of both products on purpose. The toolbox clamps to whatever the dataset
actually holds, so this asks for "everything" without hardcoding an M-2 date that goes
stale two months after it is written."""

VARIABLES = (
    "VHM0",
    "VHM0_SW1",
    "VTM01_SW1",
    "VMDR_SW1",
    "VHM0_SW2",
    "VTM01_SW2",
    "VMDR_SW2",
)
"""The Combined Sea total, plus height, period and direction for both swell trains.

`VTM01_*` is a **mean** period — spectral moments (0,1) — not a peak period. Neither
product publishes a per-partition peak period; `VTPK` exists but describes the total
spectrum only. #11 measured that the mean/peak distinction moves this project's numbers, so
the name is worth keeping in view every time this tuple is read."""

EXPECTED_UNITS = {
    "VHM0": "m",
    "VHM0_SW1": "m",
    "VTM01_SW1": "s",
    "VMDR_SW1": "degree",
    "VHM0_SW2": "m",
    "VTM01_SW2": "s",
    "VMDR_SW2": "degree",
}
"""Checked on arrival, for the reason `hindcast.EXPECTED_UNITS` exists: the thresholds
these series are fitted against are bare floats named in metres and seconds, and a provider
that quietly changed a unit would move the bars rather than fail."""

EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True)
class Product:
    """One reanalysis, and everything that differs between the two.

    `sea_flag` names a variable that is 1 over water, when the product ships one. IBI does;
    WAVERYS publishes bathymetry alone and marks land with `_FillValue`, which xarray
    decodes to NaN. Encoding the difference here rather than branching at the call site
    means adding a third product is a table entry.
    """

    name: str
    dataset_id: str
    mask_url: str
    mask_file: str
    depth_variable: str
    sea_flag: str | None
    cadence_hours: int


IBI = Product(
    name="ibi",
    dataset_id="cmems_mod_ibi_wav_my_0.027deg_PT1H-i",
    mask_url=(
        "https://s3.waw3-1.cloudferro.com/mdl-native-10/native/IBI_MULTIYEAR_WAV_005_006/"
        "cmems_mod_ibi_wav_my_0.027deg_static_202311/IBI-MFC_005_006_mask_bathy.nc"
    ),
    mask_file="IBI_mask_bathy.nc",
    depth_variable="deptho",
    sea_flag="mask",
    cadence_hours=1,
)

WAVERYS = Product(
    name="waverys",
    dataset_id="cmems_mod_glo_wav_my_0.2deg_PT3H-i",
    mask_url=(
        "https://s3.waw3-1.cloudferro.com/mdl-native-14/native/GLOBAL_MULTIYEAR_WAV_001_032/"
        "cmems_mod_glo_wav_my_0.2deg_static_202311/WAVERYSV1_bathymeter.nc"
    ),
    mask_file="WAVERYSV1_bathymeter.nc",
    depth_variable="deptho",
    sea_flag=None,
    cadence_hours=3,
)

PRODUCTS = (IBI, WAVERYS)


@dataclass(frozen=True)
class Node:
    """A grid point, and how far it sits from the thing it stands in for."""

    latitude: float
    longitude: float
    depth_m: float
    distance_km: float


@dataclass(frozen=True)
class Series:
    """One reanalysis at one node, validated and keyed by UTC hour.

    **Keyed by UTC, carrying the Nazaré local stamp as a field.** `hindcast.Series` keys by
    local time, which it can do because Open-Meteo is asked for local stamps directly. Doing
    the same here would lose an hour every autumn: when Lisbon leaves summer time, 00:00 and
    01:00 UTC both render as 01:00 local, and a dict keyed on that string keeps one of them.
    One hour a year, every year, in late October — inside the Big-Wave Season. So the key is
    the stamp that is unique by construction, and `at` carries the local day the hour belongs
    to (ADR 0008), which is what `group_by_date` needs.
    """

    name: str
    node: Node
    cadence_hours: int
    readings: dict[str, dict[str, float]]

    def __len__(self) -> int:
        return len(self.readings)

    def rows(self) -> list[dict[str, float | str]]:
        """The readings as `group_by_date` wants them: a list, ordered, each with an `at`.

        A list rather than a dict because the local stamps are not unique — see the class
        docstring. Both sides of a duplicated local hour are kept and both get scored, which
        is right: they are two real hours of that day.
        """
        return [dict(reading) for _, reading in sorted(self.readings.items())]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def nearest_wet(
    latitudes: np.ndarray, longitudes: np.ndarray, wet: np.ndarray, lat: float, lon: float
) -> tuple[int, int, float]:
    """Indices of the nearest node that is water, and its distance in km.

    Searches every wet node rather than snapping to the nearest node and hoping it floats.
    The two differ exactly when the nearest node is land, which is the case this function
    exists for — and at IBI's 1/36° a point 1 km off Praia do Norte is close enough to the
    coast that the question is real rather than theoretical.

    Pure, so `--check` can drive it with a grid whose answer is known by inspection.
    """
    if not wet.any():
        raise ValueError("the mask marks no water at all; wrong variable or wrong convention")

    grid_lat, grid_lon = np.meshgrid(latitudes, longitudes, indexing="ij")
    phi1, phi2 = math.radians(lat), np.radians(grid_lat)
    dphi = phi2 - phi1
    dlambda = np.radians(grid_lon - lon)
    a = np.sin(dphi / 2) ** 2 + math.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2) ** 2
    distance = 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))

    distance = np.where(wet, distance, np.inf)
    flat = int(np.argmin(distance))
    row, column = divmod(flat, distance.shape[1])
    return row, column, float(distance[row, column])


def local_stamp(moment: dt.datetime) -> str:
    """A UTC instant as the Nazaré local stamp the rest of the system speaks.

    Everything downstream slices a date off the front of this string (`days.group_by_date`),
    so the conversion has to happen once, here, rather than being a thing each reader
    remembers. Grouping raw UTC would put an hour of every summer-time day on the wrong date
    — about 28 days of each Big-Wave Season, per ADR 0008.
    """
    return moment.replace(tzinfo=dt.UTC).astimezone(NAZARE).strftime("%Y-%m-%dT%H:%M")


def combined_swell_height(sw1: float, sw2: float) -> float:
    """The two swell trains as one significant wave height.

    Partition **energies** add and partition heights do not, so this is the root sum of
    squares rather than the sum. Copernicus states the convention explicitly. There is no
    corresponding way to combine two periods — a period threshold is inherently about one
    train — which is why this function has no sibling for `VTM01_*`.
    """
    return math.sqrt(sw1**2 + sw2**2)


def expected_rows_per_day(cadence_hours: int) -> int:
    return 24 // cadence_hours


def is_usable_day(rows: int, cadence_hours: int) -> bool:
    """CONTEXT.md's Usable Day rule, with the denominator taken from the cadence.

    "A day on which an instrument reported for at least three quarters of its hours."
    `backtest.py` reads that as 18 of 24, which is right for an hourly series and wrong for
    WAVERYS: 3-hourly gives 8 rows on a complete day, so a fixed 24 would score every single
    WAVERYS day unusable and the cross-check would silently score nothing.

    A local day that crosses a summer-time boundary genuinely has 23 or 25 hours. The rule
    is left against the nominal day rather than the real one, which makes it a shade lenient
    on the short day once a year; tightening it would mean a Usable Day rule that changes
    definition twice a year, which is worse.
    """
    return rows >= 0.75 * expected_rows_per_day(cadence_hours)


def require_credentials() -> None:
    """Fail early and legibly when Copernicus credentials are absent.

    The toolbox's own failure for this arrives from several frames down and reads as a
    network problem. This is the one obstacle standing between a clean checkout and this
    module working, so it gets a sentence that says what to do.
    """
    if os.environ.get("COPERNICUSMARINE_SERVICE_USERNAME") and os.environ.get(
        "COPERNICUSMARINE_SERVICE_PASSWORD"
    ):
        return

    directory = os.environ.get("COPERNICUSMARINE_CREDENTIALS_DIRECTORY")
    configured = Path(directory) if directory else Path.home() / ".copernicusmarine"
    if (configured / ".copernicusmarine-credentials").exists():
        return

    raise RuntimeError(
        "Copernicus Marine credentials not found. The reanalysis data needs a free account "
        "(the catalogue and the mask files do not). Either set "
        "COPERNICUSMARINE_SERVICE_USERNAME and COPERNICUSMARINE_SERVICE_PASSWORD, or run "
        "`.venv/Scripts/copernicusmarine.exe login` once in a real terminal window — the "
        "prompt cannot be driven from a subprocess. Verify with `login "
        "--check-credentials-valid`."
    )


def mask(product: Product) -> xr.Dataset:
    """The product's own static land/sea mask, downloaded once and cached.

    Anonymous — these two files need no account, which is what let #36 settle the wet-node
    question before anybody had registered one.
    """
    import urllib.request

    path = CACHE / product.mask_file
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".partial")
        urllib.request.urlretrieve(product.mask_url, temporary)  # noqa: S310
        temporary.replace(path)
    return xr.open_dataset(path)


def wet_node(product: Product, lat: float = LATITUDE, lon: float = LONGITUDE) -> Node:
    """The nearest node to the Proxy Target that the product says is water."""
    grid = mask(product)
    depth = grid[product.depth_variable]
    if product.sea_flag is not None:
        wet = np.asarray(grid[product.sea_flag].values) == 1
    else:
        wet = ~np.isnan(np.asarray(depth.values))

    latitudes = np.asarray(grid["latitude"].values)
    longitudes = np.asarray(grid["longitude"].values)
    row, column, distance = nearest_wet(latitudes, longitudes, wet, lat, lon)
    return Node(
        latitude=float(latitudes[row]),
        longitude=float(longitudes[column]),
        depth_m=float(np.asarray(depth.values)[row, column]),
        distance_km=distance,
    )


def fetch(product: Product) -> Path:
    """Download the node's time series, or return the cached copy.

    Cached and skipped on later runs exactly as `hindcast._get` is, so re-running the report
    does not re-download fifteen years of ocean.
    """
    path = CACHE / f"{product.name}.nc"
    if path.exists():
        return path

    require_credentials()
    import copernicusmarine

    node = wet_node(product)
    CACHE.mkdir(parents=True, exist_ok=True)
    copernicusmarine.subset(
        dataset_id=product.dataset_id,
        variables=list(VARIABLES),
        minimum_latitude=node.latitude,
        maximum_latitude=node.latitude,
        minimum_longitude=node.longitude,
        maximum_longitude=node.longitude,
        start_datetime=f"{START}T00:00:00",
        end_datetime=f"{END}T23:00:00",
        coordinates_selection_method="nearest",
        output_directory=str(CACHE),
        output_filename=path.name,
        file_format="netcdf",
        disable_progress_bar=True,
    )
    if not path.exists():
        raise RuntimeError(f"{product.name}: the toolbox reported success but wrote no {path}")
    return path


def read(product: Product) -> Series:
    """The cached download, validated and keyed by UTC hour.

    Suspicious of the file in the same way `hindcast._parse` is suspicious of a response,
    and for the same reason: this project's characteristic failure is data that arrives
    looking plausible and is wrong.
    """
    dataset = xr.open_dataset(fetch(product))

    missing = [v for v in VARIABLES if v not in dataset.data_vars]
    if missing:
        raise ValueError(f"{product.name}: download is missing variables: {missing}")

    wrong = {
        v: dataset[v].attrs.get("units")
        for v in VARIABLES
        if dataset[v].attrs.get("units") != EXPECTED_UNITS[v]
    }
    if wrong:
        raise ValueError(
            f"{product.name}: unexpected units {wrong}; the thresholds these series are "
            "fitted against are named in metres and seconds"
        )

    node = wet_node(product)
    times = np.asarray(dataset["time"].values)
    if times.size == 0:
        raise ValueError(f"{product.name}: download has no time axis")

    columns = {v: np.asarray(dataset[v].values).ravel() for v in VARIABLES}
    readings: dict[str, dict[str, float]] = {}
    for index, stamp in enumerate(times):
        moment = dt.datetime.fromisoformat(str(stamp)[:19])
        values = {v: float(columns[v][index]) for v in VARIABLES}
        if any(math.isnan(value) for value in values.values()):
            continue
        reading: dict[str, float] = dict(values)
        reading["at"] = local_stamp(moment)  # type: ignore[assignment]
        readings[moment.isoformat()] = reading

    if not readings:
        raise ValueError(
            f"{product.name}: every hour was NaN for at least one variable — the node at "
            f"{node.latitude:.4f},{node.longitude:.4f} is not carrying these variables"
        )

    step = (times[1] - times[0]).astype("timedelta64[h]").astype(int) if times.size > 1 else 0
    if step and step != product.cadence_hours:
        raise ValueError(
            f"{product.name}: time axis steps every {step} h, but the Usable Day rule is "
            f"set up for {product.cadence_hours} h; the completeness denominator would be wrong"
        )

    return Series(
        name=product.name,
        node=node,
        cadence_hours=product.cadence_hours,
        readings=readings,
    )


def check() -> int:
    """Self-test the parts that are arithmetic, without the network.

    Analysis scripts are lint-only in CI, so the pure parts carry their own check — the same
    arrangement `gold_days/build.py --check`, `swell.py --check` and `calibrate.py --check`
    use. What is worth checking here is the node search, the timezone conversion and the two
    rules that change with cadence, because each is easy to write plausibly and wrongly.
    """
    failures: list[str] = []

    def expect(label: str, got: object, want: object) -> None:
        if got != want:
            failures.append(f"{label}: expected {want!r}, got {got!r}")

    # The nearest node is land, so the answer is the nearest WET one and not the nearest.
    # Written as a snap-to-nearest this returns (1, 1) and every reading downstream is a
    # fill value.
    latitudes = np.array([39.0, 39.5, 40.0])
    longitudes = np.array([-10.0, -9.5, -9.0])
    wet = np.array(
        [
            [True, True, True],
            [True, False, True],  # the node nearest 39.5,-9.5 is dry
            [True, True, True],
        ]
    )
    row, column, _ = nearest_wet(latitudes, longitudes, wet, 39.5, -9.5)
    expect("nearest wet node skips the dry one", (row, column), (1, 0))

    all_wet = np.ones((3, 3), dtype=bool)
    row, column, distance = nearest_wet(latitudes, longitudes, all_wet, 39.5, -9.5)
    expect("nearest wet node takes the nearest when it is wet", (row, column), (1, 1))
    expect("a node on top of the target is 0 km away", round(distance, 6), 0.0)

    try:
        nearest_wet(latitudes, longitudes, np.zeros((3, 3), dtype=bool), 39.5, -9.5)
    except ValueError:
        pass
    else:
        failures.append("nearest_wet: expected a ValueError when the mask marks no water")

    # Winter is UTC+0 in Lisbon and summer is UTC+1. An hour that converts as if the offset
    # were fixed lands on the wrong local day twice a year, which is ADR 0008's whole point.
    expect(
        "a winter hour is UTC+0 local",
        local_stamp(dt.datetime(2012, 1, 15, 23, 0)),
        "2012-01-15T23:00",
    )
    expect(
        "a summer hour is UTC+1 local",
        local_stamp(dt.datetime(2012, 7, 15, 23, 0)),
        "2012-07-16T00:00",
    )
    # Both sides of the autumn fold render as the same local stamp. This is why `Series`
    # keys on UTC: keyed on the local string, one of these two hours would vanish.
    expect(
        "the hour before the autumn fold",
        local_stamp(dt.datetime(2012, 10, 28, 0, 0)),
        "2012-10-28T01:00",
    )
    expect(
        "the hour after the autumn fold",
        local_stamp(dt.datetime(2012, 10, 28, 1, 0)),
        "2012-10-28T01:00",
    )

    # Energies add, heights do not. Written as a plain sum, two 3 m trains become 6 m.
    expect("two equal trains combine by energy", round(combined_swell_height(3.0, 3.0), 4), 4.2426)
    expect("an absent second train changes nothing", combined_swell_height(4.0, 0.0), 4.0)

    # The completeness denominator follows the cadence. Fixed at 24, every complete WAVERYS
    # day (8 rows) scores unusable and the cross-check quietly measures nothing.
    expect("hourly needs 18 of 24", expected_rows_per_day(1), 24)
    expect("3-hourly needs 6 of 8", expected_rows_per_day(3), 8)
    expect("a complete 3-hourly day is usable", is_usable_day(8, 3), True)
    expect("a two-thirds 3-hourly day is not", is_usable_day(5, 3), False)
    expect("a complete hourly day is usable", is_usable_day(24, 1), True)
    expect("a complete 3-hourly day is not judged on 24", is_usable_day(8, 1), False)

    for failure in failures:
        print(f"FAIL {failure}")
    print("reanalysis.py --check: " + ("FAILED" if failures else "all checks passed"))
    return 1 if failures else 0


def main() -> int:
    if "--check" in sys.argv:
        return check()

    for product in PRODUCTS:
        series = read(product)
        node = series.node
        first = min(series.readings)
        last = max(series.readings)
        print(
            f"{series.name:8s} {len(series):7d} hours  {first[:10]}..{last[:10]}  "
            f"every {series.cadence_hours} h\n"
            f"         node {node.latitude:.4f},{node.longitude:.4f}  "
            f"{node.distance_km:.2f} km from the Proxy Target, {node.depth_m:.1f} m deep"
        )
    print(f"\nCached under {CACHE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

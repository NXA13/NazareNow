"""Does Copernicus WAVERYS carry a real Swell partition, and does it reach our Gold Days?

Ticket #36. #11 could only score the Heuristic Baseline against 9 of the 38 Gold Days,
because the free Hindcast that reaches back to 2011 — Open-Meteo's `era5_ocean` — carries
the **Combined Sea** only, and reconstructing **Swell** from it recovers 41% of threshold
crossings at the shipped 13 s bar. WAVERYS is a wave *reanalysis*, so if it partitions the
spectrum the way the operational models do, the pre-2022 record stops being reconstructed
and starts being read.

This script asks the Copernicus Marine catalogue rather than assuming. It prints, for each
candidate reanalysis:

  * every variable and its CF standard name, so a Swell partition can be identified by
    `sea_surface_primary_swell_wave_*` rather than by a hopeful reading of a short name;
  * the grid, and the nearest node to the Proxy Target with the distance in km;
  * the time axis, and how many of the 38 Gold Days fall inside it.

It reads catalogue **metadata only** and downloads no data, so it needs no Copernicus
credentials — verified by pointing the toolbox at an empty credentials directory:

    COPERNICUSMARINE_CREDENTIALS_DIRECTORY=$(mktemp -d) \
        .venv/Scripts/python.exe analysis/waverys/verify_waverys.py

Like the rest of `analysis/`, CI lints it but does not run it. Expect it to take a couple of
minutes: the toolbox fetches the product's STAC metadata on every call and does not cache it
between processes.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path
from typing import Any

import copernicusmarine

# Monican02's position — the Proxy Target, and the point the Pipeline Run requests from
# Open-Meteo. Kept in step with backend/src/nazarenow/sources/open_meteo.py.
LATITUDE = 39.56
LONGITUDE = -9.21

GOLD_DAYS = Path(__file__).resolve().parents[1] / "gold_days" / "gold_days.jsonl"

# The reanalysis this ticket asks about, and the two products it has to be judged against:
# the regional reanalysis covering Iberia at 1/36°, and the operational global forecast the
# live pipeline's Swell numbers ultimately come from.
PRODUCTS = {
    "GLOBAL_MULTIYEAR_WAV_001_032": "cmems_mod_glo_wav_my_0.2deg_PT3H-i",
    "IBI_MULTIYEAR_WAV_005_006": "cmems_mod_ibi_wav_my_0.027deg_PT1H-i",
    "GLOBAL_ANALYSISFORECAST_WAV_001_027": "cmems_mod_glo_wav_anfc_0.083deg_PT3H-i",
}

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    y = math.sin(dlambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
    return math.degrees(math.atan2(y, x)) % 360


def compass(degrees: float) -> str:
    points = [
        "N",
        "NNE",
        "NE",
        "ENE",
        "E",
        "ESE",
        "SE",
        "SSE",
        "S",
        "SSW",
        "SW",
        "WSW",
        "W",
        "WNW",
        "NW",
        "NNW",
    ]
    return points[round(degrees / 22.5) % 16]


def snap(value: float, minimum: float, step: float) -> float:
    """The grid node nearest `value` on an axis running from `minimum` in `step`s."""
    return minimum + round((value - minimum) / step) * step


def instant(milliseconds: float) -> dt.datetime:
    return dt.datetime.fromtimestamp(milliseconds / 1000, dt.UTC)


def coordinates(variable: Any) -> dict[str, Any]:
    return {c.coordinate_id: c for c in variable.coordinates}


def time_series_service(product: Any, dataset_id: str) -> Any:
    """The ARCO time-series service of the newest version of `dataset_id`.

    The catalogue exposes the same variables through several services; the ARCO ones carry
    the coordinate extents, which is the half of this that the product page does not state
    precisely enough to snap a grid point against.
    """
    for dataset in product.datasets:
        if dataset.dataset_id != dataset_id:
            continue
        for version in dataset.versions:
            for part in version.parts:
                for service in part.services:
                    if str(getattr(service.service_name, "value", service.service_name)) == (
                        "arco-time-series"
                    ):
                        return version.label, service
    raise LookupError(f"no arco-time-series service for {dataset_id}")


def gold_days() -> list[dt.date]:
    with GOLD_DAYS.open(encoding="utf-8") as handle:
        return sorted(dt.date.fromisoformat(json.loads(line)["date"]) for line in handle)


def report(product_id: str, dataset_id: str, days: list[dt.date]) -> None:
    catalogue = copernicusmarine.describe(product_id=product_id)
    product = catalogue.products[0]
    label, service = time_series_service(product, dataset_id)

    print(f"\n{'=' * 96}\n{product_id}  —  {product.title}\n{dataset_id}  (version {label})\n")

    swell = [v for v in service.variables if "swell" in (v.standard_name or "")]
    print(f"{len(service.variables)} variables, {len(swell)} of them swell partitions:")
    for variable in sorted(service.variables, key=lambda v: v.short_name):
        mark = "*" if variable in swell else " "
        units = variable.units or ""
        print(f"  {mark} {variable.short_name:<12} {units:<8} {variable.standard_name}")

    axes = coordinates(service.variables[0])
    lat, lon = axes["latitude"], axes["longitude"]
    node_lat = snap(LATITUDE, lat.minimum_value, lat.step)
    node_lon = snap(LONGITUDE, lon.minimum_value, lon.step)
    distance = haversine_km(LATITUDE, LONGITUDE, node_lat, node_lon)
    heading = bearing_deg(LATITUDE, LONGITUDE, node_lat, node_lon)
    print(
        f"\n  grid            {lat.step:.6f}° lat x {lon.step:.6f}° lon"
        f"\n  nearest node    {node_lat:.4f}, {node_lon:.4f}"
        f"\n  from the Proxy Target ({LATITUDE}, {LONGITUDE}): "
        f"{distance:.2f} km {compass(heading)}"
    )

    time = axes["time"]
    start, end = instant(time.minimum_value), instant(time.maximum_value)
    inside = [d for d in days if start.date() <= d <= end.date()]
    print(
        f"\n  time            {start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M} UTC, "
        f"every {time.step / 3_600_000:.0f} h"
        f"\n  Gold Days       {len(inside)} of {len(days)} inside coverage"
    )
    missing = [d for d in days if d not in inside]
    if missing:
        print(f"  outside         {', '.join(d.isoformat() for d in missing)}")


def main() -> int:
    days = gold_days()
    print(f"{len(days)} Gold Days, {days[0]} to {days[-1]}")
    for product_id, dataset_id in PRODUCTS.items():
        report(product_id, dataset_id, days)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""The read-only HTTP API.

Per ADR 0005 this layer only ever reads. It evaluates no model and contacts no
third-party service — a Pipeline Run does that on a schedule and writes its results to
the store, which this API serves. Nothing here should ever grow a network call outward.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from nazarenow.store import Store, StoreUnavailable

app = FastAPI(
    title="NazareNow",
    description="Forecasts when Praia do Norte will produce giant waves.",
    version="0.1.0",
)

# Must match the port pinned in frontend/vite.config.ts. If the two drift apart the app
# fails only in a browser, with a CORS error neither test suite can see, because both
# seams mock the boundary between them. A test asserts this list to stop that recurring.
# Production origins get added when there is somewhere to deploy to.
DEVELOPMENT_ORIGINS = [
    "http://localhost:5273",
    "http://127.0.0.1:5273",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=DEVELOPMENT_ORIGINS,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.exception_handler(StoreUnavailable)
def store_unavailable(_request: Request, error: StoreUnavailable) -> JSONResponse:
    """Turn a store fault into a described 500 wherever it is raised.

    The dependency catches the expected cases, but an unhandled exception surfaces
    outside CORSMiddleware — so a browser sees an opaque CORS failure instead of the
    error. This keeps that from happening for any path not anticipated.
    """
    return JSONResponse(status_code=500, content={"detail": f"Store unavailable: {error}"})


@lru_cache
def default_store() -> Store:
    """The store this process serves. Opened read-only: creating a database here would
    turn a misconfigured path into an empty one, and the API would then report no
    conditions — a configuration fault disguised as an absence of data."""
    return Store(os.environ.get("NAZARENOW_DB") or None, create=False)


def get_store() -> Store:
    """Injected so tests can substitute a temporary store.

    The store is opened here, in the dependency, so this is also where a misconfigured
    path surfaces. An earlier version caught StoreUnavailable inside the endpoint body,
    which could never fire — dependencies resolve first — and a missing database
    produced a bare 500 with no explanation of what was wrong.
    """
    try:
        return default_store()
    except StoreUnavailable as error:
        raise HTTPException(status_code=500, detail=f"Store unavailable: {error}") from error


class Reading(BaseModel):
    """One measured quantity, carrying the unit the provider reported it in.

    The unit travels with the value rather than being assumed by the interface. Every
    displayed number can then state its unit truthfully, and a provider switching from
    km/h to m/s becomes visible instead of silently rescaling the page.
    """

    value: float
    unit: str


class CurrentConditions(BaseModel):
    observed_at: str
    """The older of the two providers' observation times — the whole picture is at
    least this old."""

    fetched_at: str
    latitude: float
    longitude: float

    swell_height: Reading
    swell_period: Reading
    swell_direction: Reading
    significant_wave_height: Reading
    wave_period: Reading
    wave_direction: Reading
    water_temperature: Reading
    air_temperature: Reading
    wind_speed: Reading
    wind_direction: Reading


class ForecastHour(BaseModel):
    at: str
    swell_height: Reading
    swell_period: Reading
    swell_direction: Reading
    significant_wave_height: Reading
    wave_period: Reading
    wave_direction: Reading
    water_temperature: Reading
    air_temperature: Reading
    wind_speed: Reading
    wind_direction: Reading


class ForecastDay(BaseModel):
    date: str

    peak_swell_height: Reading
    """The day's largest swell, which is what decides whether it is worth travelling for."""

    peak_swell_period: Reading
    dominant_swell_direction: Reading
    """Height, period and direction are summarised separately and never collapsed into one
    figure: a big short-period sea and a long-period groundswell of the same height are
    entirely different days."""

    hours: list[ForecastHour]


class Forecast(BaseModel):
    fetched_at: str
    days: list[ForecastDay]


def summarise(date: str, hours: list[dict[str, Any]]) -> ForecastDay:
    """Reduce a day's hours to the figures a user scans the overview for."""
    peak = max(hours, key=lambda hour: hour["readings"]["swell_height"]["value"])
    return ForecastDay(
        date=date,
        peak_swell_height=Reading(**peak["readings"]["swell_height"]),
        peak_swell_period=Reading(**peak["readings"]["swell_period"]),
        dominant_swell_direction=Reading(**peak["readings"]["swell_direction"]),
        hours=[ForecastHour(at=hour["at"], **hour["readings"]) for hour in hours],
    )


@app.get("/api/conditions/forecast")
def forecast(store: Annotated[Store, Depends(get_store)]) -> Forecast:
    """Every forecast hour a Pipeline Run stored, grouped by day.

    Quiet days are returned like any other. Omitting them would leave gaps a reader
    cannot distinguish from missing data, and a flat spell is a real answer to "when
    should I go".
    """
    hours = store.forecast()
    if not hours:
        raise HTTPException(
            status_code=503,
            detail="No forecast has been ingested yet. Run the pipeline first.",
        )

    by_date: dict[str, list[dict[str, Any]]] = {}
    for hour in hours:
        by_date.setdefault(hour["at"][:10], []).append(hour)

    return Forecast(
        fetched_at=hours[0]["fetched_at"],
        days=[summarise(date, by_date[date]) for date in sorted(by_date)],
    )


@app.get("/api/conditions/current")
def current_conditions(store: Annotated[Store, Depends(get_store)]) -> CurrentConditions:
    """The most recent Offshore Conditions a Pipeline Run stored.

    Returns 503 when the store is empty rather than inventing defaults. Zeros would
    render as a flat, calm ocean, which is a plausible-looking lie; an explicit failure
    is not.
    """
    latest: dict[str, Any] | None = store.latest_conditions()
    if latest is None:
        raise HTTPException(
            status_code=503,
            detail="No conditions have been ingested yet. Run the pipeline first.",
        )

    return CurrentConditions(
        observed_at=latest["observed_at"],
        fetched_at=latest["fetched_at"],
        latitude=latest["latitude"],
        longitude=latest["longitude"],
        **latest["readings"],
    )

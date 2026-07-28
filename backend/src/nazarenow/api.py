"""The read-only HTTP API.

Per ADR 0005 this layer only ever reads. It evaluates no model and contacts no
third-party service — a Pipeline Run does that on a schedule and writes its results to
the store, which this API serves. Nothing here should ever grow a network call outward.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
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

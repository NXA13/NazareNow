"""The read-only HTTP API.

Per ADR 0005 this layer only ever reads. It evaluates no model and contacts no
third-party service, and it derives no calls — a Pipeline Run does all of that on a
schedule and writes its results to the store, which this API serves. Deriving calls
here was an ADR 0005 breach that also destroyed the retained-prediction record.
Nothing here should ever grow a network call outward.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from nazarenow.days import group_by_date
from nazarenow.decision import Status
from nazarenow.schedule import STALE_AFTER_SECONDS
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


def utc_now() -> datetime:
    """The wall clock, isolated so tests can move it.

    Deliberately the only clock reading in this layer. Lead Time is fixed when a call is
    issued and stored with it, precisely so a stale forecast cannot present an elapsed Go
    Call as fresh advice — nothing about a *prediction* may depend on when it is read.
    Freshness is the exception that proves it: how old the data is is a fact about now.
    """
    return datetime.now(UTC)


def is_stale(fetched_at: str) -> bool:
    """Whether results fetched at this moment are too old to present as current.

    ADR 0005 promises the site "stays up and honest — showing stale results with a
    timestamp" when the provider is unreachable. A timestamp alone is not honest enough:
    "fetched 09:04" reads as current to anyone not doing arithmetic, and this system exists
    to make people act. So the judgement is made here and stated outright.

    An unparseable timestamp counts as stale. The alternative is reporting data as current
    because we could not work out how old it was.
    """
    try:
        fetched = datetime.fromisoformat(fetched_at)
    except ValueError:
        return True
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=UTC)
    return (utc_now() - fetched).total_seconds() > STALE_AFTER_SECONDS


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

    stale: bool
    """True when no Pipeline Run has succeeded for two whole cycles. The interface says so
    prominently rather than leaving a reader to subtract timestamps."""

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


class DayCall(BaseModel):
    status: Status
    lead_time_days: int
    """Days from the first day the forecast covers, fixed when the call was issued rather
    than recomputed against the wall clock. A Go Call is only worth anything if it arrives
    while flights are still bookable, so the number travels with the call."""

    reasons: list[str]
    predicted_significant_wave_height: Reading


class ForecastDay(BaseModel):
    date: str

    call: DayCall | None
    """None when no Pipeline Run has yet made a call about this day.

    Distinct from a call whose status is `none`, which is a judgement — the conditions
    were examined and this is not a day to travel for. Absent means nothing has judged it.
    Collapsing the two would let a gap in the record read as an answer, and dropping the
    day entirely — which this endpoint used to do — left a hole a reader cannot tell from
    missing data."""

    peak_swell_height: Reading
    """The day's largest swell, shown so a reader can scan the range at a glance.

    It decides nothing. The rule of thumb is applied to **Significant Wave Height**, which
    travels on the call as `predicted_significant_wave_height`, and `CONTEXT.md` lists
    "swell height" among that term's avoided synonyms precisely because they are different
    variables measuring different things. Saying this field was "what decides whether it is
    worth travelling for" put the conflation the model was corrected for back into the
    interface's own prose, one field above the quantity that actually decides."""

    swell_period_at_peak: Reading
    swell_direction_at_peak: Reading
    """The period and direction *of the largest hour*, not the day's maximum period.

    Named for what they hold. Calling them peak period and dominant direction was a lie:
    they were read from the peak-height hour, so a day whose longest period arrived at a
    quieter hour reported the wrong number — on the two fields a travel decision most
    turns on."""

    longest_swell_period: Reading
    """The day's actual maximum period, which is the groundswell signal a big-wave
    forecast lives on and can fall at a different hour from the peak height."""

    hours: list[ForecastHour]


class Forecast(BaseModel):
    fetched_at: str

    stale: bool
    """As on CurrentConditions. Both endpoints serve the same Pipeline Run, so a reader
    seeing one of them must not have to consult the other to learn the data is old."""

    amplification_model: str | None
    """None when the store holds no calls, so nothing has named a model. The interface
    says so rather than guessing at one."""

    calibrated: bool
    """False while thresholds are the surf community's rule of thumb rather than values
    fitted to Gold Days. Ticket #12 changes that; until then the interface must not imply
    a precision the numbers do not have."""

    days: list[ForecastDay]


def summarise(date: str, hours: list[dict[str, Any]], call: dict[str, Any] | None) -> ForecastDay:
    """Reduce a day's hours to the figures a user scans the overview for, plus its call.

    The call is read from the store, never computed. ADR 0005 makes this layer a reader,
    and CONTEXT.md makes a Pipeline Run the only thing that runs a model. A day the store
    has no call for is returned with none — synthesising one here would be this layer
    making a judgement, which is the breach the calls were moved to the pipeline to end.
    """
    peak = max(hours, key=lambda hour: hour["readings"]["swell_height"]["value"])
    longest = max(hours, key=lambda hour: hour["readings"]["swell_period"]["value"])

    return ForecastDay(
        date=date,
        call=None
        if call is None
        else DayCall(
            status=Status(call["status"]),
            lead_time_days=call["lead_time_days"],
            reasons=call["reasons"],
            predicted_significant_wave_height=Reading(
                value=call["predicted_significant_wave_height"], unit=call["unit"]
            ),
        ),
        peak_swell_height=Reading(**peak["readings"]["swell_height"]),
        swell_period_at_peak=Reading(**peak["readings"]["swell_period"]),
        swell_direction_at_peak=Reading(**peak["readings"]["swell_direction"]),
        longest_swell_period=Reading(**longest["readings"]["swell_period"]),
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

    by_date = group_by_date(hours)
    stored = store.calls()

    # A forecast with no calls behind it is still served. ADR 0005 asks that the site stay
    # up and honest, and the days, their hours and their heights are all real; failing the
    # whole endpoint because the call record is empty threw away everything ticket #5
    # delivered over something ticket #6 added.
    #
    # The store answers which call is newest. Doing it here meant sorting by `issued_at`,
    # which the store's own docstring rules out because two runs inside one second tie.
    newest = store.latest_call()

    return Forecast(
        fetched_at=hours[0]["fetched_at"],
        stale=is_stale(hours[0]["fetched_at"]),
        amplification_model=None if newest is None else newest["amplification_model"],
        # Nothing to say the thresholds were fitted, so the interface must not imply it.
        calibrated=newest is not None and newest["calibrated"],
        days=[summarise(day, by_date[day], stored.get(day)) for day in sorted(by_date)],
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
        stale=is_stale(latest["fetched_at"]),
        latitude=latest["latitude"],
        longitude=latest["longitude"],
        **latest["readings"],
    )

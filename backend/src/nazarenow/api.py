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

from nazarenow.cycle import STALE_AFTER_HOURS, STALE_AFTER_SECONDS
from nazarenow.days import group_by_date
from nazarenow.decision import Agreement, Status
from nazarenow.spread import BEARINGS, ORGANISATIONS, is_degraded
from nazarenow.store import Store, StoreUnavailable
from nazarenow.track_record import Band, Panel, Tier, TrackRecord, TrackRecordUnusable
from nazarenow.track_record import load as load_track_record

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


@app.exception_handler(TrackRecordUnusable)
def track_record_unusable(_request: Request, error: TrackRecordUnusable) -> JSONResponse:
    """Turn an unusable track record into a described 500, for the reason above.

    Same shape as the store handler and for the same reason: an unhandled exception
    surfaces outside CORSMiddleware, so a browser sees an opaque CORS failure rather than
    the error. The dependency catches the expected case; this covers the rest.
    """
    return JSONResponse(status_code=500, content={"detail": f"Track record unusable: {error}"})


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


class HeightRange(BaseModel):
    """A span between two heights, carrying its unit for the reason `Reading` does.

    Its own model rather than two bare floats on the call, so the pair cannot be rendered
    half-present: a low with no high describes a range with one end, and the interface would
    have no honest thing to draw for it.
    """

    low: float
    high: float
    unit: str


class CurrentConditions(BaseModel):
    observed_at: str
    """The older of the two providers' observation times — the whole picture is at
    least this old."""

    fetched_at: str

    stale: bool
    """True when no Pipeline Run has succeeded for two whole cycles. The interface says so
    prominently rather than leaving a reader to subtract timestamps."""

    stale_after_hours: int
    """How old results must be before `stale` turns true.

    Sent so the interface can state the figure without knowing it. It was written into the
    page as the literal "at least six hours" while a docstring claimed the number was
    single-sourced — so changing the cadence would have left the page asserting a duration
    that was no longer true, with no test to notice."""

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


class EarlierCall(BaseModel):
    """One superseded call about a date, cut down to what "has this shifted?" needs.

    Deliberately not a whole `DayCall`. The reasons, the calibration provenance and the two
    withholding flags all describe a judgement that is no longer the system's, and sending
    them would invite an interface to render a stale explanation beside a current one. What a
    reader is comparing is the number, the range and the tier.
    """

    issued_at: str
    lead_time_days: int
    """How far out this date was when that run spoke, which is what makes the series
    readable: a range narrowing from ten days out to three is the forecast doing its job,
    and the same narrowing at a fixed Lead Time would be something else entirely."""

    status: Status
    predicted_significant_wave_height: Reading
    plausible_range: HeightRange | None


class DayCall(BaseModel):
    status: Status
    lead_time_days: int
    """Days from the first day the forecast covers, fixed when the call was issued rather
    than recomputed against the wall clock. A Go Call is only worth anything if it arrives
    while flights are still bookable, so the number travels with the call."""

    reasons: list[str]
    predicted_significant_wave_height: Reading

    go_call_withheld: bool | None
    """Whether the models refused a Go Call this day's conditions otherwise supported (#8).

    The interface cannot work this out for itself, and the reason is the point of sending it:
    a day whose own swell period sits below the Go Call bar has every organisation below it
    too, so it reports `divided` while the models decided nothing. Two Watch days that look
    identical here are a swell the forecasters have not settled on and a swell that was never
    big enough — and only the Decision Model saw the conditions beside the verdict.

    Null for a call issued before the gate existed."""

    model_agreement: Agreement | None
    """What the independent wave models said about the hour this call rests on (#8).

    A property of the call rather than of the date, and it cannot be read off `model_spread`
    below: that is the date's *median* hour and a call is decided on its best matching hour.
    Sent so the interface can say why a Watch is a Watch without re-deriving a rule it does
    not own — which is the same reason `providers_expected` and `bearing` are sent.

    Null only for a call issued before the Decision Model consulted the models at all. Those
    calls were decided on this system's own forecast alone, and the interface must not present
    them as agreed."""

    plausible_range: HeightRange | None
    """Where the Predictive Distribution puts this date, 5th to 95th percentile (#15).

    The ticket's fourth criterion, and the reason it exists: "6.1 metres, 78% confident" is
    not something a person can act on, and "most likely 6.1 m, plausibly 5.2 to 7.0" is. The
    percentage was never the useful half.

    Null for a call decided without a distribution, which today means one issued before the
    pipeline built them."""

    height_bar_probability: float | None
    """How much of that distribution clears the calibrated height bar.

    #15's fifth criterion asked for the probability of reaching Gold Day *conditions*. This is
    the height condition alone, which is the part that can be measured — see
    `PredictiveDistribution.height_bar_probability` and ADR 0004 for why the other three are
    not available (#66). The field name and the interface copy both name the height condition,
    so a client cannot read the whole set into a number that prices one of them.

    A share between 0 and 1, not a percentage, so the interface owns the rounding — the
    difference between 0.94 and "94%" is presentation, and the backend guessing at it once
    left a threshold restated in two places."""

    uncertainty_measured: bool | None
    """Whether a measured Forecast Error Profile covered this call's Lead Time (#15's sixth).

    False past the archive's seven days. The width out there is still honest — it keeps
    growing at the rate the archive measured, and the centre holds at the last correction it
    measured — but nothing was measured about *that* Lead Time, and the interface has to be
    able to be visibly more cautious rather than presenting an extrapolation as evidence.

    Sent as a flag rather than left for the interface to infer from `lead_time_days`, because
    inferring it means hardcoding the archive's depth in a second place. The archive grows
    every season; the page must not carry its own copy of how deep it currently is."""

    go_call_withheld_for_uncertainty: bool | None
    """Whether the width, rather than the models, refused a Go Call (#15).

    Deliberately separate from `go_call_withheld` above. Both end in a Watch, and a reader
    deserves to know which: the forecasters disagreeing about a swell is a different fact
    about the world from one forecast being too uncertain to book on. Collapsing them would
    make the same badge mean two things.

    Null for a call issued before the distribution could refuse anything."""

    previous_runs: list[EarlierCall]
    """What earlier Pipeline Runs said about this same date, oldest first (#15's eighth).

    The current call is *not* in this list — it is the object these hang off. Empty on the
    first run that mentions a date, which is the honest answer rather than a series of one.

    Sent rather than left to the interface to accumulate, because the interface has no
    memory: it is a page a traveller opens once every few days, and the succession of runs it
    would need to have watched happened while nobody was looking. The store keeps every call
    ever made (ADR 0005) precisely so this can be answered from the record.

    Bounded to the last few runs. A date approached over a fortnight of three-hourly runs
    accumulates more than a hundred calls, and what a reader is asking is "has this been
    growing or fading", which the recent ones answer."""


class DaySpread(BaseModel):
    """How far apart the independent wave models are on one variable for one date.

    ADR 0003 makes this the system's uncertainty estimate, and #8 asks for it in terms a
    reader can interpret rather than as a bare number — so the two opinions it was measured
    between travel with the gap. "The models put Thursday between 3.1 m and 4.5 m" is
    actionable in a way that "1.4" is not.

    **An upper bound on disagreement, not a calibrated uncertainty.** The members publish on
    different cycles and their run ages cannot be read from the provider; #8 measured that
    this accounts for roughly 6% of the spread at one day of Lead Time and up to 29% at six.
    It is left uncorrected because it has a direction — sampling two models at different run
    ages can make them look more different than they are but cannot hide genuine agreement —
    so the error always runs toward caution. The interface must not present it as a
    calibrated figure, and this docstring is the reason the wording downstream is careful.
    """

    unit: str

    spread: float | None
    """The distance between the furthest-apart organisations, or None when fewer than two
    reported. Null rather than zero: a zero here is indistinguishable from perfect agreement
    and would read as certainty at exactly the moment the system knows least."""

    lowest: float | None
    highest: float | None
    """The two opinions the spread was measured between. Null exactly when `spread` is.

    For swell direction these are the arc's start and end running clockwise, so across north
    `highest` is the smaller number — 355° to 5° names the correct 10° arc, and reading them
    as a plain minimum and maximum would name the wrong 350° one."""

    providers: list[str]
    """The organisations that contributed, not the models. EWAM and GWAM are both DWD and
    the two GFS Wave resolutions are both NCEP; counting five would make the ensemble look
    nearly twice as corroborated as it is."""

    degraded: bool
    """Whether fewer than the full roster of organisations answered. A spread from two is not
    comparable with one from three, and ADR 0003 requires that degradation to be visible."""

    providers_expected: int
    """How many organisations a full read would have heard from.

    Sent rather than left for the interface to know, so "two of three" is the backend's roster
    said once. A second copy over there is a number that stays at three the day a fourth
    organisation joins, and it would be wrong in the one direction that matters: printing
    "3 of 3" beside a degraded flag reads as a full read that is somehow still degraded."""

    bearing: bool
    """Whether `lowest` and `highest` are compass points rather than points on a line.

    Named here for the same reason `spread.BEARINGS` names them rather than inferring from the
    unit: this decides arithmetic, and the unit is the provider's own string. An interface
    sniffing for a degree sign is one provider spelling change away from rendering an arc as
    an interval, which across north names the wrong three-quarters of the compass."""

    hours_measured: int
    hours_total: int
    """How many of the date's forecast hours carried a measurable spread, out of how many it
    has. A date resting on two of its twenty-four hours is a weaker claim than one measured
    throughout, and the figure alone cannot say which."""


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

    model_spread: dict[str, DaySpread]
    """Model Spread for this date, keyed by the reading it is measured on.

    Always carries every variable Model Spread is defined on, with nulls where nothing could
    be measured, rather than omitting the ones that failed. An absent key would be read as
    agreement by anything scanning it — which is the inversion this whole measurement exists
    to prevent — and the far end of every forecast is exactly where members stop answering.

    Empty only for a date stored before #8, which genuinely has no Model Spread behind it."""

    hours: list[ForecastHour]


class Calibration(BaseModel):
    """The provenance of the thresholds a call was decided against.

    Mirrors `thresholds.Calibration`, restated here because this is the published shape of
    the API and it should not change silently when an internal dataclass does.
    """

    fitted_on: str
    validated_on: str
    gold_days_fitted: int
    gold_days_validated: int
    gold_days_total: int
    method: str
    source: str
    fitted_at: str


class Forecast(BaseModel):
    fetched_at: str

    stale: bool
    """As on CurrentConditions. Both endpoints serve the same Pipeline Run, so a reader
    seeing one of them must not have to consult the other to learn the data is old."""

    stale_after_hours: int

    amplification_model: str | None
    """None when the store holds no calls, so nothing has named a model. The interface
    says so rather than guessing at one."""

    calibrated: bool
    """Whether the thresholds behind these calls were fitted to Gold Days (#12) or are the
    surf community's rule of thumb. Read from the stored call, not from today's threshold
    file, so a call made before the fit keeps saying so."""

    calibration: Calibration | None
    """What the fit rests on, or None for calls decided before there was one.

    Present so the interface can state the calibration's limits in the same breath as it
    drops the uncalibrated warning. Nine Gold Days is a thin basis and the user is told the
    number rather than left to infer confidence from the absence of a caveat — which is
    what removing the warning and adding nothing would have done."""

    days: list[ForecastDay]


def summarise_spread(stored: dict[str, dict[str, Any]]) -> dict[str, DaySpread]:
    """A date's stored Model Spread rows, keyed by the reading each is measured on.

    The keys are the store's own, which are the names every other reading on this endpoint
    already uses — the Pipeline Run translates the provider's spelling once, on arrival, so
    nothing on the read path has to.

    `degraded` is derived here rather than stored, from the organisations the row records.
    Storing it would let the flag and the list it describes disagree after a roster change —
    and a row saying "not degraded" beside two organisations out of three is worse than no
    flag at all.

    `providers_expected` and `bearing` are sent for the same reason in the other direction:
    both are facts about the roster and the variable that this layer already knows, and an
    interface re-deriving either — by counting to three itself, or by sniffing the unit for a
    degree sign — is a second copy that drifts silently when the roster or the provider's
    spelling changes.
    """
    return {
        variable: DaySpread(
            unit=row["unit"],
            spread=row["value"],
            lowest=row["lowest"],
            highest=row["highest"],
            providers=row["providers"],
            degraded=is_degraded(row["providers"]),
            providers_expected=len(ORGANISATIONS),
            bearing=variable in BEARINGS,
            hours_measured=row["hours_measured"],
            hours_total=row["hours_total"],
        )
        for variable, row in stored.items()
    }


def earlier_calls(previous: list[dict[str, Any]]) -> list[EarlierCall]:
    """The superseded calls about a date, newest excluded, oldest first.

    The store hands back the recent window including the call that is current; that one is
    the object these hang off, so sending it twice would let an interface draw a date as
    having shifted from itself.
    """
    return [
        EarlierCall(
            issued_at=call["issued_at"],
            lead_time_days=call["lead_time_days"],
            status=Status(call["status"]),
            predicted_significant_wave_height=Reading(
                value=call["predicted_significant_wave_height"], unit=call["unit"]
            ),
            plausible_range=(
                None
                if call["plausible_range_m"] is None
                else HeightRange(
                    low=call["plausible_range_m"][0],
                    high=call["plausible_range_m"][1],
                    unit=call["unit"],
                )
            ),
        )
        for call in previous[:-1]
    ]


def summarise(
    date: str,
    hours: list[dict[str, Any]],
    call: dict[str, Any] | None,
    spread: dict[str, dict[str, Any]],
    previous: list[dict[str, Any]] | None = None,
) -> ForecastDay:
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
            model_agreement=(
                None if call["model_agreement"] is None else Agreement(call["model_agreement"])
            ),
            go_call_withheld=call["go_call_withheld"],
            plausible_range=(
                None
                if call["plausible_range_m"] is None
                else HeightRange(
                    low=call["plausible_range_m"][0],
                    high=call["plausible_range_m"][1],
                    # The distribution is built in the unit the call is reported in, and
                    # sourced from the call rather than written as "m" so the two cannot
                    # disagree about what the numbers beside them mean.
                    unit=call["unit"],
                )
            ),
            height_bar_probability=call["height_bar_probability"],
            uncertainty_measured=call["uncertainty_measured"],
            go_call_withheld_for_uncertainty=call["go_call_withheld_for_uncertainty"],
            previous_runs=earlier_calls(previous or []),
        ),
        peak_swell_height=Reading(**peak["readings"]["swell_height"]),
        swell_period_at_peak=Reading(**peak["readings"]["swell_period"]),
        swell_direction_at_peak=Reading(**peak["readings"]["swell_direction"]),
        longest_swell_period=Reading(**longest["readings"]["swell_period"]),
        model_spread=summarise_spread(spread),
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
    disagreement = store.spreads()
    # The succession of runs behind each date (#15's eighth criterion). Read once for every
    # date rather than per day, so a fortnight of forecast is one query rather than fourteen —
    # and scoped to this forecast's own dates, so the query's cost tracks the answer rather
    # than the age of an append-only table (#67).
    succession = store.recent_calls(by_date.keys())

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
        stale_after_hours=STALE_AFTER_HOURS,
        amplification_model=None if newest is None else newest["amplification_model"],
        # Both read off the newest stored call rather than off today's threshold file, so a
        # recalibration cannot retroactively describe calls it did not decide.
        calibrated=newest is not None and newest["calibrated"],
        calibration=None
        if newest is None or newest.get("calibration") is None
        else Calibration(**newest["calibration"]),
        days=[
            summarise(
                day,
                by_date[day],
                stored.get(day),
                disagreement.get(day, {}),
                succession.get(day),
            )
            for day in sorted(by_date)
        ],
    )


class TierRecord(BaseModel):
    """One tier's record against the Gold Days, with every rate already worked out.

    The counts travel too, because a rate without them is not checkable — "69% of Gold Days"
    reads the same whether it rests on thirteen days or thirteen hundred, and this one rests
    on thirteen. But the interface never divides: the arithmetic lives in `track_record.py`,
    for the same reason `degraded` is derived on this side of the seam rather than the other.
    """

    gold_days_called: int
    gold_days_in_panel: int
    days_flagged: int

    recall: float
    precision_lower_bound: float
    """A **lower** bound. A flagged day absent from the hand-verified Gold Day list may still
    have been an XXL Day nobody documented, so the true precision can only be higher."""

    wasted_upper_bound: float
    days_wasted_upper_bound: int
    """How often acting on this tier would have been wasted, at worst — the figure #16 asks
    to be stated plainly rather than left as an inversion the reader performs. Sent as both a
    share and a count, because a share is comparable and a count is what a reader pictures."""

    flags_per_big_wave_season: float


class PanelRecord(BaseModel):
    """One span the record was scored over.

    Both tiers are named fields rather than a mapping, so a response carrying only one of
    them cannot be constructed. #16 requires Watch and Go Call accuracy reported separately
    and never as one figure; making the pair structural means no renderer has to remember.
    """

    span: str
    basis: str
    """What produced the calls — the Hindcast, which is a reconstruction of Offshore
    Conditions built after the fact and was never available in advance. Named rather than
    assumed by the interface: a rule scored against a perfect reconstruction flatters itself
    against the same rule served a real forecast, and a reader is owed which one this is."""

    gold_days: int
    big_wave_seasons: float
    watch_or_better: TierRecord
    go_call: TierRecord


class AccuracyBand(BaseModel):
    """How close each model came on one subset of hours.

    Both errors are required fields. ADR 0006 forbids reporting an accuracy figure without
    the Heuristic Baseline beside it, and a required pair is a promise the schema keeps.
    """

    name: str
    hours: int
    baseline_mae_m: float
    learned_mae_m: float
    gain_m: float
    """Positive means the learned Amplification Model is closer to the Proxy Target — the
    sign convention `analysis/amplification_model/` already publishes in."""

    caveat: str | None
    """What this row cannot carry on its own, on the rows whose source says so.

    Two rows have one. The Gold Day row rests on five days, which
    `analysis/amplification_model/README.md` says must never be quoted without. And #52
    measured the served `Combined Sea 3 m and above` aggregate as **not robust** to the
    reconstruction assumption — it falls from +0.027 to −0.004 under a residual that grows
    with the sea, and that is the shipped fit rather than an alternative. Sent with the band
    so the qualification travels into whatever renders the table."""


class RecordedDayResponse(BaseModel):
    date: str
    season: str
    call: Status
    peak_significant_wave_height_m: float
    """The day's largest Significant Wave Height **in the Hindcast** — which is the same
    reconstruction the call was derived from, not an independent observation of the outcome.
    The independently verified part of this row is `gold_day`.

    Not Face Height, and not convertible to it by any fixed ratio — `CONTEXT.md` keeps the
    two apart because the difference is the whole reason this system predicts the smaller
    number."""

    gold_day: bool
    gold_tier: str | None


class IssuedRecord(BaseModel):
    """What this installation has actually issued, as opposed to what the reports reconstruct.

    Kept apart from every figure above, and deliberately unscored. Scoring these would mean
    comparing a stored call against an observation, and no buoy reading reaches the running
    system at all — ADR 0002's Proxy Target lives in the analysis directory, for training.
    So this section counts and dates the retained calls and says nothing about whether they
    were right, which is the only honest thing it can say.

    It is here because #16 asks for a record derived from predictions as they were issued.
    The reconstructed panels above cannot demonstrate that on their own, and a page that
    showed only them would let a backtest read as an operating history.
    """

    calls_issued: int
    dates_covered: int
    go_calls_issued: int
    first_issued_at: str | None
    last_issued_at: str | None
    """None when nothing has been issued yet, which is the ordinary state of a fresh
    installation and is shown as such rather than as a zero-length record of success."""


class PublishedTrackRecord(BaseModel):
    published_at: str
    source: str
    """The path in this repository that regenerates the record, so a reader can check it
    rather than take it."""

    held_out: PanelRecord
    full_record: PanelRecord
    """Two panels, never averaged. The held-out one is measured on Big-Wave Seasons the
    thresholds never saw; the whole-record one is larger and partly covers the seasons they
    were fitted on. A reader given only their mean would be given neither."""

    scored: list[AccuracyBand]
    served: list[AccuracyBand]
    """The same comparison twice: once on identical Hindcast rows, once along the path a
    Pipeline Run takes, where the learned model must first restate an Open-Meteo reading into
    the units it was fitted in. They disagree, and the disagreement is the finding rather
    than a discrepancy to resolve."""

    gold_days_fitted: int
    gold_days_validated: int
    gold_days_total: int
    days: list[RecordedDayResponse]

    issued: IssuedRecord | None
    """None when the store could not be opened at all.

    Null rather than a section of zeros, and null rather than a failed request. The
    published record is a property of the release and does not need the store to exist, so a
    misconfigured database must not take down the page a reader consults to decide whether
    to trust the system — but reporting "0 calls issued" for a store nobody could read would
    be inventing the most flattering of the two possible truths."""


def as_tier(tier: Tier) -> TierRecord:
    return TierRecord(
        gold_days_called=tier.gold_days_called,
        gold_days_in_panel=tier.gold_days_in_panel,
        days_flagged=tier.days_flagged,
        recall=tier.recall,
        precision_lower_bound=tier.precision_lower_bound,
        wasted_upper_bound=tier.wasted_upper_bound,
        days_wasted_upper_bound=tier.days_wasted_upper_bound,
        flags_per_big_wave_season=tier.flags_per_big_wave_season,
    )


def as_panel(panel: Panel) -> PanelRecord:
    return PanelRecord(
        span=panel.span,
        basis=panel.basis,
        gold_days=panel.gold_days,
        big_wave_seasons=panel.big_wave_seasons,
        watch_or_better=as_tier(panel.watch_or_better),
        go_call=as_tier(panel.go_call),
    )


def as_bands(bands: list[Band]) -> list[AccuracyBand]:
    return [
        AccuracyBand(
            name=band.name,
            hours=band.hours,
            baseline_mae_m=band.baseline_mae_m,
            learned_mae_m=band.learned_mae_m,
            gain_m=band.gain_m,
            caveat=band.caveat,
        )
        for band in bands
    ]


@lru_cache
def default_track_record() -> TrackRecord:
    """The published record this process serves.

    Cached because it is a file that cannot change without a release, exactly like the
    thresholds. Injected below so tests can substitute one.
    """
    return load_track_record()


def get_track_record() -> TrackRecord:
    try:
        return default_track_record()
    except TrackRecordUnusable as error:
        raise HTTPException(status_code=500, detail=f"Track record unusable: {error}") from error


def optional_store() -> Store | None:
    """The store, or None when it cannot be opened.

    Only the track record uses this. Every other endpoint needs the store to answer at all,
    so a fault there is the answer; here the store contributes one section of a page whose
    substance is a file shipped with the release. Failing the whole request would mean a
    misconfigured database took down the page a reader consults to decide whether to trust
    the system — the one page whose absence is indistinguishable from a system with nothing
    to show.
    """
    try:
        return default_store()
    except StoreUnavailable:
        return None


@app.get("/api/track-record")
def track_record(
    store: Annotated[Store | None, Depends(optional_store)],
    published: Annotated[TrackRecord, Depends(get_track_record)],
) -> PublishedTrackRecord:
    """What the system has called, and what actually happened.

    Ticket #16. Nothing is scored here — the panels are read from a file the analysis
    directory writes, and the issued counts are read from the store. ADR 0005 makes this
    layer a reader, and on this endpoint that is more than a rule: re-deriving what the
    system "would have called" at request time would score it against data that did not
    exist when it called, which is precisely the flattery the record exists to rule out.

    Served whether or not any Pipeline Run has stored anything, and whether or not the store
    can be opened at all. The published record is a property of the release, not of this
    installation's history, and a reader deciding whether to trust the system should not be
    told there is no record because nothing has been ingested today.
    """
    return PublishedTrackRecord(
        published_at=published.published_at,
        source=published.source,
        held_out=as_panel(published.held_out),
        full_record=as_panel(published.full_record),
        scored=as_bands(published.scored),
        served=as_bands(published.served),
        gold_days_fitted=published.gold_days_fitted,
        gold_days_validated=published.gold_days_validated,
        gold_days_total=published.gold_days_total,
        days=[
            RecordedDayResponse(
                date=day.date,
                season=day.season,
                call=day.call,
                peak_significant_wave_height_m=day.peak_significant_wave_height_m,
                gold_day=day.gold_day,
                gold_tier=day.gold_tier,
            )
            for day in published.days
        ],
        issued=None if store is None else IssuedRecord(**store.issued_summary()),
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
        stale_after_hours=STALE_AFTER_HOURS,
        latitude=latest["latitude"],
        longitude=latest["longitude"],
        **latest["readings"],
    )

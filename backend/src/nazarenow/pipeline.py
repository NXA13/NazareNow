"""A Pipeline Run: fetch Offshore Conditions, validate them, store them.

Per ADR 0005 this is the only part of the system that contacts a third party. The API
and the web interface read what this leaves behind.

Ordering matters. A response is validated before it is stored, so a payload that has
changed shape fails the run rather than entering the store. Parsed conditions are
written only once every source has been fetched and validated — a run that fails
partway leaves the previous run's conditions in place rather than a half-updated
picture.
"""

from __future__ import annotations

import os
import sqlite3
import time
from collections.abc import Callable
from dataclasses import asdict
from datetime import date
from typing import Any

import httpx

from nazarenow import spread
from nazarenow.days import group_by_date
from nazarenow.decision import (
    Agreement,
    Status,
    agreement_of,
    conditions_behind,
    decide,
    strength,
)
from nazarenow.models import AmplificationModel, HeuristicBaseline, LearnedAmplification
from nazarenow.runs import FailureKind
from nazarenow.sources import open_meteo
from nazarenow.sources.open_meteo import (
    EXPECTED_UNITS,
    MARINE_READINGS,
    SPREAD_READINGS,
    WEATHER_READINGS,
)
from nazarenow.store import Store, StoreUnavailable

# A real Pipeline Run returns days of hourly data. Anything less is a degraded provider
# response, not a short forecast — and replacing a good forecast with it destroys the
# range while looking like a success. Zero alone was not enough of a floor: a response
# nulling all but one hour passed the check and replaced seventy-two stored hours with
# one, silently. Nor was 24: a healthy run yields about 216 hours, so a floor of 24 was
# 11% of one and let the same failure through at a larger size (#25).
MINIMUM_FORECAST_HOURS = 120

# ...and separately, no run may replace a stored forecast with less than half of it.
#
# The two guards catch different things and neither is enough alone. The floor catches a
# response that is short in isolation; this catches one that is short *relative to what it
# is about to destroy* — 150 hours is a perfectly respectable forecast unless 300 are
# already stored, and no provider is going to hand those back once they are gone.
#
# Deliberately a coarse fraction rather than a tuned one. Nobody yet knows what a
# legitimate short forecast from this provider looks like, and inventing a precise
# threshold would be false precision. A refused run is now a durable record carrying the
# payload that caused it (#30), so a provider genuinely shortening its horizon shows up as
# a run of identical failures with the evidence attached — which is what this number should
# eventually be set from, rather than from a guess made today.
MINIMUM_SHARE_OF_STORED_FORECAST = 0.5


MODELS: dict[str, Callable[[], AmplificationModel]] = {
    "heuristic-baseline": HeuristicBaseline,
    "learned-amplification": LearnedAmplification,
}
"""Every Amplification Model this release can run, by the name it reports as its own.

Keyed on `model.name` so the store's `amplification_model` field and this switch cannot
disagree about what a model is called — the recorded name is the one you would set to
reproduce the run.

The Heuristic Baseline stays in this map permanently under ADR 0006. It is not a legacy
entry: it is the benchmark, it is what `analysis/` scores every learned model against, and a
release that could no longer run it could no longer justify the one it ships.
"""

DEFAULT_MODEL = "learned-amplification"
"""What ships active, changed from the Heuristic Baseline by ticket #13.

The learned model is **worse** on the record as a whole — 0.207 m against 0.196 m of mean
absolute error across all held-out hours — and better exactly where the system earns its
keep: 0.356 m against 0.403 m above 3 m of Combined Sea, and 0.564 m against 0.885 m on
held-out Gold Day hours. The improvement grows monotonically with size across every band
above 3 m and is measured on thousands of hours, not only on the 5 held-out Gold Days.

That trade is the right way round for this system, which exists to call the days somebody
would fly for and calls nothing at all below 3 m. It is still a trade, and
`analysis/amplification_model/README.md` states it in both directions rather than quoting
the flattering half.

Switching the default is low-risk in a specific, checked sense: `LearnedAmplification`
delegates every `Condition` verdict to the Heuristic Baseline, and `decide` branches on
those identities alone. So this changes the predicted height a user reads and cannot change
who receives a Watch or a Go Call. `test_learned.py` pins that, and it is the property that
makes shipping a learned model on 5 held-out Gold Days defensible at all.
"""

MODEL_VARIABLE = "NAZARENOW_MODEL"
"""Selects the active model without a code change, following `NAZARENOW_THRESHOLDS`.

Read inside `amplification_model` rather than at import, so it is picked up on the next
scheduled run — the same reason that function gives for building its model per run.
"""


def amplification_model() -> AmplificationModel:
    """The active Amplification Model, built fresh for each Pipeline Run.

    ADR 0006 keeps the Heuristic Baseline permanently as the benchmark; ticket #13 swapped a
    learned model in behind the same interface, and this function is the whole of that swap.
    The return type is that interface rather than a concrete class, so the type checker is
    what proves the swap is possible — an interface nothing is ever declared against is
    decoration.

    Built per run, not once at import, for two reasons. It reads the calibrated thresholds
    from disk (#12) and now the fitted coefficients too (#13), so a recalibration or a refit
    takes effect on the next scheduled run rather than at the next restart — which is what
    "configurable without redeployment" has to mean for a system whose only writer is a
    scheduled batch job. And a misconfigured file then fails the run, which `run_pipeline`
    records with its cause attached, instead of failing at import where it would take down
    the API for a file the API never reads. `store` resolves its own path in a dependency for
    the same reason.

    An unrecognised name raises rather than falling back to the default. A typo that silently
    ran the baseline would leave the store recording `heuristic-baseline` for a deployment
    whose operator believed it was running the learned model, and every figure read off that
    run would be attributed to the wrong component.
    """
    name = os.environ.get(MODEL_VARIABLE) or DEFAULT_MODEL
    try:
        build = MODELS[name]
    except KeyError:
        raise ValueError(
            f"{MODEL_VARIABLE}={name!r} names no Amplification Model this release can run. "
            f"Choose one of: {', '.join(sorted(MODELS))}."
        ) from None
    return build()


def calibration_of(model: AmplificationModel) -> dict[str, Any] | None:
    """The provenance of the thresholds a model decided against, ready to store.

    Asks the model for its threshold set rather than loading the file a second time, so
    what is recorded is what actually judged the hours. Loading independently would let a
    recalibration landing mid-run record provenance for a fit that decided none of these
    calls — a discrepancy nothing downstream could detect, since both halves would look
    entirely ordinary.

    `None` for a model carrying no calibration, which includes any future model that does
    not express its thresholds this way. The `getattr` is what keeps the seam ADR 0001
    draws: the `AmplificationModel` interface promises a name, a `calibrated` flag and
    `predict`, and #13's learned model is not obliged to hold a `Thresholds` at all.
    """
    thresholds = getattr(model, "thresholds", None)
    calibration = getattr(thresholds, "calibration", None)
    if calibration is None:
        return None
    return asdict(calibration) | {"gold_days_total": calibration.gold_days_total}


def collect(body: dict[str, Any], mapping: dict[str, str]) -> dict[str, dict[str, Any]]:
    """Pull the readings we care about, each carrying the provider's own unit.

    Indexing directly is safe because `validate` has already established that every
    mapped variable and its unit are present — and the mapping here is the same object
    the request was built from, so the two cannot drift apart.
    """
    current = body["current"]
    units = body["current_units"]
    return {
        name: {"value": current[source], "unit": units[source]} for name, source in mapping.items()
    }


def collect_hourly(
    body: dict[str, Any], mapping: dict[str, str]
) -> dict[str, dict[str, dict[str, Any]]]:
    """Readings for every forecast hour, keyed by timestamp.

    Validation has already established that every mapped variable is present, carries a
    unit, and has exactly as many values as the time axis — so zipping them here cannot
    misalign a reading against the wrong hour.
    """
    hourly = body["hourly"]
    units = body["hourly_units"]
    by_hour: dict[str, dict[str, dict[str, Any]]] = {}

    for index, stamp in enumerate(hourly["time"]):
        values = {name: hourly[source][index] for name, source in mapping.items()}
        # The provider pads its time axis to the requested range and fills the hours it
        # cannot model with nulls — marine data currently stops around nine days while
        # the axis runs to sixteen. Those hours are dropped rather than stored: a null
        # reading has no honest rendering, and a zero would draw a flat calm sea.
        if any(value is None for value in values.values()):
            continue
        by_hour[stamp] = {
            name: {"value": values[name], "unit": units[source]} for name, source in mapping.items()
        }

    return by_hour


def merge_hourly(
    marine: dict[str, dict[str, dict[str, Any]]],
    weather: dict[str, dict[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    """One record per hour both providers cover.

    Only hours present in both are kept. An hour with half its readings would render as
    a gap-toothed row that looks like calm weather rather than like missing data.
    """
    return [
        {"at": stamp, "readings": marine[stamp] | weather[stamp]}
        for stamp in sorted(set(marine) & set(weather))
    ]


# The ensemble as `{forecast hour: {model: {reading: {value, unit}}}}` — every wave model's
# own readings, kept apart. Named because the nesting is four deep and unreadable spelled out
# at each of the four signatures that pass it around.
Ensemble = dict[str, dict[str, dict[str, dict[str, Any]]]]


def collect_ensemble(body: dict[str, Any], models: list[str]) -> Ensemble:
    """Each model's own readings for each forecast hour: `{stamp: {model: {variable: …}}}`.

    Nothing is combined here. Ticket #8's first requirement is that the members are stored
    separately rather than averaged on arrival, and an average is the one transformation of
    an ensemble that cannot be undone — collapse five opinions into one number and the
    disagreement ADR 0003 uses as the system's uncertainty estimate is gone for good.

    A member that answered null for an hour is simply absent from it, as is one that answered
    for none of them. That is the same shape `spread.derive` already reads: a provider being
    unavailable degrades the estimate rather than failing the run.

    Indexing the series against the time axis is safe because `validate_ensemble` has
    established that every series present runs the axis's full length — a short one would
    attribute every reading past the gap to the wrong hour.

    Readings come out under this system's own names rather than the provider's, matching what
    `collect_hourly` stores beside them.
    """
    hourly = body["hourly"]
    units = body["hourly_units"]
    by_hour: Ensemble = {}

    for index, stamp in enumerate(hourly["time"]):
        for model in models:
            readings = {
                name: {"value": hourly[key][index], "unit": units[key]}
                for name, variable in SPREAD_READINGS.items()
                if (key := f"{variable}_{model}") in hourly and hourly[key][index] is not None
            }
            if readings:
                by_hour.setdefault(stamp, {})[model] = readings

    return by_hour


def as_model_hours(ensemble: Ensemble) -> list[dict[str, Any]]:
    """The ensemble flattened into one row per model per hour, ready for the store."""
    return [
        {"at": stamp, "model": model, "readings": readings}
        for stamp in sorted(ensemble)
        for model, readings in sorted(ensemble[stamp].items())
    ]


def derive_spreads(hours: list[dict[str, Any]], ensemble: Ensemble) -> list[dict[str, Any]]:
    """One Model Spread row per date per variable, for every date the forecast covers.

    Dates come from the *forecast*, not from the ensemble, so a date the members did not
    reach still gets a row saying they did not. A date silently missing from this record
    would be indistinguishable from a Pipeline Run that never happened, and the members stop
    modelling swell before the forecast's own range ends — so the far end of every run is
    exactly where that absence would be mistaken for agreement.

    The unit is the provider's own declared unit for the variable, which `validate_ensemble`
    has already established equals the one this system's thresholds are named in.
    """
    by_date = group_by_date(hours)
    rows: list[dict[str, Any]] = []

    for day in sorted(by_date):
        stamps = [hour["at"] for hour in by_date[day]]
        for name, variable in SPREAD_READINGS.items():
            derived = spread.for_day(
                name,
                [
                    {
                        model: readings[name]["value"]
                        for model, readings in ensemble.get(stamp, {}).items()
                        if name in readings
                    }
                    for stamp in stamps
                ],
            )
            measured = derived.spread
            rows.append(
                {
                    "date": day,
                    "variable": name,
                    "value": None if measured is None else measured.value,
                    "lowest": None if measured is None else measured.lowest,
                    "highest": None if measured is None else measured.highest,
                    "unit": EXPECTED_UNITS[variable],
                    "providers": [] if measured is None else list(measured.providers),
                    "models_reporting": 0 if measured is None else measured.models_reporting,
                    "hours_measured": derived.hours_measured,
                    "hours_total": derived.hours_total,
                }
            )

    return rows


def earliest(*timestamps: str) -> str:
    """The oldest of several observation times.

    The two endpoints are separate products and each reports its own observation time.
    Presenting ten readings under the marine timestamp alone would overstate how fresh
    the weather half is, so the conditions are dated by the older of the two: the whole
    picture is at least this old.
    """
    return min(timestamps)


def lowest_opinion_of_period(ensemble: Ensemble, stamp: str) -> float | None:
    """The gloomiest organisation's swell period for one forecast hour, or None if too few
    reported.

    **One forecast hour, not the date's.** `derive_spreads` takes a date's spread from its
    median hour, which is a real hour's real disagreement and needs no model to find. A call
    rests on a different hour — the best *matching* one, which only the Amplification Model
    can identify — so a gate reading the stored median would judge a call against a moment
    that did not produce it. Per-model readings are held per hour (#8's first half) precisely
    so this can ask about the right one, with no refetch and no migration.

    `spread.derive` supplies the None, and it means fewer than two organisations rather than
    perfect agreement. `agreement_of` is where that becomes a decision.
    """
    measured = spread.derive(
        "swell_period",
        {
            model: readings["swell_period"]["value"]
            for model, readings in ensemble.get(stamp, {}).items()
            if "swell_period" in readings
        },
    )
    return None if measured is None else measured.lowest


def agreement_at(
    model: AmplificationModel,
    readings: dict[str, float],
    ensemble: Ensemble,
    stamp: str,
) -> Agreement:
    """What the wave models said about one forecast hour of this forecast.

    Asked by running the active Amplification Model a second time over the same hour with the
    lowest organisation's swell period substituted for our own: *if the gloomiest forecaster
    is right, does this hour still earn a Go Call?* Answering it this way rather than
    comparing against a bar here means the gate uses whatever thresholds actually judged the
    call, so a recalibration cannot move the tiers and leave the gate behind.
    """
    lowest = lowest_opinion_of_period(ensemble, stamp)
    if lowest is None:
        return agreement_of(None)
    return agreement_of(model.predict(readings | {"swell_period": lowest}))


def derive_calls(hours: list[dict[str, Any]], ensemble: Ensemble) -> list[dict[str, Any]]:
    """Group hours into days and decide a call for each.

    Per ADR 0005 this belongs to the Pipeline Run, not the request path: the API is
    strictly a reader, CONTEXT.md makes a Pipeline Run "the only part of the system that
    runs a model", and the ADR promises every prediction is retained -- the record ticket
    #11 needs to score Go Call precision after the fact. Deciding per request produced no
    record at all.

    **A day is called at the best call any of its hours supports.** Every hour is decided on
    its own and the strongest resulting call wins, the largest sea breaking a tie.

    Choosing a representative hour *before* deciding cannot work, and two attempts at it
    failed the same way. Ranking hours by how many conditions they failed is tier-blind: a
    Watch ignores wind by design, so an 8m hour failing only *period* ties with a clean 3.5m
    hour failing only *wind*, wins the tie on size, and takes the day down to no call --
    a bigger wave *removing* a Watch. Judging the peak hour alone had the same shape. Any
    pre-selection must guess which conditions matter, and only the tier knows that.

    Deciding first and comparing calls afterwards cannot have that fault: each hour is
    judged against the conditions its own tier requires.

    A Go Call can still rest on a single clean hour, and it is the tier optimised for
    precision. Rather than invent a minimum window -- ticket #12 calibrates thresholds
    against Gold Days and should own that number -- every call states how many hours
    supported it, so a day resting on one says so in the reasons a user reads. ADR 0003
    records the trade.
    """
    by_date = group_by_date(hours)
    issued_for = min(by_date)
    calls: list[dict[str, Any]] = []
    # One model for the whole run, so every day in a forecast is decided against the same
    # thresholds. Rebuilding it per day would let a recalibration landing mid-run split one
    # forecast across two rules.
    model = amplification_model()
    # Recorded on every call this run writes, so a call can always be read back against the
    # calibration that produced it rather than against whichever one is current when someone
    # asks (#12, and #30's premise that a prediction is traceable to its inputs).
    provenance = calibration_of(model)

    for day in sorted(by_date):
        readings = [
            {name: value["value"] for name, value in hour["readings"].items()}
            for hour in by_date[day]
        ]
        predictions = [model.predict(hour) for hour in readings]
        lead_time = (date.fromisoformat(day) - date.fromisoformat(issued_for)).days
        # Decide every hour, then take the strongest call. The reasons and the height
        # reported are the winning hour's, so what a user reads is the hour that earned
        # the call rather than whichever hour some earlier heuristic preferred.
        #
        # Model Spread is consulted per hour for the same reason, and it is what makes the
        # deciding hour's spread the one that gates the call: whichever hour wins brings its
        # own ensemble verdict with it, so no separate pass has to go back and find it.
        issued = [
            decide(prediction, lead_time, agreement_at(model, hour, ensemble, stamp["at"]))
            for stamp, hour, prediction in zip(by_date[day], readings, predictions, strict=True)
        ]
        call = max(
            issued,
            key=lambda issued: (
                strength(issued.status),
                issued.predicted_significant_wave_height,
            ),
        )
        # Counted against the conditions this call rests on, not always against all four.
        # A Watch ignores wind by design, so counting every condition made a genuine Watch
        # day report "0 of 24 forecast hours match every condition" beside its own badge.
        required = conditions_behind(call.status)
        matching = sum(1 for prediction in predictions if prediction.holds(*required))
        hours_matched = (
            f"{matching} of {len(predictions)} forecast hours carry the swell behind this Watch"
            if call.status is Status.WATCH
            else f"{matching} of {len(predictions)} forecast hours match every condition"
        )
        calls.append(
            {
                "date": day,
                "issued_for_date": issued_for,
                "status": call.status.value,
                "lead_time_days": call.lead_time_days,
                "reasons": [*call.reasons, hours_matched],
                "predicted_significant_wave_height": call.predicted_significant_wave_height,
                "unit": call.unit,
                "model_agreement": call.agreement.value,
                "go_call_withheld": call.go_call_withheld,
                "amplification_model": model.name,
                "calibrated": model.calibrated,
                "calibration": provenance,
            }
        )
    return calls


def failure_kind(error: BaseException) -> FailureKind:
    """Which kind of failure an exception represents.

    Lives here rather than in `runs` because it names `StoreUnavailable`, and `store`
    imports the run vocabulary — putting this beside the enum would close an import cycle.

    Order matters: `StoreUnavailable` is a `RuntimeError` and not an `httpx` or value
    error, but it is checked first anyway so that the ordering states the intent rather
    than relying on the current class hierarchy staying as it is.
    """
    # A store fault *during* a run, which is the only kind that can be recorded: a store
    # too broken to open fails at `begin_run`, before there is a run record to write to.
    # `sqlite3.Error` is the reachable half — a full disk or a locked database while the
    # output is being written — and `record_run_failed` still succeeds after that, because
    # the failed transaction has already rolled back. Without it this kind would name a
    # situation the record could never actually contain.
    if isinstance(error, StoreUnavailable | sqlite3.Error):
        return FailureKind.STORE_UNAVAILABLE
    # Every transport fault and every error status alike: unreachable, timed out, 5xx,
    # rate-limited. From the record's point of view they are one situation — the provider
    # did not give us usable data this cycle — and the detail string carries which.
    if isinstance(error, httpx.HTTPError):
        return FailureKind.PROVIDER_UNAVAILABLE
    # Everything `validate` raises, plus the forecast-hours floor. A payload that arrived
    # and did not mean what this system expects it to mean.
    if isinstance(error, ValueError):
        return FailureKind.PAYLOAD_UNRECOGNISED
    return FailureKind.UNEXPECTED


def failure_detail(error: BaseException) -> str:
    """The failure in one line: the exception's type and its message.

    The type is included because the message alone is often the more forgettable half —
    an empty `ConnectError` says nothing, while its name says the provider was
    unreachable.
    """
    return f"{type(error).__name__}: {error}"


ENSEMBLE_UNAVAILABLE = "open-meteo-ensemble-unavailable"
"""The `raw_response` source naming a run that could not reach the ensemble at all.

Its own source rather than a flag on `open-meteo-ensemble`, so "which runs lost their second
opinion" is one query and no row under the real source is anything but a real response.
"""


def attempted_url(error: httpx.HTTPError, fallback: str) -> str:
    """The URL a failed request was aimed at, as far as the exception knows it.

    `httpx.HTTPError` splits here: a `RequestError` carries the request it failed on, while a
    bare error raised before one was built does not. The endpoint is used as the fallback so
    the record always names where we were looking — a blank URL beside a transport failure
    would lose the one detail that distinguishes "the ensemble was unreachable" from a fault
    somewhere else in the run.
    """
    request = getattr(error, "request", None)
    return str(request.url) if request is not None else fallback


def run_pipeline(store: Store, client: httpx.Client, sleep=time.sleep) -> None:
    """Execute one Pipeline Run against the given store, recording the run either way.

    The run record is opened here rather than in the scheduler, so the one-off `ingest`
    command leaves the same trace as a scheduled run. A record that only existed under the
    scheduler would make the store's provenance depend on which command happened to write
    it, and ticket #11 scores whatever is in there.
    """
    run_id = store.begin_run()
    try:
        _fetch_and_store(store, client, sleep, run_id)
    except Exception as error:
        # The failure is recorded and then re-raised unchanged. The scheduler still
        # decides what a failed run means for the schedule (`schedule.py`); this only
        # ensures the attempt is not invisible to anyone reading the store afterwards.
        store.record_run_failed(run_id, failure_kind(error), failure_detail(error))
        raise


def _fetch_and_store(store: Store, client: httpx.Client, sleep, run_id: int) -> None:
    marine_body, marine_url = open_meteo.fetch_marine(client, sleep)
    store.record_raw_response(run_id, "open-meteo-marine", marine_url, marine_body)

    weather_body, weather_url = open_meteo.fetch_weather(client, sleep)
    store.record_raw_response(run_id, "open-meteo-weather", weather_url, weather_body)

    ensemble = fetch_spread_members(store, client, sleep, run_id)

    # Everything is computed and checked before anything is written. Writing the current
    # conditions first meant a rejected forecast still advanced them — a half-updated
    # picture, which this module's own docstring promises not to produce.
    readings = collect(marine_body, MARINE_READINGS) | collect(weather_body, WEATHER_READINGS)
    hours = merge_hourly(
        collect_hourly(marine_body, MARINE_READINGS),
        collect_hourly(weather_body, WEATHER_READINGS),
    )
    if len(hours) < MINIMUM_FORECAST_HOURS:
        raise ValueError(
            f"Providers returned only {len(hours)} usable forecast hours, fewer than the "
            f"{MINIMUM_FORECAST_HOURS} a real run produces; keeping the previous forecast"
        )

    stored = len(store.forecast())
    if len(hours) < stored * MINIMUM_SHARE_OF_STORED_FORECAST:
        raise ValueError(
            f"Providers returned {len(hours)} usable forecast hours, less than half of the "
            f"{stored} already stored; keeping the previous forecast rather than replacing "
            "a longer one with a fragment"
        )

    store.record_run(
        observed_at=earliest(marine_body["current"]["time"], weather_body["current"]["time"]),
        latitude=marine_body["latitude"],
        longitude=marine_body["longitude"],
        readings=readings,
        hours=hours,
        calls=derive_calls(hours, ensemble),
        model_hours=as_model_hours(ensemble),
        spreads=derive_spreads(hours, ensemble),
        run_id=run_id,
    )


def fetch_spread_members(store: Store, client: httpx.Client, sleep, run_id: int) -> Ensemble:
    """The wave models Model Spread is measured across, or an empty ensemble if unreachable.

    **A transport failure here degrades the estimate; it does not fail the run.** ADR 0003 is
    explicit that a model being unavailable "degrades the uncertainty estimate rather than the
    prediction", and the forecast a traveller reads does not depend on this endpoint at all —
    losing the whole site's range because a second opinion timed out would be the wrong trade
    in both directions.

    A `ValueError` is deliberately *not* caught, and the distinction is `validate_ensemble`'s
    own: a member answering nothing is an unavailable provider, while a response with no time
    axis, the wrong timezone, unstated units or no series for any member at all is a payload
    that has changed shape. This project's characteristic failure is data that arrives looking
    plausible and is wrong, and a changed contract read as "everybody happens to be quiet
    today" is precisely that.

    **The degradation is recorded, not merely survived.** #8 requires an unavailable provider
    to be *recorded*, and the all-null spread rows alone do not say what happened: a row with
    no value is identical whether the endpoint was unreachable or answered cleanly with every
    member quiet. Those are different facts — one is our sight of the models failing, the
    other is the models having nothing to say — and #11 scores calls against the inputs that
    were actually available when they were issued.

    So the failure is written to `raw_response` under its own source name, carrying the same
    `failure_kind`/`failure_detail` vocabulary a failed run would use. A separate source
    rather than the real one because this is not a response: nothing was received, and a
    synthesised body filed under `open-meteo-ensemble` would be a fabricated provider reply
    sitting in the table that exists to hold genuine ones.

    Alongside it, `derive_spreads` still writes a row for every date carrying no value and
    `hours_measured` of zero, and `model_forecast_hour` holds nothing for the run.
    """
    models = list(spread.PROVIDERS)
    try:
        body, url = open_meteo.fetch_ensemble(client, models, sleep)
    except httpx.HTTPError as error:
        store.record_raw_response(
            run_id,
            ENSEMBLE_UNAVAILABLE,
            attempted_url(error, open_meteo.MARINE_URL),
            {"failure_kind": failure_kind(error).value, "failure_detail": failure_detail(error)},
        )
        return {}
    store.record_raw_response(run_id, "open-meteo-ensemble", url, body)
    return collect_ensemble(body, models)

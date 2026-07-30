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

import time
from datetime import date
from typing import Any

import httpx

from nazarenow.days import group_by_date
from nazarenow.decision import decide
from nazarenow.models import AmplificationModel, HeuristicBaseline
from nazarenow.sources import open_meteo
from nazarenow.sources.open_meteo import MARINE_READINGS, WEATHER_READINGS
from nazarenow.store import Store

# A real Pipeline Run returns days of hourly data. Anything less is a degraded provider
# response, not a short forecast — and replacing a good forecast with it destroys the
# range while looking like a success. Zero alone was not enough of a floor: a response
# nulling all but one hour passed the check and replaced seventy-two stored hours with
# one, silently.
MINIMUM_FORECAST_HOURS = 24

# The active Amplification Model. ADR 0006 keeps the Heuristic Baseline permanently as
# the benchmark; ticket #13 swaps a learned model in behind the same interface. Annotated
# with that interface rather than left implicit, so the type checker is what proves the
# swap is possible — an interface nothing is ever declared against is decoration.
AMPLIFICATION_MODEL: AmplificationModel = HeuristicBaseline()


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


def earliest(*timestamps: str) -> str:
    """The oldest of several observation times.

    The two endpoints are separate products and each reports its own observation time.
    Presenting ten readings under the marine timestamp alone would overstate how fresh
    the weather half is, so the conditions are dated by the older of the two: the whole
    picture is at least this old.
    """
    return min(timestamps)


def derive_calls(hours: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group hours into days and decide a call for each.

    Per ADR 0005 this belongs to the Pipeline Run, not the request path: the API is
    strictly a reader, CONTEXT.md makes a Pipeline Run "the only part of the system that
    runs a model", and the ADR promises every prediction is retained -- the record ticket
    #11 needs to score Go Call precision after the fact. Deciding per request produced no
    record at all.

    The call is judged on the day's best *matching* hour rather than its biggest. A day
    with a clean 3m offshore window at 09:00 and an onshore peak at 15:00 is worth
    surfacing, and judging the peak alone silently discarded it -- costing exactly the
    recall ADR 0003 asks the Watch tier to protect.

    That rule cuts against precision, though, and a Go Call is the tier optimised for it:
    one clean hour in twenty-four is enough to earn "book a flight". Rather than invent a
    minimum window -- ticket #12 calibrates thresholds against Gold Days and should own
    that number -- every call states how many of the day's hours actually matched, so a
    day resting on a single hour says so in the reasons a user reads. ADR 0003 records
    the trade.
    """
    by_date = group_by_date(hours)
    issued_for = min(by_date)
    calls: list[dict[str, Any]] = []

    for day in sorted(by_date):
        predictions = [
            AMPLIFICATION_MODEL.predict(
                {name: value["value"] for name, value in hour["readings"].items()}
            )
            for hour in by_date[day]
        ]
        # Fewest failed conditions wins; the largest sea breaks a tie.
        best = min(
            predictions,
            key=lambda p: (len(p.unmatched), -p.significant_wave_height),
        )
        lead_time = (date.fromisoformat(day) - date.fromisoformat(issued_for)).days
        call = decide(best, lead_time)
        matching = sum(1 for prediction in predictions if prediction.matches_rule)
        calls.append(
            {
                "date": day,
                "issued_for_date": issued_for,
                "status": call.status.value,
                "lead_time_days": call.lead_time_days,
                "reasons": [
                    *call.reasons,
                    f"{matching} of {len(predictions)} forecast hours match every condition",
                ],
                "predicted_significant_wave_height": call.predicted_significant_wave_height,
                "unit": call.unit,
                "amplification_model": AMPLIFICATION_MODEL.name,
                "calibrated": AMPLIFICATION_MODEL.calibrated,
            }
        )
    return calls


def run_pipeline(store: Store, client: httpx.Client, sleep=time.sleep) -> None:
    """Execute one Pipeline Run against the given store."""
    marine_body, marine_url = open_meteo.fetch_marine(client, sleep)
    store.record_raw_response("open-meteo-marine", marine_url, marine_body)

    weather_body, weather_url = open_meteo.fetch_weather(client, sleep)
    store.record_raw_response("open-meteo-weather", weather_url, weather_body)

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

    store.record_run(
        observed_at=earliest(marine_body["current"]["time"], weather_body["current"]["time"]),
        latitude=marine_body["latitude"],
        longitude=marine_body["longitude"],
        readings=readings,
        hours=hours,
        calls=derive_calls(hours),
    )

"""What a day is, and what a run does when the provider sends less than a forecast.

Two decisions taken deliberately rather than inherited, both recorded in ADR 0008.

A **day** is a Nazaré local day. A traveller books a day in Portugal, so the day the
system groups hours into has to be the day they will stand on the beach — which is not
the UTC day for about four weeks of every Big-Wave Season.

A **short forecast** is refused rather than stored, because replacing a nine-day forecast
with a fragment and reporting success is the failure this project keeps designing against.
"""

from __future__ import annotations

import httpx
import pytest

from helpers import GIANT, forecast_provider, ingest, no_sleep
from nazarenow.pipeline import MINIMUM_FORECAST_HOURS, run_pipeline
from nazarenow.runs import FailureKind
from nazarenow.schedule import run_scheduled
from nazarenow.sources.open_meteo import TIMEZONE

TODAY = "2026-02-09"


class TestADayIsANazareLocalDay:
    """Europe/Lisbon is UTC in winter and UTC+1 under summer time.

    Under UTC+1 the hour stamped 23:00 UTC is midnight *the next day* in Nazaré, so a
    UTC-grouped day is shifted by one hour's worth of readings against the day a traveller
    actually experiences. That is not a rounding detail: it decides which day a call is
    issued for, and therefore what the record ticket #11 scores means.

    Roughly 28 days of every Big-Wave Season fall under summer time — 25 of them in the
    first three weeks of October, which is when the deployment in #28 starts collecting.
    """

    def test_the_run_asks_the_provider_for_nazare_local_time(self, store) -> None:
        """Asked for, so the timestamps arrive already local and grouping is correct by
        construction rather than by a conversion someone has to remember."""
        asked: list[str] = []
        good = forecast_provider({}, today=TODAY)

        def handle(request: httpx.Request) -> httpx.Response:
            asked.append(request.url.params["timezone"])
            return good.handler(request)

        ingest(store, httpx.MockTransport(handle))

        assert asked, "the provider was never called"
        assert set(asked) == {"Europe/Lisbon"}, "hours would arrive on the wrong day boundary"
        assert TIMEZONE == "Europe/Lisbon"

    def test_a_response_in_the_wrong_zone_fails_the_run(self, store) -> None:
        """The request is a preference; only the response is evidence.

        Exactly the reasoning `EXPECTED_UNITS` already applies to units: a provider-side
        default that quietly ignored our parameter would shift every day boundary by an
        hour, and nothing downstream could tell. A whole day's calls would be attributed to
        the wrong date while every number on the page still looked plausible.
        """
        good = forecast_provider({}, today=TODAY)

        def wrong_zone(request: httpx.Request) -> httpx.Response:
            body = good.handler(request).json()
            return httpx.Response(200, json={**body, "timezone": "GMT"})

        with httpx.Client(transport=httpx.MockTransport(wrong_zone)) as client:
            run_scheduled(store, client, runs=1, sleep=no_sleep)

        failed = store.failed_runs()
        assert len(failed) == 1, "a run on the wrong day boundary was accepted"
        assert failed[0]["failure_kind"] == FailureKind.PAYLOAD_UNRECOGNISED.value
        assert "Europe/Lisbon" in failed[0]["failure_detail"]


class TestAShortForecastIsRefused:
    """`MINIMUM_FORECAST_HOURS` was an absolute floor of 24 against a healthy run of about
    216 hours, so a degraded response carrying 30 could replace nine days of forecast and
    report success — the failure its own comment described, moved rather than removed.

    Two guards now, because neither alone is enough: an absolute floor catches a response
    that is short in isolation, and a comparison against what is already stored catches one
    that is short *relative to what it is about to destroy*.
    """

    def test_a_fragment_of_a_forecast_is_refused(self, store) -> None:
        with (
            httpx.Client(transport=forecast_provider({}, today=TODAY, days=2)) as client,
            pytest.raises(ValueError, match="forecast hours"),
        ):
            run_pipeline(store, client, sleep=no_sleep)

        assert store.forecast() == [], "a two-day fragment was stored as a forecast"

    def test_the_floor_is_a_real_forecast_not_a_token_one(self) -> None:
        """Pinned as a literal. 24 hours was 11% of a healthy run and passed as success."""
        assert MINIMUM_FORECAST_HOURS == 120

    def test_a_run_that_shrinks_the_stored_forecast_by_half_is_refused(self, store) -> None:
        """The guard the absolute floor cannot provide.

        Six days clears the floor comfortably. It is still less than half of the fourteen
        days already stored, and accepting it would throw away eight days of forecast that
        nothing is going to fetch again.
        """
        ingest(store, forecast_provider({"2026-02-13": GIANT}, today=TODAY, days=14))
        before = store.forecast()

        with (
            httpx.Client(transport=forecast_provider({}, today=TODAY, days=6)) as client,
            pytest.raises(ValueError, match="less than half"),
        ):
            run_pipeline(store, client, sleep=no_sleep)

        assert store.forecast() == before, "the longer forecast was replaced by a shorter one"

    def test_a_forecast_that_shortens_a_little_is_still_accepted(self, store) -> None:
        """A provider legitimately trimming its horizon must not stop the system.

        The two guards exist to catch collapse, not variation — a rule that refused every
        shrinkage would turn an ordinary provider change into an outage that needs a code
        edit to clear.
        """
        ingest(store, forecast_provider({}, today=TODAY, days=14))

        with httpx.Client(transport=forecast_provider({}, today=TODAY, days=11)) as client:
            run_pipeline(store, client, sleep=no_sleep)

        assert len(store.forecast()) == 11 * 24, "a normal shortening was refused"

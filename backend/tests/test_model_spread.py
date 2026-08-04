"""Model Spread end to end: fetched, stored per model, derived per date, served.

Driven at the same backend seam as the rest of the suite — providers stubbed at the HTTP
boundary, a Pipeline Run executed, the result read back through the API.

ADR 0003 makes disagreement between independent wave models the system's uncertainty
estimate, and #8's acceptance criteria are mostly about the ways that estimate can quietly
stop being one: by averaging the members away on arrival, by reporting a confident-looking
number when hardly anyone answered, or by failing the whole run because a second opinion was
unavailable.
"""

from __future__ import annotations

import pytest

from helpers import ENSEMBLE_SPREAD_M, GIANT, forecast_provider, ingest

TODAY = "2026-02-09"
SOON = "2026-02-12"

# Both NCEP resolutions, which is one organisation leaving the ensemble. Silencing a single
# resolution would prove nothing: NCEP still votes through the other one, which is the
# property that keeps the spread comparable across Lead Times.
NCEP = ("ncep_gfswave025", "ncep_gfswave016")
MOST_OF_THE_ROSTER = (*NCEP, "meteofrance_wave")


def spread_for(client, date: str, reading: str = "swell_height") -> dict:
    body = client.get("/api/conditions/forecast").json()
    day = next(day for day in body["days"] if day["date"] == date)
    return day["model_spread"][reading]


class TestTheMembersAreKeptApart:
    """#8's first criterion: fetched per model and stored separately, not averaged."""

    def test_every_model_keeps_its_own_reading_for_every_hour(self, store) -> None:
        ingest(store, forecast_provider({SOON: GIANT}, today=TODAY))

        rows = store.model_forecast()

        assert rows, "the ensemble stored nothing"
        assert {row["model"] for row in rows} == {
            "meteofrance_wave",
            "dwd_ewam",
            "dwd_gwam",
            "ncep_gfswave025",
            "ncep_gfswave016",
        }
        # Five members for one hour, each with its own value. An average would leave one.
        first = min(row["at"] for row in rows)
        at_first = [row for row in rows if row["at"] == first]
        assert len(at_first) == 5
        assert len({row["readings"]["swell_height"]["value"] for row in at_first}) > 1

    def test_the_members_cover_the_same_readings_the_spread_is_measured_on(self, store) -> None:
        """Stored under this system's own names, as the forecast hours beside them are —
        not the provider's `swell_wave_height` spelling, which would make the store speak
        two languages and leave the read path translating between them."""
        ingest(store, forecast_provider({SOON: GIANT}, today=TODAY))

        readings = store.model_forecast()[0]["readings"]

        assert sorted(readings) == ["swell_direction", "swell_height", "swell_period"]
        assert readings["swell_height"]["unit"] == "m"


class TestTheSpreadIsDerivedPerDate:
    def test_a_date_carries_the_disagreement_between_the_organisations(self, store, client):
        ingest(store, forecast_provider({SOON: GIANT}, today=TODAY))

        measured = spread_for(client, SOON)

        assert measured["spread"] == pytest.approx(ENSEMBLE_SPREAD_M)
        assert measured["unit"] == "m"
        assert measured["highest"] - measured["lowest"] == pytest.approx(measured["spread"])

    def test_which_providers_contributed_is_visible(self, store, client) -> None:
        """#8 asks for this by name. A spread from two organisations and one from three are
        not comparable, and the number alone cannot say which happened."""
        ingest(store, forecast_provider({SOON: GIANT}, today=TODAY))

        measured = spread_for(client, SOON)

        assert measured["providers"] == ["DWD", "MeteoFrance", "NCEP"]
        assert measured["degraded"] is False

    def test_an_organisation_votes_once_however_many_models_it_runs(self, store, client):
        """Five members, three votes. Counted per model, DWD and NCEP would each carry two
        and the ensemble would look nearly twice as corroborated as it is."""
        ingest(store, forecast_provider({SOON: GIANT}, today=TODAY))

        assert len(spread_for(client, SOON)["providers"]) == 3

    def test_every_forecast_date_carries_an_entry_even_where_nothing_was_measured(
        self, store, client
    ) -> None:
        """A date silently missing from the record would read as agreement to anything
        scanning it, and the far end of a forecast — where members stop answering — is
        exactly where that mistake would be made."""
        ingest(store, forecast_provider({SOON: GIANT}, today=TODAY))

        body = client.get("/api/conditions/forecast").json()

        for day in body["days"]:
            assert sorted(day["model_spread"]) == [
                "swell_direction",
                "swell_height",
                "swell_period",
            ], f"{day['date']} is missing a Model Spread entry"

    def test_the_spread_says_how_much_of_the_day_it_was_measured_across(self, store, client):
        ingest(store, forecast_provider({SOON: GIANT}, today=TODAY))

        measured = spread_for(client, SOON)

        assert measured["hours_measured"] == 24
        assert measured["hours_total"] == 24


class TestSwellDirectionIsMeasuredOnACircle:
    def test_agreement_across_north_is_not_reported_as_near_total_disagreement(
        self, store, client
    ) -> None:
        """A swell from 355°, 5° and 15° is a 20° spread, and plain subtraction calls it
        350°. That would put maximum doubt on a day the models agree about — and on a
        northerly swell, which is the direction the Nazaré Canyon focuses.

        The stub offsets each model's bearing from the day's own, so a base direction of
        358° puts the members either side of north.
        """
        ingest(store, forecast_provider({SOON: {**GIANT, "swell_direction": 358}}, today=TODAY))

        measured = spread_for(client, SOON, "swell_direction")

        assert measured["spread"] < 90, "the arc crossing north was measured the long way"
        assert measured["unit"] == "°"


class TestAProviderBeingUnavailable:
    """ADR 0003: it degrades the estimate rather than failing the Pipeline Run."""

    def test_one_organisation_silent_still_produces_a_usable_run(self, store, client) -> None:
        """#8's second named test. A member answering 200 with nothing in it is what an
        unavailable provider actually looks like here."""
        ingest(store, forecast_provider({SOON: GIANT}, today=TODAY, silent_models=NCEP))

        body = client.get("/api/conditions/forecast").json()
        day = next(day for day in body["days"] if day["date"] == SOON)

        assert day["call"] is not None, "the run must still have produced calls"
        measured = day["model_spread"]["swell_height"]
        assert measured["spread"] is not None
        assert measured["providers"] == ["DWD", "MeteoFrance"]
        assert measured["degraded"] is True

    def test_a_single_organisation_left_carries_no_spread_rather_than_zero(
        self, store, client
    ) -> None:
        """Zero would be indistinguishable from perfect agreement and would read as
        certainty at exactly the moment the system knows least."""
        ingest(
            store,
            forecast_provider({SOON: GIANT}, today=TODAY, silent_models=MOST_OF_THE_ROSTER),
        )

        measured = spread_for(client, SOON)

        assert measured["spread"] is None
        assert measured["lowest"] is None and measured["highest"] is None
        assert measured["hours_measured"] == 0
        assert measured["degraded"] is True

    def test_the_ensemble_endpoint_failing_does_not_fail_the_run(self, store, client) -> None:
        """The forecast a traveller reads does not come from this endpoint at all. Losing
        the whole range because a second opinion timed out would be the wrong trade."""
        ingest(store, forecast_provider({SOON: GIANT}, today=TODAY, ensemble_status=503))

        body = client.get("/api/conditions/forecast").json()
        day = next(day for day in body["days"] if day["date"] == SOON)

        assert day["call"] is not None
        assert day["hours"], "the forecast itself must survive"
        assert day["model_spread"]["swell_height"]["spread"] is None
        assert store.model_forecast() == []

    def test_an_unreachable_ensemble_is_recorded_rather_than_left_silent(self, store) -> None:
        """A date with no row is indistinguishable from a Pipeline Run that never happened,
        so the degradation is written down instead of omitted."""
        ingest(store, forecast_provider({SOON: GIANT}, today=TODAY, ensemble_status=503))

        history = store.spread_history()

        assert history, "an unreachable ensemble left no record at all"
        assert all(row["value"] is None for row in history)
        assert all(row["providers"] == [] for row in history)
        assert all(row["hours_total"] == 24 for row in history)


class TestTheRecordAccumulates:
    def test_a_later_run_adds_to_the_record_rather_than_replacing_it(self, store) -> None:
        """What a date's disagreement was at ten days and what it had become at three is
        the series #11 needs to say whether narrowing spread preceded the swells that
        arrived. Overwriting per date would destroy it."""
        ingest(store, forecast_provider({SOON: GIANT}, today=TODAY))
        first = len(store.spread_history())

        ingest(store, forecast_provider({SOON: GIANT}, today=TODAY))

        assert len(store.spread_history()) == first * 2

    def test_a_spread_names_the_run_that_derived_it(self, store) -> None:
        ingest(store, forecast_provider({SOON: GIANT}, today=TODAY))

        run = store.runs()[0]

        assert all(row["run_id"] == run["id"] for row in store.spread_history())

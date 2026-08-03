"""Watch, Go Call and Confirmed statuses, driven at the agreed backend seam.

Everything here goes through the HTTP API. An earlier version called the Amplification
Model directly, which was a seam breach with no justification: every property asserted
below — status, reasons, predicted height — is observable through the API, so the
exception `Store.raw_responses()` earns ("nothing else can observe it") does not apply.

Two classes at the end are the narrow exceptions, each for the same documented reason:
what they assert cannot be observed through HTTP at all. `TestTheInterfaceIsRealDecides`
substitutes a different Amplification Model, which is the swap ADR 0001 and ADR 0006
exist to permit and which no request can exercise; `TestCallsSurviveTheNextRun` asserts
retention across runs, and only the latest call is served.

Thresholds are pinned at their boundaries, both sides. Testing only "a giant setup
matches and a flat one does not" left every threshold value and every comparison operator
free: 3m could become 2m or 4m, and >= could become >, with the suite still green.
"""

from __future__ import annotations

import pytest

from helpers import (
    BONUS_HOUR,
    GIANT,
    QUIET,
    forecast_provider,
    ingest,
    stub_hours,
    swell_height_for,
)
from nazarenow.decision import decide
from nazarenow.models.base import Condition, ConditionOutcome, Prediction
from nazarenow.pipeline import DEFAULT_MODEL, amplification_model

# Literals, deliberately. Importing the constants and testing `CONSTANT - 0.1` looks
# rigorous and pins nothing: change the constant and both sides of the assertion move
# with it. These are the values ticket #39's recalibration produced, so a silent retuning
# of any threshold fails here — which is the point, and which is why #12 and then #39 each
# had to come through this file and say so rather than sliding past a green suite.
#
# #39 refitted against 38 Gold Days rather than #12's 9, on the Copernicus reanalysis, and
# translated the wave bars back into Open-Meteo units. Every one of them moved, and the
# period bars moved a long way: a Watch bar that had to catch 25 Gold Days rather than 6
# lands far lower than one that only had to catch the recent, well-documented ones.
#
# #43 then moved the Watch bar back up, from 10.1 s to 11.5 s, by giving the recall tier a
# stated price (ADR 0010) instead of requiring it to catch every Gold Day whatever that cost.
# Only this bar moved: the Go Call bar, the height bar and the wind exemption are unchanged.
HEIGHT_M = 2.75
WATCH_PERIOD_S = 11.5
GO_PERIOD_S = 12.9
SWELL_ARC_FROM, SWELL_ARC_TO = 255.0, 330.0
WIND_ARC_FROM, WIND_ARC_TO = 20.0, 180.0
MAX_WIND_KMH = 35.0
LIGHT_WIND_KMH = 16.5
"""ADR 0009: below this the offshore arc is not consulted. Not a second cap — see the ADR."""
CONFIRMED_LEAD = 1
GO_LEAD = 7

# Comfortably above the calibrated height bar, and well below the "big" hours these tests
# contrast it against. Named because several cases need an hour that is modest *and*
# clearing every condition, and the previous literal 3.5 stopped clearing the height bar
# the moment #12 raised it — turning four unrelated tests red for a reason none of them
# were about.
MODEST_M = 4.0

TODAY = "2026-02-09"
SOON = "2026-02-13"  # lead 4: inside the Go band
FAR = "2026-02-20"  # lead 11: beyond it


def calls(client) -> dict[str, dict]:
    body = client.get("/api/conditions/forecast").json()
    return {day["date"]: day["call"] for day in body["days"]}


def status_for(store, client, conditions: dict, date: str = SOON, **kwargs) -> str:
    ingest(store, forecast_provider({date: conditions}, today=TODAY, **kwargs))
    return calls(client)[date]["status"]


def predicted_for(conditions: dict, swell_height: float | None = None) -> float:
    """What the active Amplification Model predicts for one hour of these conditions.

    Since ticket #13 the shipped model is a learned one, so the height a call reports is no
    longer the height that went in. Several cases below are about *which hour* a day was
    called on, and used to name that hour by its literal height — an assertion that reads as
    a statement about hour selection and is in fact a statement about the model.

    Asking the active model keeps those cases about their own subject and keeps them true
    under either model, which is what ADR 0006's permanent swappability requires of them.
    It is not circular: nothing here asserts the model is *right*, only that the call
    reported the hour it claims to have judged. `test_learned.py` and
    `analysis/amplification_model/` own whether the number is any good.
    """
    hour = stub_hours(TODAY, conditions)[0]
    readings = {name: value["value"] for name, value in hour["readings"].items()}
    if swell_height is not None:
        readings["swell_height"] = swell_height
    return amplification_model().predict(readings).significant_wave_height


def winning_hour_swell_height(conditions: dict) -> float:
    """The swell height `forecast_provider` generates for these conditions on its bonus hour.

    Delegated rather than re-derived: `helpers.swell_height_for` is the only place that
    expression should exist, since the fixture and this expectation have to move together.
    """
    return swell_height_for(conditions["significant_wave_height"], BONUS_HOUR)


class TestThresholdBoundaries:
    """Each threshold, one increment either side of its boundary."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(HEIGHT_M, "go"), (HEIGHT_M - 0.1, "none")],
    )
    def test_wave_height_boundary(self, store, client, value, expected) -> None:
        assert status_for(store, client, {**GIANT, "significant_wave_height": value}) == expected

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (GO_PERIOD_S, "go"),
            # Between the two calibrated bars: worth watching, not worth booking on. This
            # row is the whole of what #12 changed about the tiers, and #11 measured the
            # cost of not having it — a Watch tier that caught nothing a Go Call missed.
            (GO_PERIOD_S - 0.1, "watch"),
            (WATCH_PERIOD_S, "watch"),
            (WATCH_PERIOD_S - 0.1, "none"),
        ],
    )
    def test_swell_period_boundary(self, store, client, value, expected) -> None:
        """Both bars, one increment either side, at a Lead Time inside the Go band."""
        assert status_for(store, client, {**GIANT, "swell_period": value}) == expected

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (SWELL_ARC_FROM, "go"),
            (SWELL_ARC_FROM - 1, "none"),
            (SWELL_ARC_TO, "go"),
            (SWELL_ARC_TO + 1, "none"),
        ],
    )
    def test_swell_direction_arc_edges(self, store, client, value, expected) -> None:
        assert status_for(store, client, {**GIANT, "swell_direction": value}) == expected

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (WIND_ARC_FROM, "go"),
            (WIND_ARC_FROM - 1, "watch"),
            (WIND_ARC_TO, "go"),
            (WIND_ARC_TO + 1, "watch"),
        ],
    )
    def test_offshore_wind_arc_edges(self, store, client, value, expected) -> None:
        """Wind outside the arc withholds a Go Call but not a Watch — the swell is still
        worth watching, which is the distinction ADR 0003 asks for."""
        assert status_for(store, client, {**GIANT, "wind_direction": value}) == expected

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(MAX_WIND_KMH, "go"), (MAX_WIND_KMH + 0.1, "watch")],
    )
    def test_wind_speed_boundary(self, store, client, value, expected) -> None:
        assert status_for(store, client, {**GIANT, "wind_speed": value}) == expected


class TestLeadTimeBands:
    """Each tier boundary, one day either side."""

    def test_confirmed_band_upper_edge(self, store, client) -> None:
        ingest(store, forecast_provider({"2026-02-10": GIANT, "2026-02-11": GIANT}, today=TODAY))
        issued = calls(client)

        assert issued["2026-02-10"]["lead_time_days"] == CONFIRMED_LEAD
        assert issued["2026-02-10"]["status"] == "confirmed"
        assert issued["2026-02-11"]["status"] == "go"

    def test_go_band_upper_edge(self, store, client) -> None:
        ingest(store, forecast_provider({"2026-02-16": GIANT, "2026-02-17": GIANT}, today=TODAY))
        issued = calls(client)

        assert issued["2026-02-16"]["lead_time_days"] == GO_LEAD
        assert issued["2026-02-16"]["status"] == "go"
        assert issued["2026-02-17"]["status"] == "watch"

    def test_today_is_confirmed(self, store, client) -> None:
        assert status_for(store, client, GIANT, date=TODAY) == "confirmed"


class TestWatchIsLooserThanGo:
    """ADR 0003 optimises a Watch for recall and a Go Call for precision. Gating both on
    every condition made them one rule with two names, differing only by lead time."""

    def test_a_building_swell_with_wrong_wind_still_raises_a_watch(self, store, client) -> None:
        assert status_for(store, client, {**GIANT, "wind_direction": 270}, date=FAR) == "watch"

    def test_wind_alone_never_earns_a_go_call(self, store, client) -> None:
        assert status_for(store, client, {**GIANT, "wind_direction": 270}, date=SOON) == "watch"

    def test_a_flat_swell_raises_nothing_however_perfect_the_wind(self, store, client) -> None:
        assert status_for(store, client, QUIET, date=FAR) == "none"

    def test_a_swell_failing_only_direction_raises_nothing(self, store, client) -> None:
        """Direction is a swell condition, so unlike wind it does gate the Watch."""
        assert status_for(store, client, {**GIANT, "swell_direction": 200}, date=FAR) == "none"


class TestCallContent:
    def test_a_call_is_judged_on_the_best_matching_hour_not_the_peak(self, store, client) -> None:
        """The biggest hour of the day is not always the one worth travelling for.

        Here 15:00 is the largest sea but blows onshore, while 09:00 is smaller and clean.
        Judging the peak alone returns no call and discards a real window; judging the
        best matching hour surfaces it. A fixture whose matching window *is* the peak
        cannot tell those apart, which is how this went unpinned.
        """
        ingest(
            store,
            forecast_provider(
                {SOON: {**GIANT, "significant_wave_height": MODEST_M}},
                today=TODAY,
                only_hours={SOON: (9, 10, 11)},
                peak_but_onshore={SOON: (15,)},
            ),
        )

        assert calls(client)[SOON]["status"] == "go"

    def test_a_bigger_hour_never_weakens_a_day_s_call(self, store, client) -> None:
        """A day is called at the best call any of its hours supports, so adding an hour
        can only ever strengthen it.

        The rule this replaces ranked hours by how many conditions they failed, which is
        tier-blind. A Watch ignores wind, so an 8m hour failing only period tied with a
        clean 3.5m hour failing only wind, won the tie on size, and took the day to no
        call — a bigger wave *removing* a Watch, destroying exactly the recall ADR 0003
        asks the Watch tier to protect, in code whose docstring claimed to have fixed it.
        """
        clean = {**GIANT, "significant_wave_height": MODEST_M, "wind_direction": 270}
        # Larger, offshore, but far too short-period to be worth travelling for.
        big_and_short = {**GIANT, "significant_wave_height": 8.0, "swell_period": 10.0}

        ingest(
            store,
            forecast_provider(
                {FAR: clean},
                today=TODAY,
                only_hours={FAR: tuple(range(0, 12))},
            ),
        )
        without_the_big_hour = calls(client)[FAR]["status"]

        ingest(
            store,
            forecast_provider(
                {FAR: clean},
                today=TODAY,
                only_hours={FAR: tuple(range(0, 12))},
                also_hours={FAR: (big_and_short, (15,))},
            ),
        )
        with_the_big_hour = calls(client)[FAR]["status"]

        assert without_the_big_hour == "watch"
        assert with_the_big_hour == "watch", "a bigger wave removed the Watch"

    def test_a_go_hour_outranks_a_watch_hour_on_the_same_day(self, store, client) -> None:
        """When one hour earns a Go Call and another only a Watch, the day is a Go Call.

        The tier ordering has to be pinned in both directions. Nothing else here compares
        two *different* statuses on one day, so inverting Go and Watch in the ordering
        table changed real behaviour with the suite still green.
        """
        onshore = {**GIANT, "wind_direction": 270}

        ingest(
            store,
            forecast_provider(
                {SOON: onshore},
                today=TODAY,
                only_hours={SOON: tuple(range(0, 12))},
                also_hours={SOON: (GIANT, (15,))},
            ),
        )

        assert calls(client)[SOON]["status"] == "go"

    def test_between_two_hours_earning_the_same_call_the_larger_sea_is_reported(
        self, store, client
    ) -> None:
        """The tie-break direction needs its own case: every hour in the test above that
        could win carried the same height, so reversing the tie-break changed nothing."""
        ingest(
            store,
            forecast_provider(
                {SOON: {**GIANT, "significant_wave_height": MODEST_M}},
                today=TODAY,
                only_hours={SOON: tuple(range(0, 12))},
                also_hours={SOON: ({**GIANT, "significant_wave_height": 6.0}, (15,))},
            ),
        )

        issued = calls(client)[SOON]

        assert issued["status"] == "go"
        assert issued["predicted_significant_wave_height"]["value"] == pytest.approx(
            predicted_for({**GIANT, "significant_wave_height": 6.0})
        )

    def test_a_call_reports_the_hour_that_earned_it(self, store, client) -> None:
        """The reasons and the height are the winning hour's. Reporting some other hour's
        would explain the call with conditions that did not produce it."""
        clean = {**GIANT, "significant_wave_height": MODEST_M, "wind_direction": 270}
        big_and_short = {**GIANT, "significant_wave_height": 8.0, "swell_period": 10.0}

        ingest(
            store,
            forecast_provider(
                {FAR: clean},
                today=TODAY,
                only_hours={FAR: tuple(range(0, 12))},
                also_hours={FAR: (big_and_short, (15,))},
            ),
        )

        issued = calls(client)[FAR]

        # 04:00 falls inside the clean window and carries the fixture's swell-height bonus,
        # so it is the clean hour with the largest predicted sea and the one reported.
        assert issued["predicted_significant_wave_height"]["value"] == pytest.approx(
            predicted_for(clean, swell_height=winning_hour_swell_height(clean))
        )
        assert issued["predicted_significant_wave_height"]["value"] != pytest.approx(
            predicted_for(big_and_short)
        ), "the call reported the big short-period hour it did not judge"
        assert any("swell period 16.5s" in reason for reason in issued["reasons"])

    def test_a_call_explains_itself(self, store, client) -> None:
        ingest(store, forecast_provider({SOON: GIANT}, today=TODAY))

        reasons = calls(client)[SOON]["reasons"]

        assert any("significant wave height" in reason for reason in reasons)
        assert any("swell period" in reason for reason in reasons)
        assert any("wind" in reason for reason in reasons)

    def test_a_call_says_how_much_of_the_day_matched(self, store, client) -> None:
        """A Go Call is the tier optimised for precision, and judging a day on its best
        matching hour lets a single clean hour earn one. Rather than invent a minimum
        window — ticket #12 owns threshold values — the call states the count, so a day
        resting on one hour cannot present itself as a day-long swell."""
        ingest(
            store,
            forecast_provider(
                {SOON: GIANT},
                today=TODAY,
                only_hours={SOON: (9, 10, 11)},
            ),
        )

        assert "3 of 24 forecast hours match every condition" in calls(client)[SOON]["reasons"]

    def test_a_quiet_day_says_no_hour_matched(self, store, client) -> None:
        ingest(store, forecast_provider({SOON: QUIET}, today=TODAY))

        assert "0 of 24 forecast hours match every condition" in calls(client)[SOON]["reasons"]

    def test_a_watch_counts_the_hours_it_was_actually_judged_on(self, store, client) -> None:
        """A Watch ignores wind on purpose, so counting hours that cleared *every*
        condition described something it was never judged against: a real Watch day read
        "0 of 24 forecast hours match every condition" beside its own Watch badge."""
        issued = status_for(
            store, client, {**GIANT, "wind_direction": 270}, date=FAR
        )  # onshore all day
        reasons = calls(client)[FAR]["reasons"]

        assert issued == "watch"
        assert "24 of 24 forecast hours carry the swell behind this Watch" in reasons
        assert not any("match every condition" in reason for reason in reasons)

    def test_a_call_reports_the_significant_wave_height_it_judged(self, store, client) -> None:
        """The reported height must derive from the Significant Wave Height, not the swell
        height — CONTEXT.md lists those as different variables, and the interface labels
        this one as the instrument's measure of the sea.

        Since #13 the model transforms that input rather than returning it, so equality
        with the input no longer states the property. The two readings differ in the
        fixture (`stub_hours` sets swell height to 0.8x Hs), so feeding the wrong one
        produces a different number — which is what the second assertion catches.
        """
        ingest(store, forecast_provider({SOON: GIANT}, today=TODAY))

        reported = calls(client)[SOON]["predicted_significant_wave_height"]
        as_swell_height = {
            **GIANT,
            "significant_wave_height": GIANT["significant_wave_height"] * 0.8,
        }

        assert reported["unit"] == "m"
        assert reported["value"] == pytest.approx(
            predicted_for(GIANT, swell_height=winning_hour_swell_height(GIANT))
        )
        assert reported["value"] != pytest.approx(
            predicted_for(as_swell_height, swell_height=winning_hour_swell_height(as_swell_height))
        ), "the swell height was judged as though it were the Significant Wave Height"

    @pytest.mark.parametrize("height", [3.0, 4.2, 7.5])
    def test_the_active_model_never_returns_a_face_height_multiple(
        self, store, client, height
    ) -> None:
        """The canyon's threefold amplification applies to Face Height, a different quantity.

        Until #13 the shipped model returned its input unchanged and this asserted equality,
        because a model with nothing fitted had no business moving the number at all — and
        asserting merely that it was "not enormous" had already let a 1.5x and even a 1.9x
        multiple through.

        #13 earns a correction, so equality is no longer the property. The danger it guarded
        is unchanged, though, and is if anything closer now that the number does move: a
        learned model drifting toward a Face-Height multiple would look like a better model
        right up until someone flew to Portugal for it. The shipped fit lands between 1.10x
        and 1.16x across this range — the reanalysis reads a little under the buoy near the
        canyon head — so this band admits the measured correction and nothing resembling the
        threefold one.

        The band is deliberately close to what was measured. An earlier 0.8-1.3 admitted a
        20% *reduction* from a model documented as scaling up, which is a direction the fit
        has never gone and would be a defect rather than drift.
        """
        ingest(
            store,
            forecast_provider({SOON: {**GIANT, "significant_wave_height": height}}, today=TODAY),
        )

        reported = calls(client)[SOON]["predicted_significant_wave_height"]["value"]

        assert 1.05 * height <= reported <= 1.25 * height, (
            f"the active model returned {reported}m for a {height}m sea, which is outside "
            "the range a Significant Wave Height correction can plausibly occupy"
        )

    def test_calls_declare_that_their_thresholds_are_calibrated(self, store, client) -> None:
        """Since #12 the thresholds are fitted, so the flag that drives the interface's
        caveat flips — and the interface drops the warning that these are a rule of thumb.

        The model name is asserted against `pipeline.DEFAULT_MODEL` rather than a literal.
        What matters here is that the store records the model that actually decided, so a
        deployment reading its own record is not misled; which model that is, is #13's
        decision and is pinned in `test_pipeline_model_switch.py`.
        """
        ingest(store, forecast_provider({SOON: GIANT}, today=TODAY))

        body = client.get("/api/conditions/forecast").json()

        assert body["calibrated"] is True
        assert body["amplification_model"] == DEFAULT_MODEL

    def test_the_forecast_states_what_the_calibration_rests_on(self, store, client) -> None:
        """#12 requires the interface to say how few Gold Days are behind these thresholds.

        Asserted on the API rather than only in the frontend because this is the half that
        has to survive a redesign: a UI that quietly stopped rendering the caveat would
        leave the user reading fitted-looking calls with no idea how wide the fit is.

        #39 took the fit from 9 Gold Days to 38. The caveat is still owed — 38 is a better
        number and still a small one — but it is no longer the same sentence, so the figure
        the interface states is pinned here rather than left to drift.
        """
        ingest(store, forecast_provider({SOON: GIANT}, today=TODAY))

        calibration = client.get("/api/conditions/forecast").json()["calibration"]

        assert calibration["gold_days_total"] == 38
        # Named as Big-Wave Seasons, not calendar years, and the two must not share one.
        # CONTEXT.md: a season is never a calendar year. Splitting on the calendar put
        # October-to-December 2023 in the fit and January-to-March 2024 in the held-out
        # half — one season in both, so the held-out split was not held out.
        assert calibration["fitted_on"] == "2011/12-2019/20"
        assert calibration["validated_on"] == "2020/21-2025/26"
        assert "analysis/calibration" in calibration["source"]


class TestCallsArePersisted:
    def test_the_api_serves_calls_it_did_not_compute(self, store, client) -> None:
        """ADR 0005 makes the API a reader and a Pipeline Run the only thing that runs a
        model. It also promises every prediction is retained, which is the record ticket
        #11 needs to score Go Call precision. Deriving calls per request kept none."""
        ingest(store, forecast_provider({SOON: GIANT}, today=TODAY))

        stored = store.calls()

        assert stored[SOON]["status"] == "go"
        assert stored[SOON]["issued_for_date"] == TODAY
        assert stored[SOON]["issued_at"]

    def test_a_stale_forecast_reports_the_lead_time_it_was_issued_at(self, store, client) -> None:
        """Lead Time is fixed when the call is issued, so a forecast left sitting cannot
        present an already-elapsed Go Call as fresh advice."""
        ingest(store, forecast_provider({"2020-01-05": GIANT}, today="2020-01-01"))

        assert calls(client)["2020-01-05"]["lead_time_days"] == 4
        assert store.calls()["2020-01-05"]["issued_for_date"] == "2020-01-01"

    def test_no_forecast_yet_is_reported_rather_than_faked(self, client) -> None:
        assert client.get("/api/conditions/forecast").status_code == 503

    def test_a_day_with_no_call_is_shown_without_one(self, store, client) -> None:
        """ADR 0005 asks that the site stay up and honest. A forecast whose calls are
        missing still has real days, hours and heights behind it, and failing the whole
        endpoint threw away everything ticket #5 delivered over something #6 added.

        A day carrying no call is distinct from one whose call is `none`: the first has
        not been judged, the second has been judged and found not worth travelling for.
        """
        store.record_run(
            observed_at=f"{TODAY}T00:00",
            latitude=39.5,
            longitude=-9.2,
            readings={},
            hours=stub_hours(SOON, GIANT),
            calls=[],
            run_id=store.begin_run(),
        )

        body = client.get("/api/conditions/forecast").json()

        assert body["days"], "days disappeared with their calls"
        assert all(day["call"] is None for day in body["days"])
        assert body["amplification_model"] is None
        # Nothing says these thresholds were fitted, so nothing may imply it.
        assert body["calibrated"] is False

    def test_every_forecast_day_is_listed_even_without_a_call(self, store, client) -> None:
        """Days were filtered to those the store held a call for, so a day missing from
        the call record vanished from the range — a hole a reader cannot tell from
        missing data, in an endpoint whose own docstring promises quiet days are kept."""
        store.record_run(
            observed_at=f"{TODAY}T00:00",
            latitude=39.5,
            longitude=-9.2,
            readings={},
            hours=stub_hours(TODAY, GIANT) + stub_hours(SOON, GIANT),
            calls=[
                {
                    "date": TODAY,
                    "issued_for_date": TODAY,
                    "status": "confirmed",
                    "lead_time_days": 0,
                    "reasons": ["every condition holds"],
                    "predicted_significant_wave_height": 4.2,
                    "unit": "m",
                    "amplification_model": "heuristic-baseline",
                    "calibrated": False,
                }
            ],
            run_id=store.begin_run(),
        )

        body = client.get("/api/conditions/forecast").json()
        shown = {day["date"]: day["call"] for day in body["days"]}

        assert list(shown) == [TODAY, SOON]
        assert shown[TODAY]["status"] == "confirmed"
        assert shown[SOON] is None


class TestCallsSurviveTheNextRun:
    """ADR 0005: "Every prediction the system has ever made is retained by construction."

    That record is what ticket #11 scores Go Call precision from, and the succession of
    calls about one date as it approaches is itself the measurement — a Watch at eleven
    days that became a Go Call at four and then a flat sea is a different failure from a
    day never called at all.

    Asserted through `Store.call_history` rather than HTTP, for the reason `raw_responses`
    documents: no endpoint exposes superseded calls, and retention cannot be observed
    through one that serves only the latest.
    """

    def test_a_second_run_does_not_erase_the_first(self, store) -> None:
        ingest(store, forecast_provider({FAR: GIANT}, today=TODAY))
        ingest(store, forecast_provider({FAR: QUIET}, today=TODAY))

        history = [call for call in store.call_history() if call["date"] == FAR]

        assert [call["status"] for call in history] == ["watch", "none"]

    def test_every_day_of_the_forecast_gets_a_call(self, store, client) -> None:
        """The behaviour that made retention optional dangerous. `record_run` once took
        `calls` as an optional argument, so a run that simply omitted them stored a
        forecast, reported success, and left the record ADR 0005 promises empty."""
        ingest(store, forecast_provider({SOON: GIANT}, today=TODAY))

        body = client.get("/api/conditions/forecast").json()

        assert body["days"]
        assert all(day["call"] is not None for day in body["days"])

    def test_the_model_reported_is_the_one_from_the_most_recent_run(
        self, store, client, monkeypatch
    ) -> None:
        """Which Amplification Model produced the current calls is a property of the run,
        and the store answers it by insertion order. The API once reconstructed "newest"
        by sorting on `issued_at`, a wall clock: adjusted backwards it inverts, and on a
        tie the winner is whichever row SQLite returned first.

        The clock is frozen here so both runs share a timestamp, and the *earlier* run
        writes the *earlier* date — so a sort on `issued_at` ties, falls back to date
        order, and lands on the older run's model.

        Two runs over one date cannot show this: the newest-per-date rule already
        collapses them to the right answer and the broken ordering looks correct by luck.
        Nor can two runs on an unfrozen clock, since microseconds almost never tie. This
        test survived both of those mistakes before it caught anything.
        """
        monkeypatch.setattr("nazarenow.store.now", lambda: f"{TODAY}T09:00:00+00:00")

        for date, name, calibrated in (
            (SOON, "heuristic-baseline", False),
            (FAR, "learned-v1", True),
        ):
            store.record_run(
                observed_at=f"{TODAY}T00:00",
                latitude=39.5,
                longitude=-9.2,
                readings={},
                hours=stub_hours(SOON, GIANT),
                calls=[
                    {
                        "date": date,
                        "issued_for_date": TODAY,
                        "status": "go",
                        "lead_time_days": 4,
                        "reasons": ["every condition holds"],
                        "predicted_significant_wave_height": 4.2,
                        "unit": "m",
                        "amplification_model": name,
                        "calibrated": calibrated,
                    }
                ],
                run_id=store.begin_run(),
            )

        body = client.get("/api/conditions/forecast").json()

        assert body["amplification_model"] == "learned-v1"
        assert body["calibrated"] is True

    def test_the_api_serves_the_most_recent_call_for_a_date(self, store, client) -> None:
        ingest(store, forecast_provider({FAR: GIANT}, today=TODAY))
        ingest(store, forecast_provider({FAR: QUIET}, today=TODAY))

        assert calls(client)[FAR]["status"] == "none"


class TestTheInterfaceIsRealDecides:
    """ADR 0001 and ADR 0006 promise the Heuristic Baseline can be swapped for a learned
    model in ticket #13 "without anything downstream changing". Nothing observable through
    HTTP can exercise that, because only one model is ever wired in — so these substitute
    another implementation of the interface directly.

    What they guard is real: the Decision Model once decided Watch-versus-Go by
    substring-matching the Heuristic Baseline's own English failure messages. Any model
    phrasing its failures differently matched nothing, and every day it judged became a
    Watch — the tier ADR 0003 optimises for recall, handed out on wording.
    """

    def test_a_model_wording_its_failures_differently_is_read_correctly(self) -> None:
        prediction = Prediction(
            significant_wave_height=6.0,
            conditions=(
                ConditionOutcome(Condition.SIGNIFICANT_WAVE_HEIGHT, True, "big enough"),
                ConditionOutcome(Condition.SWELL_PERIOD, True, "long enough"),
                # Worded without the words the old rule looked for.
                ConditionOutcome(Condition.SWELL_DIRECTION, False, "arriving from the south"),
                ConditionOutcome(Condition.WIND, True, "clean"),
            ),
        )

        # Direction is a swell condition, so it gates the Watch as surely as height does.
        assert decide(prediction, 11).status == "none"

    def test_a_model_that_never_judges_wind_cannot_earn_a_go_call(self) -> None:
        """The same collapse as above, one branch lower and found a pass later.

        Watch was fixed to name its conditions while Go and Confirmed still asked
        `matches_rule` — "did everything you judged hold?" — so a model that simply never
        judges wind satisfied it on any clean swell and issued a Go Call through an
        onshore gale. ADR 0003 exists to stop the two tiers becoming one rule with two
        names, and that is what this was.
        """
        prediction = Prediction(
            significant_wave_height=6.0,
            conditions=(
                ConditionOutcome(Condition.SIGNIFICANT_WAVE_HEIGHT, True, "big enough"),
                ConditionOutcome(Condition.SWELL_PERIOD, True, "long enough"),
                ConditionOutcome(Condition.SWELL_DIRECTION, True, "through the canyon"),
            ),
        )

        # The swell conditions all hold, so a Watch is right at range — but wind was never
        # judged, and a Go Call may not be handed out on a condition nobody checked.
        assert decide(prediction, 4).status == "watch"
        assert decide(prediction, 0).status == "none"

    def test_a_model_that_judges_nothing_earns_no_call(self) -> None:
        """`matches_rule` once read as "no failures", so a prediction carrying no
        conditions at all satisfied every tier — advice to book a flight, from silence."""
        assert decide(Prediction(significant_wave_height=9.0), 4).status == "none"

    def test_a_call_cannot_be_issued_for_a_date_before_its_forecast(self) -> None:
        """A negative Lead Time is a caller fault, not a case to fall through. The branch
        that returned silence here was unreachable — the pipeline measures Lead Time from
        the forecast's own first day — while its comment claimed it protected users from
        a stale forecast presenting an elapsed Go Call as fresh advice."""
        with pytest.raises(ValueError, match="negative"):
            decide(Prediction(significant_wave_height=9.0), -1)

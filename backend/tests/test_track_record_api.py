"""The track record endpoint: what it publishes, and what it refuses to imply.

Ticket #16. These tests are mostly about the seams rather than the arithmetic — the
arithmetic is `test_track_record.py`'s. What matters here is that the endpoint reads and
never computes, that both models arrive together, and that a fresh installation with no
history says so rather than presenting a reconstruction as an operating record.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from nazarenow.api import app, get_track_record, optional_store
from nazarenow.decision import Status
from nazarenow.store import Store
from nazarenow.track_record import DEFAULT_PATH, TrackRecordUnusable
from nazarenow.track_record import load as load_track_record


@pytest.fixture
def published_client(store: Store) -> Iterator[TestClient]:
    """A client serving the record this release ships, over a temporary store.

    The record is loaded explicitly rather than left to the cached default so the test
    cannot pass on a file another test happened to leave behind.
    """
    app.dependency_overrides[optional_store] = lambda: store
    app.dependency_overrides[get_track_record] = lambda: load_track_record(DEFAULT_PATH)
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestWhatItPublishes:
    def test_the_shipped_record_is_served(self, published_client: TestClient) -> None:
        response = published_client.get("/api/track-record")

        assert response.status_code == 200
        body = response.json()
        assert body["source"] == "analysis/track_record/publish.py"
        assert body["days"]

    def test_both_tiers_arrive_separately(self, published_client: TestClient) -> None:
        """#16: Watch and Go Call accuracy reported separately, never as one figure."""
        panel = published_client.get("/api/track-record").json()["held_out"]

        assert panel["watch_or_better"]["gold_days_called"] > 0
        assert panel["go_call"]["gold_days_called"] > 0
        assert panel["watch_or_better"]["days_flagged"] > panel["go_call"]["days_flagged"]

    def test_the_go_call_waste_figure_is_stated_rather_than_left_to_be_inverted(
        self, published_client: TestClient
    ) -> None:
        tier = published_client.get("/api/track-record").json()["held_out"]["go_call"]

        assert tier["wasted_upper_bound"] == pytest.approx(1 - tier["precision_lower_bound"])
        assert tier["days_wasted_upper_bound"] == tier["days_flagged"] - tier["gold_days_called"]

    def test_the_go_call_delivery_arrives_counted_over_the_days_it_flagged(
        self, published_client: TestClient
    ) -> None:
        """#83's counterweight to the waste figure, at the seam.

        The two are rendered as statements about one set of days, so the denominator is the
        assertion: a delivery counted over a different set would let the page say "97 of 43"
        beside "at most 34 of 43 wasted" with both halves looking ordinary.
        """
        tier = published_client.get("/api/track-record").json()["held_out"]["go_call"]
        delivered = tier["delivered"]

        assert delivered is not None
        assert all(step["of_days"] == tier["days_flagged"] for step in delivered["above"])
        assert all(step["days"] <= tier["days_flagged"] for step in delivered["above"])
        assert delivered["minimum_m"] <= delivered["median_m"] <= delivered["maximum_m"]

    def test_the_delivery_shares_are_divided_here_and_not_by_the_interface(
        self, published_client: TestClient
    ) -> None:
        """Same rule as every other rate in this response. The interface holding two counts
        and dividing them is a second implementation of a published figure."""
        delivered = published_client.get("/api/track-record").json()["held_out"]["go_call"][
            "delivered"
        ]

        for step in delivered["above"]:
            assert step["share"] == pytest.approx(step["days"] / step["of_days"])

    def test_both_tiers_carry_a_delivery(self, published_client: TestClient) -> None:
        """Since #87, which is what made the Watch tier publishable.

        It shipped with the Go Call alone because the two reports the record was assembled
        from disagreed about how many Watch days there were — 199 against 193 — and the page
        renders the delivered figure and the waste figure as statements about one set of days.
        The Watch tier is where the pairing matters most: its waste figure reads 94%, on a
        tier that never flagged a day the sea stayed below 2.72 m.

        That a tier *may* carry none is still true and still exercised, in
        `test_track_record.py`. It is no longer true of anything this release publishes, so
        asserting it here would pin the page to a state #87 exists to have left.
        """
        panels = published_client.get("/api/track-record").json()

        for span in ("held_out", "full_record"):
            for tier in ("watch_or_better", "go_call"):
                delivered = panels[span][tier]["delivered"]
                assert delivered is not None, f"{span} {tier} carries no delivered sea"
                assert all(
                    step["of_days"] == panels[span][tier]["days_flagged"]
                    for step in delivered["above"]
                )

    def test_the_range_calibration_arrives_with_both_subsets_at_every_lead_time(
        self, published_client: TestClient
    ) -> None:
        """#94. The interface prints a range in metres and this is the measurement of it.

        Both subsets are asserted at every Lead Time because the big-swell rows are the sea a
        Go Call is issued on and read kinder than the whole; a response able to carry one of
        them alone is a page able to publish the kinder number as the finding.
        """
        calibration = published_client.get("/api/track-record").json()["range_calibration"]

        assert 0 < calibration["claimed"] < 1
        assert calibration["leads"]
        for lead in calibration["leads"]:
            for subset in ("all_hours", "big_swell"):
                measured = lead[subset]
                assert measured["hours"] > 0, f"{lead['lead_days']} d {subset}"
                assert 0 <= measured["covered"] <= 1
                assert measured["median_width_m"] > 0
            assert lead["big_swell"]["hours"] <= lead["all_hours"]["hours"]

    def test_the_width_the_outcomes_asked_for_is_divided_here_and_not_by_the_interface(
        self, published_client: TestClient
    ) -> None:
        """Same rule as every other derived figure in this response."""
        calibration = published_client.get("/api/track-record").json()["range_calibration"]

        for lead in calibration["leads"]:
            for subset in ("all_hours", "big_swell"):
                measured = lead[subset]
                assert measured["justified_width_m"] == pytest.approx(
                    measured["median_width_m"] * measured["widening_factor"]
                )

    def test_the_two_qualifications_travel_with_the_figures(
        self, published_client: TestClient
    ) -> None:
        """Without them the table reads as a calibration certificate.

        One says the shipped range is wider than the one measured — every distribution scored
        was built without the wave models' disagreement term, which only widens. The other
        says the whole table rests on one partial Big-Wave Season with a single confirmed
        giant day in it. Neither is derivable from the numbers beside them.
        """
        calibration = published_client.get("/api/track-record").json()["range_calibration"]

        assert calibration["understates_because"].strip()
        assert calibration["rests_on"].strip()

    def test_no_verdict_on_the_range_is_sent_over_the_wire(
        self, published_client: TestClient
    ) -> None:
        """The direction is derived by whatever renders this, never asserted in the schema.

        #82 exists to narrow this distribution. A field saying "too wide" would outlive the
        refit that makes it false — the failure #76 and ADR 0014 are both about. What travels
        is the claim, the measurement, and the two qualifications.
        """
        calibration = published_client.get("/api/track-record").json()["range_calibration"]

        assert set(calibration) == {"claimed", "understates_because", "rests_on", "leads"}
        assert set(calibration["leads"][0]["all_hours"]) == {
            "hours",
            "covered",
            "median_width_m",
            "justified_width_m",
            "widening_factor",
        }

    def test_every_band_carries_both_models(self, published_client: TestClient) -> None:
        """ADR 0006, enforced at the published boundary as well as in the file.

        Checked on both tables rather than one: the served table is assembled from a
        different report and is where a missing column would first appear.
        """
        body = published_client.get("/api/track-record").json()

        for table in ("scored", "served"):
            assert body[table], f"{table} table is empty"
            for band in body[table]:
                assert isinstance(band["baseline_mae_m"], float)
                assert isinstance(band["learned_mae_m"], float)
                assert band["gain_m"] == pytest.approx(
                    band["baseline_mae_m"] - band["learned_mae_m"]
                )

    def test_the_served_table_is_the_corrected_one(self, published_client: TestClient) -> None:
        """#52 found the previously published served table was partly measuring its own
        generator, and the two rows it moved are the two that flattered the learned model.

        Pinned here because the failure is invisible: reading the other generator's rows
        publishes eight plausible numbers, and the two wrong ones are the only ones on the
        page that would say the learned model is better on an ordinary day.

        **The values moved in #58 and the pin is weaker for it.** Refitting the height
        Translation on every overlapping hour removed the distortion at its source, so the two
        generators now sit 0.002 m apart rather than 0.11 m. The assertion still catches the
        wiring mistake — 0.002 m is four times the tolerance — but it no longer separates a
        flattering number from an honest one, because there is no longer a flattering one to
        separate. `-0.0774` and `-0.1258` were the pre-#58 values.
        """
        served = {
            band["name"]: band
            for band in published_client.get("/api/track-record").json()["served"]
        }

        assert served["all hours"]["gain_m"] == pytest.approx(-0.0162, abs=5e-4)
        assert served["under 2 m"]["gain_m"] == pytest.approx(-0.0350, abs=5e-4)
        # And the finding that survives it: still decisively better on the days that matter.
        assert served["6 m and above"]["gain_m"] > 0.3

    def test_the_two_qualified_figures_arrive_qualified(self, published_client: TestClient) -> None:
        """#52 said not to quote the served aggregate as robust, and the amplification
        README says the Gold Day figure should never be quoted without the five days behind
        it. Both are strong-looking numbers a page would otherwise publish bare."""
        body = published_client.get("/api/track-record").json()

        scored = {band["name"]: band for band in body["scored"]}
        served = {band["name"]: band for band in body["served"]}

        assert "5 Gold Days" in scored["Gold Day hours"]["caveat"]
        assert "Not robust" in served["Combined Sea 3 m and above"]["caveat"]
        assert served["6 m and above"]["caveat"] is None

    def test_the_gold_day_basis_is_stated_and_small(self, published_client: TestClient) -> None:
        body = published_client.get("/api/track-record").json()

        assert body["gold_days_total"] == body["gold_days_fitted"] + body["gold_days_validated"]
        assert body["held_out"]["gold_days"] == body["gold_days_validated"]

    def test_days_carry_the_call_and_what_the_sea_did(self, published_client: TestClient) -> None:
        days = published_client.get("/api/track-record").json()["days"]

        assert all(day["gold_day"] or day["call"] == Status.GO for day in days), (
            "the day list should hold the days that mattered and the days it told someone "
            "to travel for, and nothing else"
        )
        assert [day["date"] for day in days] == sorted(day["date"] for day in days)
        missed = [day for day in days if day["gold_day"] and day["call"] == Status.NONE]
        assert missed, "the record must show the Gold Days it missed, not only the ones it caught"

    def test_the_panels_name_what_produced_them(self, published_client: TestClient) -> None:
        """A backtest presented without saying so reads as an operating history."""
        body = published_client.get("/api/track-record").json()

        assert body["held_out"]["basis"] == "Hindcast"
        assert body["full_record"]["basis"] == "Hindcast"


class TestTheIssuedRecord:
    def test_a_fresh_installation_reports_nothing_issued(
        self, published_client: TestClient
    ) -> None:
        """The ordinary state of a new deployment, and it must not read as a record of
        success. Nulls rather than a zero-length history with timestamps."""
        issued = published_client.get("/api/track-record").json()["issued"]

        assert issued == {
            "calls_issued": 0,
            "dates_covered": 0,
            "go_calls_issued": 0,
            "first_issued_at": None,
            "last_issued_at": None,
        }

    def test_retained_calls_are_counted(self, published_client: TestClient, store: Store) -> None:
        """The counts come from the retained record — every call ever made, including
        superseded ones — which is the only thing this system has that was issued in
        advance rather than reconstructed."""
        store.record_run(
            observed_at="2026-08-04T00:00",
            latitude=39.5,
            longitude=-9.2,
            readings={},
            hours=[],
            calls=[
                {
                    "date": "2026-08-05",
                    "issued_for_date": "2026-08-05",
                    "status": "go",
                    "lead_time_days": 4,
                    "reasons": ["every condition holds"],
                    "predicted_significant_wave_height": 4.2,
                    "unit": "m",
                    "amplification_model": "learned-amplification",
                    "calibrated": True,
                    "model_agreement": "agreed",
                    "go_call_withheld": False,
                }
            ],
            model_hours=[],
            spreads=[],
            run_id=store.begin_run(),
        )
        history = store.call_history()

        issued = published_client.get("/api/track-record").json()["issued"]

        assert issued["calls_issued"] == len(history) == 1
        assert issued["dates_covered"] == len({call["issued_for_date"] for call in history})
        assert issued["go_calls_issued"] == 1
        assert issued["first_issued_at"] is not None

    def test_the_published_record_is_served_even_with_an_empty_store(
        self, published_client: TestClient
    ) -> None:
        """Unlike the forecast endpoints, this one does not 503 on an empty store.

        The record is a property of the release. Someone deciding whether to trust the
        system should not be told there is no track record because nothing was ingested
        this morning.
        """
        assert published_client.get("/api/track-record").status_code == 200

    def test_an_unopenable_store_costs_the_issued_section_and_nothing_else(self) -> None:
        """A misconfigured database must not take down the page a reader consults to decide
        whether to trust the system — that is the one page whose absence looks exactly like
        a system with nothing to show for itself.

        Null rather than a section of zeros. "0 calls issued" for a store nobody could read
        is the more flattering of the two possible truths, invented.
        """
        app.dependency_overrides[optional_store] = lambda: None
        app.dependency_overrides[get_track_record] = lambda: load_track_record(DEFAULT_PATH)
        try:
            response = TestClient(app).get("/api/track-record")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        body = response.json()
        assert body["issued"] is None
        assert body["days"], "the published record must survive the store being unreadable"
        assert body["held_out"]["go_call"]["days_flagged"] > 0


class TestFailure:
    def test_an_unusable_record_is_a_described_500(self, store: Store) -> None:
        """Not a silent empty page. A track record that renders with nothing on it is
        indistinguishable from a system with nothing to show for itself."""

        def broken() -> None:
            raise TrackRecordUnusable("the file moved")

        app.dependency_overrides[optional_store] = lambda: store
        app.dependency_overrides[get_track_record] = broken
        try:
            response = TestClient(app, raise_server_exceptions=False).get("/api/track-record")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 500
        assert "the file moved" in response.json()["detail"]

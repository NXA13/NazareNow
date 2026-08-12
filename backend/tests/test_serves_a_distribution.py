"""A Pipeline Run decides on a Predictive Distribution, stores it, and serves it.

Ticket #15, and the step where the ticket finally reaches a user. Everything before this
built the distribution and taught `decide` to consume one; the live pipeline still called
`decide` with nothing, so no deployed call had moved.

Driven through the HTTP API like the rest of `test_calls.py`, and for the same reason: every
property below is observable there, so reaching past it would be a seam breach with no
justification.

**The hour matters, and it is the trap this file exists to catch.** A day is called on its
best *matching* hour, which is not its median hour and not its peak. `day_spread` stores the
median hour's disagreement, `Call.model_agreement` already had to be stored rather than
derived because of that mismatch, and a range built for the wrong hour would describe a
moment that did not produce the call sitting beside it — while looking entirely ordinary.

**A distribution is not built for every hour, and the reason is cost rather than taste.**
Measured, one costs 22.9 ms, so all 216 hours of a real forecast would be 4.9 s. That is
comfortably inside a three-hour cycle and would still be the wrong shape: the only hours
whose distribution can change a *decision* are the ones already clearing every Go Call
condition, because that is the sole branch `_height_probable_enough` gates. So those are built
before the ranking, the winner gets one afterwards for the range a user reads, and the rest
are never built at all.
"""

from __future__ import annotations

import json
import time

from helpers import GIANT, forecast_provider, ingest
from nazarenow.cycle import INTERVAL_SECONDS
from nazarenow.distribution import DRAWS, ErrorBudget
from nazarenow.forecast_error import PATH_VARIABLE

TODAY = "2026-02-09"
SOON = "2026-02-12"
"""Three days out: inside the Go Call band and inside the measured archive."""

FAR = "2026-02-19"
"""Ten days out: past the archive's seven days, so nothing was measured about it."""


def call_for(client, date: str) -> dict:
    body = client.get("/api/conditions/forecast").json()
    return next(day for day in body["days"] if day["date"] == date)["call"]


def widened(tmp_path, factor: float) -> str:
    """The shipped profile with every drift band multiplied, written where the loader looks.

    Scaling the real file rather than writing a synthetic one keeps every other field —
    the bias, the regime bar, the measured depth — exactly as shipped, so what the test
    changes is the one quantity it is about.
    """
    from nazarenow.forecast_error import DEFAULT_PATH

    body = json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))
    for bands in body["by_lead_time"].values():
        for band in bands.values():
            band["drift"] *= factor
    path = tmp_path / f"forecast_error_x{factor}.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return str(path)


class TestTheUserIsGivenARangeRatherThanANumber:
    """#15's fourth and fifth criteria, at the point they reach a reader."""

    def test_a_call_carries_a_plausible_range_in_metres(self, store, client) -> None:
        ingest(store, forecast_provider({SOON: GIANT}, today=TODAY))

        call = call_for(client, SOON)

        assert call["plausible_range"]["unit"] == "m"
        assert call["plausible_range"]["low"] < call["plausible_range"]["high"]

    def test_the_range_brackets_the_height_the_call_reports(self, store, client) -> None:
        """The range is about the same prediction the call states, not a second opinion.

        A range that did not contain its own headline number would be two answers to one
        question, and the user would have no way to tell which the system meant.
        """
        ingest(store, forecast_provider({SOON: GIANT}, today=TODAY))

        call = call_for(client, SOON)
        predicted = call["predicted_significant_wave_height"]["value"]

        assert call["plausible_range"]["low"] < predicted < call["plausible_range"]["high"]

    def test_the_chance_of_clearing_the_height_bar_is_stated(self, store, client) -> None:
        ingest(store, forecast_provider({SOON: GIANT}, today=TODAY))

        assert 0.0 <= call_for(client, SOON)["height_bar_probability"] <= 1.0

    def test_a_giant_day_is_likelier_to_clear_the_bar_than_a_quiet_one(self, store, client):
        """Otherwise the number is present and means nothing."""
        ingest(store, forecast_provider({SOON: GIANT}, today=TODAY))

        giant = call_for(client, SOON)["height_bar_probability"]
        quiet = call_for(client, "2026-02-13")

        assert quiet is None or giant > quiet["height_bar_probability"]


class TestBeyondTheArchiveTheSystemSaysSo:
    """#15's sixth criterion: far-out dates are visibly more cautious."""

    def test_a_date_inside_the_archive_reports_measured_uncertainty(self, store, client):
        ingest(store, forecast_provider({SOON: GIANT}, today=TODAY))

        assert call_for(client, SOON)["uncertainty_measured"] is True

    def test_a_date_past_seven_days_reports_that_nothing_was_measured(self, store, client):
        ingest(store, forecast_provider({FAR: GIANT}, today=TODAY))

        assert call_for(client, FAR)["uncertainty_measured"] is False

    def test_the_far_date_carries_the_wider_range(self, store, client) -> None:
        """`measured=False` is a label; this is the substance behind it."""
        ingest(store, forecast_provider({SOON: GIANT, FAR: GIANT}, today=TODAY))

        near = call_for(client, SOON)["plausible_range"]
        far = call_for(client, FAR)["plausible_range"]

        assert (far["high"] - far["low"]) > (near["high"] - near["low"])


class TestTheRangeDescribesTheHourTheCallRests_On:
    def test_the_range_follows_the_deciding_hour_rather_than_the_days_median(
        self, store, client
    ) -> None:
        """The mismatch `Call.model_agreement` already exists to record.

        One hour of the day carries a much larger sea than the rest. That hour earns the
        call and its height is what the call reports, so the range has to sit around *it* —
        a range built from the day's median hour would be centred metres lower while
        looking exactly as authoritative.
        """
        huge = GIANT | {"significant_wave_height": 7.0}
        ingest(
            store,
            forecast_provider({SOON: huge}, today=TODAY, only_hours={SOON: (9,)}),
        )

        call = call_for(client, SOON)
        predicted = call["predicted_significant_wave_height"]["value"]

        assert predicted > 5.0, "the fixture no longer produces a standout hour"
        assert call["plausible_range"]["low"] < predicted < call["plausible_range"]["high"]


class TestAWiderErrorProfileMakesTheSystemMoreCautious:
    """#15's final criterion, end to end rather than at the unit seam.

    `test_distribution.py` proves a wider profile widens the distribution and
    `test_decides_on_a_distribution.py` proves an uncertain distribution withholds a Go
    Call. Neither shows the running system doing it, which is what the criterion asks for.
    """

    def test_a_wider_profile_widens_the_range_a_user_reads(
        self, store, client, tmp_path, monkeypatch
    ) -> None:
        ingest(store, forecast_provider({SOON: GIANT}, today=TODAY))
        shipped = call_for(client, SOON)["plausible_range"]

        monkeypatch.setenv(PATH_VARIABLE, widened(tmp_path, 6.0))
        ingest(store, forecast_provider({SOON: GIANT}, today=TODAY))
        wide = call_for(client, SOON)["plausible_range"]

        assert (wide["high"] - wide["low"]) > (shipped["high"] - shipped["low"])

    def test_a_wide_enough_profile_withholds_the_go_call(
        self, store, client, tmp_path, monkeypatch
    ) -> None:
        """And says which of the two refusals happened. The models disagreeing about a
        swell and the forecast being too uncertain to book on are different facts, and a
        reader who is told only "Watch" cannot tell them apart."""
        ingest(store, forecast_provider({SOON: GIANT}, today=TODAY))
        assert call_for(client, SOON)["status"] == "go"

        monkeypatch.setenv(PATH_VARIABLE, widened(tmp_path, 40.0))
        ingest(store, forecast_provider({SOON: GIANT}, today=TODAY))
        call = call_for(client, SOON)

        assert call["status"] == "watch"
        assert call["go_call_withheld_for_uncertainty"] is True
        assert call["go_call_withheld"] is False, "the models agreed; only the width refused"
        assert any("too uncertain" in reason for reason in call["reasons"])


class TestAPredictionCanBeWatchedMoving:
    """#15's eighth criterion: how a prediction has shifted across successive runs.

    Served from the record rather than accumulated by the interface, which has no memory —
    a page a traveller opens once every few days cannot have watched the runs in between.
    The store keeps every call ever made (ADR 0005) so this can be answered from what
    happened rather than from what somebody's browser happened to see.
    """

    def test_the_first_run_about_a_date_has_nothing_to_compare_against(self, store, client):
        """Empty, not a series of one. A date compared against itself would draw a shift of
        exactly zero and read as "settled" on a forecast nobody has revisited."""
        ingest(store, forecast_provider({SOON: GIANT}, today=TODAY))

        assert call_for(client, SOON)["previous_runs"] == []

    def test_a_later_run_carries_what_the_earlier_one_said(self, store, client) -> None:
        smaller = GIANT | {"significant_wave_height": 3.6}
        ingest(store, forecast_provider({SOON: smaller}, today=TODAY))
        was = call_for(client, SOON)["predicted_significant_wave_height"]["value"]

        ingest(store, forecast_provider({SOON: GIANT | {"significant_wave_height": 5.4}}, TODAY))
        call = call_for(client, SOON)

        assert len(call["previous_runs"]) == 1
        assert call["previous_runs"][0]["predicted_significant_wave_height"]["value"] == was
        assert call["predicted_significant_wave_height"]["value"] > was, "the swell built"

    def test_the_current_call_is_not_listed_among_the_ones_it_superseded(self, store, client):
        """Sending it twice would let an interface draw a date as having shifted from
        itself, which is the one movement that is always spurious."""
        for _ in range(3):
            ingest(store, forecast_provider({SOON: GIANT}, today=TODAY))

        call = call_for(client, SOON)
        issued = [run["issued_at"] for run in call["previous_runs"]]

        assert len(issued) == 2
        assert issued == sorted(issued), "the succession must read oldest first"

    def test_an_earlier_run_carries_its_own_range_and_lead_time(self, store, client) -> None:
        """The range, because a narrowing band is the shift worth seeing most; the Lead Time,
        because a range narrowing as a date approaches is the forecast working, and the same
        narrowing at a fixed Lead Time would be something else entirely."""
        ingest(store, forecast_provider({SOON: GIANT}, today=TODAY))
        ingest(store, forecast_provider({SOON: GIANT}, today=TODAY))

        earlier = call_for(client, SOON)["previous_runs"][0]

        assert earlier["plausible_range"]["low"] < earlier["plausible_range"]["high"]
        assert earlier["lead_time_days"] == call_for(client, SOON)["lead_time_days"]


class TestARefusedGoCallIsNotLostToABiggerHour:
    """The tie-break `test_calls.py` already protects, in the dimension #15 added.

    `derive_calls` ranks a day's hours by status, then by whether a Go Call was *withheld*,
    then by size — because a day whose conditions supported a Go Call somebody refused is a
    different day from one that failed a condition outright, and it is the more useful of the
    two to explain. Without the middle term a clean window under a bigger onshore peak loses
    the day to the peak, and the refusal disappears from the record.

    #15 introduced a second way to refuse one. An hour the *width* refused is a day whose
    conditions supported a Go Call just as much as one the forecasters refused, so it has to
    count in the same place — otherwise the ticket reproduces the exact defect the existing
    tie-break exists to prevent, one term along.
    """

    def test_an_hour_the_width_refused_outranks_a_taller_hour_that_never_earned_one(
        self, store, client, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.setenv(PATH_VARIABLE, widened(tmp_path, 40.0))
        ingest(
            store,
            forecast_provider({SOON: GIANT}, today=TODAY, peak_but_onshore={SOON: (12,)}),
        )

        call = call_for(client, SOON)

        assert call["status"] == "watch"
        assert call["go_call_withheld_for_uncertainty"] is True, (
            "the day lost its refused hour to the taller onshore peak"
        )
        assert any("too uncertain" in reason for reason in call["reasons"])


class TestTheEstimateDegradesRatherThanFailing:
    def test_an_unreachable_ensemble_still_produces_a_range(self, store, client) -> None:
        """ADR 0003: a provider being unavailable degrades the uncertainty estimate rather
        than the prediction. The archive terms are shipped as data and owe nothing to the
        network, so the range survives losing the ensemble entirely."""
        ingest(store, forecast_provider({SOON: GIANT}, today=TODAY, ensemble_status=500))

        call = call_for(client, SOON)

        assert call["plausible_range"]["high"] > call["plausible_range"]["low"]
        assert call["model_agreement"] == "unmeasured"


class TestThePipelineRunStaysInsideTheForecastCycle:
    """#15's ninth criterion, asserted in the backend rather than modelled in a CSV.

    `analysis/amplification_model/output/inference_cost.csv` modelled 500 draws across 14
    dates. A Pipeline Run scores many hours per date, so the modelled shape was not the
    served one and nothing in the backend checked the difference.
    """

    def test_a_run_builds_exactly_the_distributions_its_shape_calls_for(self, store) -> None:
        """The deterministic statement of criterion 9, pinned exactly rather than bounded.

        An inequality was the first attempt and it was worth almost nothing: at four times
        the real figure it admitted a doubled `DRAWS`, a doubled hour count, and most of the
        regressions it was written to catch. This repo pins shipped numbers as literals for
        the same reason `test_calls.py` gives — a bound that moves with the thing it measures
        pins nothing.

        The fixture is 14 dates of 24 hours, which is already larger than the ~216 hours a
        real forecast returns, so a run inside this budget is inside it in production too.
        """
        built = 0
        original = ErrorBudget.distribution

        def counted(self, *args, **kwargs):
            nonlocal built
            built += 1
            return original(self, *args, **kwargs)

        ErrorBudget.distribution = counted
        try:
            ingest(store, forecast_provider({SOON: GIANT}, today=TODAY))
        finally:
            ErrorBudget.distribution = original

        # Every hour of SOON clears every Go Call condition, so all 24 are priced before the
        # ranking; the other 13 dates are quiet and pay for their winning hour alone. A run
        # building one per hour would be 336.
        assert built == 24 + 13

    def test_the_run_stays_inside_the_cycle_at_that_shape(self, store) -> None:
        """Criterion 9 itself, as arithmetic rather than as a stopwatch.

        The cost is `DRAWS` model evaluations per distribution, and
        `analysis/amplification_model/output/inference_cost.csv` measures the point model at
        tens of microseconds. Projecting the two against the cycle states the criterion
        without depending on how loaded the machine running the suite happens to be — a
        wall-clock bound tight enough to be informative would flake on CI, and one loose
        enough not to flake says nothing.

        Deliberately generous about the per-evaluation cost. The published figure is 13 µs;
        this allows 200, so the claim survives a machine an order of magnitude slower than
        the one the CSV was written on and still fails if the *shape* goes wrong.
        """
        hours_in_a_real_run = 216
        # The worst shape the pricing rule permits: every hour of every date clearing every
        # Go Call condition, so none of them is skipped.
        worst_case = hours_in_a_real_run * DRAWS * 200e-6

        # A tenth of the cycle, not the whole of it. A Pipeline Run shares the cycle with
        # three provider requests and their retries, and a run that only just fits leaves
        # nothing for the fetching that has to happen first.
        assert worst_case < INTERVAL_SECONDS / 10, (
            f"{worst_case:.0f}s of a {INTERVAL_SECONDS}s cycle"
        )

    def test_a_full_run_does_not_hang(self, store) -> None:
        """The stopwatch, claiming only what a stopwatch can claim.

        CI machines vary by more than an order of magnitude, so this catches a run that
        hangs or has gone quadratic and nothing subtler. The two tests above are where the
        shape and the cost are actually pinned.
        """
        started = time.perf_counter()
        ingest(store, forecast_provider({SOON: GIANT, FAR: GIANT}, today=TODAY))
        elapsed = time.perf_counter() - started

        assert elapsed < INTERVAL_SECONDS / 20


def test_every_date_carries_a_range_including_the_quiet_ones(store, client) -> None:
    """Not only the days that earned a call.

    #15's eighth criterion asks a user to watch a prediction move between Pipeline Runs, and
    the movement worth seeing most is a swell arriving where there was nothing. A date given
    a range only once it already earns a Watch would appear from nowhere already formed.
    """
    ingest(store, forecast_provider(today=TODAY))

    body = client.get("/api/conditions/forecast").json()

    assert body["days"], "the fixture produced no days"
    for day in body["days"]:
        assert day["call"]["plausible_range"]["high"] > 0, f"{day['date']} carries no range"

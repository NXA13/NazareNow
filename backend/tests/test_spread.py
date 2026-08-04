"""Model Spread: agreement is confidence, disagreement is doubt, and silence is neither.

ADR 0003 makes disagreement between independent wave models the system's only uncertainty
estimate, so these tests guard the two ways that number can lie: by counting one
organisation's opinion twice, and by reporting confident agreement when nobody answered.
"""

from __future__ import annotations

import pytest

from nazarenow.spread import (
    MINIMUM_PROVIDERS,
    ORGANISATIONS,
    PROVIDERS,
    arc_of,
    by_provider,
    derive,
    for_day,
    spread_of,
)


def test_agreeing_providers_yield_a_narrow_spread():
    """#8: agreeing stubbed providers must produce narrow spread."""
    agreed = derive(
        "swell_height",
        {"meteofrance_wave": 3.10, "dwd_gwam": 3.12, "ncep_gfswave025": 3.11},
    )

    assert agreed is not None
    assert agreed.value == pytest.approx(0.02, abs=1e-9)
    assert agreed.providers == ("DWD", "MeteoFrance", "NCEP")
    assert not agreed.degraded


def test_disagreeing_providers_yield_a_wide_spread():
    """#8: disagreeing stubbed providers must produce wide spread."""
    scattered = derive(
        "swell_height",
        {"meteofrance_wave": 2.0, "dwd_gwam": 4.5, "ncep_gfswave025": 3.1},
    )

    assert scattered is not None
    assert scattered.value == pytest.approx(2.5, abs=1e-9)
    assert scattered.providers == ("DWD", "MeteoFrance", "NCEP")


def test_one_provider_failing_still_produces_a_usable_spread():
    """#8: a provider being unavailable degrades Model Spread rather than failing the run."""
    degraded = derive("swell_height", {"meteofrance_wave": 3.0, "dwd_gwam": 3.6})

    assert degraded is not None
    assert degraded.value == pytest.approx(0.6, abs=1e-9)
    assert degraded.providers == ("DWD", "MeteoFrance")
    assert degraded.degraded, "a spread resting on two of three organisations must say so"


def test_a_provider_returning_null_is_not_an_opinion():
    """A member that answered with nothing must not be counted as having answered."""
    assert derive("swell_height", {"meteofrance_wave": 3.0, "dwd_gwam": None}) is None


def test_a_single_organisation_carries_no_spread_rather_than_zero():
    """Zero here would be indistinguishable from perfect agreement.

    Both DWD models reporting is still one organisation, so there is nothing to difference.
    Returning 0.0 would read as maximum confidence at exactly the moment the system knows
    least, which is the inversion ADR 0003's uncertainty estimate exists to prevent.
    """
    assert derive("swell_height", {"dwd_ewam": 3.0, "dwd_gwam": 3.9}) is None
    assert derive("swell_height", {"meteofrance_wave": 3.0}) is None
    assert derive("swell_height", {}) is None


def test_each_organisation_votes_exactly_once():
    """Five identifiers are three organisations, and the spread must reflect three.

    Counted per model instead, DWD and NCEP would carry two votes each and the range below
    would be 0.6 rather than 0.5 — the ensemble looking more corroborated than it is.
    """
    readings = {
        "meteofrance_wave": 1.0,
        "dwd_ewam": 1.2,
        "dwd_gwam": 1.4,
        "ncep_gfswave025": 0.8,
        "ncep_gfswave016": 0.8,
    }

    opinions = by_provider(readings, "swell_height")

    assert sorted(opinions) == ORGANISATIONS
    assert opinions["DWD"] == pytest.approx(1.3), "an organisation votes its models' median"
    assert spread_of(list(opinions.values())) == pytest.approx(0.5)
    assert spread_of(list(readings.values())) == pytest.approx(0.6), "the double-counted range"


def test_a_member_dropping_out_leaves_its_organisation_represented():
    """The property that keeps spread comparable across Lead Times.

    `dwd_ewam` stops at about three days while `dwd_gwam` runs to seven. If losing EWAM lost
    DWD, the ensemble would shrink from three organisations to two partway through the
    forecast range and the spread would step for a reason that is not about the weather.
    """
    full = {"meteofrance_wave": 1.0, "dwd_ewam": 1.2, "dwd_gwam": 1.4, "ncep_gfswave025": 0.8}

    without_ewam = {model: value for model, value in full.items() if model != "dwd_ewam"}

    assert sorted(by_provider(without_ewam, "swell_height")) == ORGANISATIONS
    assert derive("swell_height", without_ewam).degraded is False


def test_a_model_off_the_roster_is_refused_rather_than_given_a_vote():
    """An unknown identifier would otherwise silently change the ensemble's size."""
    with pytest.raises(KeyError, match="roster"):
        by_provider({"meteofrance_wave": 1.0, "some_new_model": 2.0}, "swell_height")


def test_spread_needs_two_opinions():
    with pytest.raises(ValueError, match="not an ensemble"):
        spread_of([1.0])


def test_the_roster_maps_every_model_to_an_organisation():
    """A model added to the roster without an organisation would crash mid-run."""
    assert all(PROVIDERS.values())
    assert len(ORGANISATIONS) >= MINIMUM_PROVIDERS


def test_a_spread_carries_the_two_opinions_it_was_measured_between():
    """The endpoints, not only the gap, because the gap alone cannot be displayed honestly.

    "The models disagree by 1.4 m" is a bare number. "The models put this day between 3.1 m
    and 4.5 m" is the same measurement in terms a traveller can act on, and #8 asks for the
    second.
    """
    measured = derive(
        "swell_height",
        {"meteofrance_wave": 3.1, "dwd_gwam": 4.5, "ncep_gfswave025": 3.6},
    )

    assert measured is not None
    assert measured.lowest == pytest.approx(3.1)
    assert measured.highest == pytest.approx(4.5)
    assert measured.value == pytest.approx(measured.highest - measured.lowest)


class TestBearingsAreCircular:
    """Swell direction is one of the three variables Model Spread is measured on.

    Subtracting the smallest bearing from the largest is right for metres and seconds and
    wrong for degrees. Models agreeing on a north swell at 355° and 5° are 10° apart, and
    the arithmetic range calls them 350° apart — near-total disagreement reported on a day
    of near-perfect agreement. That inversion is exactly what ADR 0003's uncertainty
    estimate exists to prevent, and it would strike hardest on the northerly swells the
    canyon focuses best.
    """

    def test_agreement_across_north_is_the_short_arc(self):
        near_north = derive(
            "swell_direction",
            {"meteofrance_wave": 355.0, "dwd_gwam": 5.0, "ncep_gfswave025": 0.0},
        )

        assert near_north is not None
        assert near_north.value == pytest.approx(10.0)

    def test_the_endpoints_run_the_way_the_arc_does(self):
        """`lowest` and `highest` are the arc's start and end, so across north the start
        is the larger number. Reported as 5° to 355° the arc would name the wrong 350°."""
        near_north = derive("swell_direction", {"meteofrance_wave": 355.0, "dwd_gwam": 5.0})

        assert near_north is not None
        assert (near_north.lowest, near_north.highest) == (355.0, 5.0)

    def test_an_ordinary_north_westerly_arc_reads_as_it_always_did(self):
        """The wrap case must not be bought at the cost of the common one."""
        typical = derive(
            "swell_direction",
            {"meteofrance_wave": 300.0, "dwd_gwam": 320.0, "ncep_gfswave025": 310.0},
        )

        assert typical is not None
        assert (typical.lowest, typical.highest, typical.value) == (300.0, 320.0, 20.0)

    def test_an_organisation_votes_a_bearing_that_is_also_circular(self):
        """The per-organisation collapse has the same fault as the spread itself.

        DWD's two models at 355° and 5° take a plain median of 180° — a southerly swell
        invented out of two northerly forecasts, which then widens the spread against
        everyone else. The bug has to be fixed in both places or it survives in one.
        """
        opinions = by_provider({"dwd_ewam": 355.0, "dwd_gwam": 5.0}, "swell_direction")

        assert opinions["DWD"] == pytest.approx(0.0)

    def test_identical_bearings_span_nothing(self):
        """A degenerate case the gap-finding arithmetic gets wrong if left to itself:
        every gap between identical bearings is zero, and the widest empty gap would make
        the arc the whole circle rather than a point."""
        assert arc_of([310.0, 310.0]) == (310.0, 310.0, 0.0)


class TestADaySpread:
    """A date's Model Spread, from the hours the ensemble covered.

    A day is not one measurement. The models are asked about every hour of it, and each
    hour has its own disagreement, so the day needs a rule for which of them it reports.
    """

    def test_a_day_reports_its_median_hour(self):
        """The median rather than the mean, so one wild hour cannot set the day's figure,
        and rather than the peak, which would report the worst hour as the day."""
        day = for_day(
            "swell_height",
            [
                {"meteofrance_wave": 3.0, "dwd_gwam": 3.1, "ncep_gfswave025": 3.0},
                {"meteofrance_wave": 3.0, "dwd_gwam": 3.4, "ncep_gfswave025": 3.0},
                {"meteofrance_wave": 3.0, "dwd_gwam": 9.0, "ncep_gfswave025": 3.0},
            ],
        )

        assert day.spread is not None
        assert day.spread.value == pytest.approx(0.4)
        assert (day.hours_measured, day.hours_total) == (3, 3)

    def test_an_even_number_of_hours_takes_the_wider_middle(self):
        """The tiebreak errs toward doubt, which is the direction every other choice in
        this module errs in: an overstated spread makes the system quieter, and a quiet
        system never issues a Go Call it should not have."""
        day = for_day(
            "swell_height",
            [
                {"meteofrance_wave": 3.0, "dwd_gwam": 3.1, "ncep_gfswave025": 3.0},
                {"meteofrance_wave": 3.0, "dwd_gwam": 3.5, "ncep_gfswave025": 3.0},
            ],
        )

        assert day.spread is not None
        assert day.spread.value == pytest.approx(0.5)

    def test_hours_too_thin_to_measure_are_counted_rather_than_dropped(self):
        """How much of the day the ensemble actually covered is part of the answer.

        A day whose spread rests on two of its twenty-four hours is not the same claim as
        one measured throughout, and nothing else in the record would say which happened.
        """
        day = for_day(
            "swell_height",
            [
                {"meteofrance_wave": 3.0, "dwd_gwam": None, "ncep_gfswave025": None},
                {"meteofrance_wave": 3.0, "dwd_gwam": 3.4, "ncep_gfswave025": 3.0},
                {"meteofrance_wave": None, "dwd_gwam": None, "ncep_gfswave025": None},
            ],
        )

        assert day.spread is not None
        assert day.spread.value == pytest.approx(0.4)
        assert (day.hours_measured, day.hours_total) == (1, 3)

    def test_a_day_no_hour_could_measure_carries_no_spread_and_says_so(self):
        """The ensemble being unavailable is recorded, not omitted. A missing day is
        indistinguishable from a Pipeline Run that never happened (ADR 0003, #8)."""
        day = for_day(
            "swell_height",
            [{"meteofrance_wave": 3.0}, {"dwd_gwam": 3.4}],
        )

        assert day.spread is None
        assert (day.hours_measured, day.hours_total) == (0, 2)

    def test_a_day_with_no_hours_at_all_is_not_an_error(self):
        """A date the ensemble did not reach — the members stop modelling swell before the
        forecast's own range ends, so the last days of it have no members at all."""
        day = for_day("swell_height", [])

        assert day.spread is None
        assert (day.hours_measured, day.hours_total) == (0, 0)

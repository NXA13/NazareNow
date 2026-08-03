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
    by_provider,
    derive,
    spread_of,
)


def test_agreeing_providers_yield_a_narrow_spread():
    """#8: agreeing stubbed providers must produce narrow spread."""
    agreed = derive(
        "swell_wave_height",
        {"meteofrance_wave": 3.10, "dwd_gwam": 3.12, "ncep_gfswave025": 3.11},
    )

    assert agreed is not None
    assert agreed.value == pytest.approx(0.02, abs=1e-9)
    assert agreed.providers == ("DWD", "MeteoFrance", "NCEP")
    assert not agreed.degraded


def test_disagreeing_providers_yield_a_wide_spread():
    """#8: disagreeing stubbed providers must produce wide spread."""
    scattered = derive(
        "swell_wave_height",
        {"meteofrance_wave": 2.0, "dwd_gwam": 4.5, "ncep_gfswave025": 3.1},
    )

    assert scattered is not None
    assert scattered.value == pytest.approx(2.5, abs=1e-9)
    assert scattered.providers == ("DWD", "MeteoFrance", "NCEP")


def test_one_provider_failing_still_produces_a_usable_spread():
    """#8: a provider being unavailable degrades Model Spread rather than failing the run."""
    degraded = derive("swell_wave_height", {"meteofrance_wave": 3.0, "dwd_gwam": 3.6})

    assert degraded is not None
    assert degraded.value == pytest.approx(0.6, abs=1e-9)
    assert degraded.providers == ("DWD", "MeteoFrance")
    assert degraded.degraded, "a spread resting on two of three organisations must say so"


def test_a_provider_returning_null_is_not_an_opinion():
    """A member that answered with nothing must not be counted as having answered."""
    assert derive("swell_wave_height", {"meteofrance_wave": 3.0, "dwd_gwam": None}) is None


def test_a_single_organisation_carries_no_spread_rather_than_zero():
    """Zero here would be indistinguishable from perfect agreement.

    Both DWD models reporting is still one organisation, so there is nothing to difference.
    Returning 0.0 would read as maximum confidence at exactly the moment the system knows
    least, which is the inversion ADR 0003's uncertainty estimate exists to prevent.
    """
    assert derive("swell_wave_height", {"dwd_ewam": 3.0, "dwd_gwam": 3.9}) is None
    assert derive("swell_wave_height", {"meteofrance_wave": 3.0}) is None
    assert derive("swell_wave_height", {}) is None


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

    opinions = by_provider(readings)

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

    assert sorted(by_provider(without_ewam)) == ORGANISATIONS
    assert derive("swell_wave_height", without_ewam).degraded is False


def test_a_model_off_the_roster_is_refused_rather_than_given_a_vote():
    """An unknown identifier would otherwise silently change the ensemble's size."""
    with pytest.raises(KeyError, match="roster"):
        by_provider({"meteofrance_wave": 1.0, "some_new_model": 2.0})


def test_spread_needs_two_opinions():
    with pytest.raises(ValueError, match="not an ensemble"):
        spread_of([1.0])


def test_the_roster_maps_every_model_to_an_organisation():
    """A model added to the roster without an organisation would crash mid-run."""
    assert all(PROVIDERS.values())
    assert len(ORGANISATIONS) >= MINIMUM_PROVIDERS

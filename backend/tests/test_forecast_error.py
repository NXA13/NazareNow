"""Loading the Forecast Error Profile, and refusing a file that would narrow a Go Call.

Ticket #15. #14 measured how far a forecast drifts as its date approaches and shipped the
result as data (`forecast_error.json`); this is the loader that lets the running system read
it. The profile is one of the three terms a Predictive Distribution is built from, and the
only one that varies with Lead Time.

Every refusal below describes a file that **parses cleanly and means something wrong**, which
is the same standard `test_thresholds.py` holds the calibration to. The failure mode is worse
here, though, and worth naming: a threshold file that means something wrong produces visibly
odd calls, while an error profile that means something wrong produces a distribution of the
wrong *width*. A width is not obviously wrong to anyone reading it. Too narrow reads as
confidence, and confidence at seven days is exactly what ADR 0004 built this mechanism to
avoid.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nazarenow.forecast_error import (
    DEFAULT_PATH,
    PATH_VARIABLE,
    ForecastErrorUnusable,
    load,
    parse,
)


def band(drift: float = 0.1, bias: float = 0.0, p5: float = -0.2, p95: float = 0.2) -> dict:
    return {"drift": drift, "bias": bias, "p5": p5, "p95": p95, "hours": 1000}


def profile(through: int = 3, **overrides) -> dict:
    """A whole file, valid unless an override makes it otherwise."""
    body = {
        "quantity": "significant_wave_height_m",
        "reference": "open-meteo day 0",
        "measured_through_lead_days": through,
        "only_term": "Forecast drift alone. The Translation residual and the Amplification "
        "Model's own error are the other two terms",
        "by_lead_time": {
            str(lead): {"all_hours": band(), "big_swell": band(drift=0.2)}
            for lead in range(1, through + 1)
        },
        "method": {
            "ticket": 14,
            "serves": 15,
            "archive_begins": "2025-11-16",
            "big_swell_m": 3.0,
            "source": "analysis/forecast_error/profile.py",
        },
    }
    return body | overrides


class TestTheShippedProfile:
    """The file this release actually carries, not a fixture."""

    def test_it_loads(self) -> None:
        error = load()

        assert error.quantity == "significant_wave_height_m"
        assert error.measured_through_lead_days == 7

    def test_it_is_measured_at_every_lead_time_it_claims(self) -> None:
        """A gap would leave a Lead Time silently unmeasured rather than visibly missing."""
        error = load()

        for lead in range(1, error.measured_through_lead_days + 1):
            assert error.at(lead) is not None, f"lead time {lead} is claimed but absent"

    def test_the_seven_day_big_swell_bias_is_the_asymmetry_adr_0004_did_not_expect(self) -> None:
        """ADR 0004's amendment: beyond five days the forecast under-reads a big swell.

        Pinned because a Predictive Distribution centred symmetrically on the incoming
        forecast would sit on a number already known to be low, exactly where a Go Call is
        issued. Whatever #15 does about it, it must not do it by accident.
        """
        seven = load().at(7)

        assert seven is not None
        assert seven.big_swell.bias == pytest.approx(-0.2302)
        assert seven.big_swell.bias < seven.all_hours.bias


class TestBeyondTheMeasuredRange:
    """ADR 0004: the archive stops at seven days and nothing extends it."""

    def test_an_unmeasured_lead_time_is_absent_rather_than_extrapolated(self) -> None:
        """The criterion is that far-out dates are *visibly* more cautious.

        Returning the widest measured band would be the tempting silent fallback, and it
        would understate the uncertainty it claims to represent — eight days out is not
        seven days out, and the file has no evidence about it either way.
        """
        error = parse(profile(through=3))

        assert error.at(4) is None
        assert error.at(70) is None

    def test_lead_time_zero_and_below_are_absent_too(self) -> None:
        """Not an error: a Pipeline Run scores today, and today has no forecast drift."""
        error = parse(profile(through=3))

        assert error.at(0) is None
        assert error.at(-1) is None


class TestChoosingTheBand:
    """Which of the two measured regimes applies to a given sea."""

    def test_a_big_swell_reads_the_big_swell_band(self) -> None:
        lead = parse(profile()).at(1)

        assert lead is not None
        assert lead.for_sea(4.0) is lead.big_swell

    def test_a_small_sea_reads_the_all_hours_band(self) -> None:
        lead = parse(profile()).at(1)

        assert lead is not None
        assert lead.for_sea(1.5) is lead.all_hours

    def test_the_bar_itself_counts_as_big_swell(self) -> None:
        """`>=`, matching how every other 3 m bar in this project is written."""
        lead = parse(profile()).at(1)

        assert lead is not None
        assert lead.for_sea(3.0) is lead.big_swell


class TestRefusals:
    """Files that parse and mean something wrong."""

    def test_a_zero_width_band_is_refused(self) -> None:
        """Zero drift is a claim of certainty, and it would collapse the distribution.

        The mechanism would keep working: perturbing by zero returns the point estimate,
        every evaluation agrees, and the range renders as a single number with no warning.
        """
        body = profile()
        body["by_lead_time"]["1"]["all_hours"] = band(drift=0.0)

        with pytest.raises(ForecastErrorUnusable, match="drift"):
            parse(body)

    def test_a_negative_width_is_refused(self) -> None:
        body = profile()
        body["by_lead_time"]["1"]["big_swell"] = band(drift=-0.1)

        with pytest.raises(ForecastErrorUnusable, match="drift"):
            parse(body)

    def test_a_profile_written_before_the_drift_rename_is_refused(self) -> None:
        """#65 renamed the band's width key from `noise` to `drift`. Old files must not load.

        This is the one way the rename can reach a running system, and it is not
        hypothetical: `NAZARENOW_FORECAST_ERROR` exists so the profile can be re-measured
        without a redeploy, so a deployment can be pointed at a file written before #65.

        The tempting kindness — accept either key — is the failure this class is built to
        refuse everywhere else. A width is the one field whose wrongness does not look wrong,
        and silently reading `noise` would make the two spellings mean the same thing again,
        which is the ambiguity the rename removed. Refusing costs a clear error at startup;
        accepting costs a vocabulary that quietly has two words for one quantity forever.
        """
        pre_65 = profile()
        for lead in pre_65["by_lead_time"].values():
            for regime in lead.values():
                regime["noise"] = regime.pop("drift")

        # The whole message, not just "drift" — that substring appears in most of this class's
        # refusals, so matching it alone would pass if the file were rejected for some other
        # reason entirely and prove nothing about the old key.
        with pytest.raises(ForecastErrorUnusable, match="is missing 'drift'"):
            parse(pre_65)

    def test_inverted_percentiles_are_refused(self) -> None:
        """p5 above p95 describes no distribution, and both are valid floats."""
        body = profile()
        body["by_lead_time"]["1"]["all_hours"] = band(p5=0.4, p95=-0.4)

        with pytest.raises(ForecastErrorUnusable, match="p5"):
            parse(body)

    def test_a_gap_in_the_measured_range_is_refused(self) -> None:
        """The file claims a range; the keys must cover it.

        Without this the loader would answer `None` for a Lead Time the file says it
        measured, and the caller would widen for missing data that is merely mistyped.
        """
        body = profile(through=3)
        del body["by_lead_time"]["2"]

        with pytest.raises(ForecastErrorUnusable, match="2"):
            parse(body)

    def test_a_band_measured_on_no_hours_is_refused(self) -> None:
        body = profile()
        body["by_lead_time"]["1"]["all_hours"] = band() | {"hours": 0}

        with pytest.raises(ForecastErrorUnusable, match="hours"):
            parse(body)

    def test_a_missing_regime_is_refused(self) -> None:
        """Both bands are required. A file with one would silently apply it to both seas."""
        body = profile()
        del body["by_lead_time"]["1"]["big_swell"]

        with pytest.raises(ForecastErrorUnusable, match="big_swell"):
            parse(body)

    def test_a_profile_that_does_not_say_it_is_only_one_term_is_refused(self) -> None:
        """`only_term` is load-bearing prose, not decoration.

        #14 found drift is the *smallest* of the three terms at one day out. A consumer
        that treated this file as the whole uncertainty would build a distribution roughly
        three times too narrow, which is the specific mistake the field exists to prevent,
        so a file that drops it is refused rather than trusted.
        """
        body = profile()
        del body["only_term"]

        with pytest.raises(ForecastErrorUnusable, match="only_term"):
            parse(body)

    def test_a_missing_big_swell_bar_is_refused(self) -> None:
        """Without it there is no way to know which sea reads which band."""
        body = profile()
        del body["method"]["big_swell_m"]

        with pytest.raises(ForecastErrorUnusable, match="big_swell_m"):
            parse(body)

    def test_a_non_object_file_is_refused(self) -> None:
        with pytest.raises(ForecastErrorUnusable):
            parse([])  # type: ignore[arg-type]


class TestLoading:
    def test_a_missing_file_raises_rather_than_defaulting(self, tmp_path: Path) -> None:
        """Same reasoning as `ThresholdsUnusable`: a built-in fallback would let a
        misconfigured deployment publish confident ranges nobody measured."""
        with pytest.raises(ForecastErrorUnusable, match="cannot read"):
            load(tmp_path / "absent.json")

    def test_malformed_json_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "profile.json"
        path.write_text("{not json", encoding="utf-8")

        with pytest.raises(ForecastErrorUnusable, match="valid JSON"):
            load(path)

    def test_the_environment_variable_redirects_the_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Re-measuring the profile should not mean redeploying, per `thresholds.py`."""
        path = tmp_path / "profile.json"
        path.write_text(json.dumps(profile(through=2)), encoding="utf-8")
        monkeypatch.setenv(PATH_VARIABLE, str(path))

        assert load().measured_through_lead_days == 2

    def test_the_shipped_path_is_where_the_analysis_writes(self) -> None:
        assert DEFAULT_PATH.name == "forecast_error.json"

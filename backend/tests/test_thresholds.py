"""Loading calibrated thresholds, and refusing a file that would ship wrong advice.

Ticket #12 moved the Decision Model's numbers out of code and into data, which buys
recalibration without redeployment and costs the guarantee that the numbers were reviewed by
whoever reviewed the release. These tests are the replacement for that guarantee.

Every refusal below describes a file that **parses cleanly and means something wrong**. A
schema check would pass all of them, and every one produces confident, ordinary-looking calls
rather than a crash — which is why they are checked at load rather than left to be noticed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nazarenow.thresholds import (
    DEFAULT_PATH,
    PATH_VARIABLE,
    ThresholdsUnusable,
    load,
    parse,
)

VALID = {
    "minimum_significant_wave_height_m": 3.75,
    "watch_minimum_swell_period_s": 12.5,
    "go_call_minimum_swell_period_s": 13.0,
    "swell_arc": [255.0, 330.0],
    "offshore_wind_arc": [20.0, 180.0],
    "maximum_wind_speed_kmh": 35.0,
    "light_wind_exemption_kmh": 16.5,
    "calibration": {
        "fitted_on": "2021/22-2022/23",
        "validated_on": "2023/24-2025/26",
        "gold_days_fitted": 6,
        "gold_days_validated": 3,
        "method": "fitted per tier against Gold Days",
        "source": "analysis/calibration/calibrate.py",
        "fitted_at": "2026-08-02",
    },
}


def write(tmp_path: Path, body: object) -> Path:
    path = tmp_path / "thresholds.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


class TestParsing:
    def test_a_valid_file_round_trips(self) -> None:
        thresholds = parse(VALID)

        assert thresholds.minimum_significant_wave_height_m == 3.75
        assert thresholds.watch_minimum_swell_period_s == 12.5
        assert thresholds.go_call_minimum_swell_period_s == 13.0
        assert thresholds.swell_arc == (255.0, 330.0)
        assert thresholds.calibrated is True

    def test_a_set_without_a_calibration_reports_itself_uncalibrated(self) -> None:
        """An explicit null is legitimate — it is what an unfitted rule of thumb looks like.

        What it must not do is claim otherwise, since `calibrated` is what the interface
        uses to decide whether to warn the user.
        """
        thresholds = parse(VALID | {"calibration": None})

        assert thresholds.calibrated is False
        assert thresholds.calibration is None

    def test_gold_days_total_is_the_sum_of_both_splits(self) -> None:
        """The number the interface shows the user. Derived rather than stored, so a file
        cannot claim a total larger than the splits it names."""
        calibration = parse(VALID).calibration

        assert calibration is not None
        assert calibration.gold_days_total == 9


class TestVarying:
    """`as_dict` and `replacing`, which the calibration sweep and the backtest both use."""

    def test_a_set_round_trips_through_its_own_dict(self) -> None:
        """`as_dict` is what writes the shipped file, so a key it drops is a threshold the
        next load would reject or silently miss."""
        original = parse(VALID)

        assert parse(original.as_dict()) == original

    def test_replacing_varies_one_field_and_keeps_the_rest(self) -> None:
        varied = parse(VALID).replacing(go_call_minimum_swell_period_s=14.0)

        assert varied.go_call_minimum_swell_period_s == 14.0
        assert varied.watch_minimum_swell_period_s == 12.5
        assert varied.swell_arc == (255.0, 330.0)

    def test_replacing_still_refuses_an_inverted_pair(self) -> None:
        """The reason `replacing` exists rather than `dataclasses.replace`, which would skip
        validation entirely — letting a sweep score a set the running system would refuse to
        load, and then recommend it."""
        with pytest.raises(ThresholdsUnusable, match="not above the Watch bar"):
            parse(VALID).replacing(go_call_minimum_swell_period_s=11.0)


class TestRefusals:
    def test_a_go_bar_below_the_watch_bar_is_refused(self) -> None:
        """The refusal this module exists for.

        Inverting the bars makes the Watch tier unreachable — anything clearing it clears
        the Go Call bar too — which is precisely the tier collapse #11 measured and #12
        undid. Every field is still a valid float, so nothing else would notice.
        """
        with pytest.raises(ThresholdsUnusable, match="not above the Watch bar"):
            parse(VALID | {"go_call_minimum_swell_period_s": 12.0})

    def test_equal_bars_are_refused_too(self) -> None:
        """Equal bars collapse the tiers just as completely as inverted ones, and are the
        far likelier typo."""
        with pytest.raises(ThresholdsUnusable, match="not above the Watch bar"):
            parse(VALID | {"go_call_minimum_swell_period_s": 12.5})

    def test_an_arc_wrapping_past_north_is_refused(self) -> None:
        """A wrapping arc matches no bearing at all under a single comparison, so it reads
        as "the swell is never from the right direction" — silence, not an error."""
        with pytest.raises(ThresholdsUnusable, match="does not open eastward"):
            parse(VALID | {"swell_arc": [330.0, 30.0]})

    @pytest.mark.parametrize(
        "field",
        [
            "minimum_significant_wave_height_m",
            "watch_minimum_swell_period_s",
            "go_call_minimum_swell_period_s",
            "maximum_wind_speed_kmh",
        ],
    )
    def test_a_missing_threshold_is_refused(self, field: str) -> None:
        body = {key: value for key, value in VALID.items() if key != field}

        with pytest.raises(ThresholdsUnusable, match=field):
            parse(body)

    @pytest.mark.parametrize("field", ["swell_arc", "offshore_wind_arc"])
    def test_a_missing_arc_is_refused(self, field: str) -> None:
        body = {key: value for key, value in VALID.items() if key != field}

        with pytest.raises(ThresholdsUnusable, match=field):
            parse(body)

    def test_a_non_numeric_threshold_is_refused(self) -> None:
        with pytest.raises(ThresholdsUnusable, match="must be a number"):
            parse(VALID | {"maximum_wind_speed_kmh": "thirty-five"})

    @pytest.mark.parametrize("value", [0.0, -1.0])
    def test_a_non_positive_threshold_is_refused(self, value: float) -> None:
        """A zero height bar admits a flat calm sea to a Go Call."""
        with pytest.raises(ThresholdsUnusable, match="must be positive"):
            parse(VALID | {"minimum_significant_wave_height_m": value})

    def test_a_partial_calibration_is_refused(self) -> None:
        """Half a provenance is worse than none: the interface would drop its uncalibrated
        warning and then have nothing to put in its place."""
        partial = {k: v for k, v in VALID["calibration"].items() if k != "gold_days_validated"}

        with pytest.raises(ThresholdsUnusable, match="incomplete"):
            parse(VALID | {"calibration": partial})

    def test_fitting_and_validating_on_one_span_is_refused(self) -> None:
        """An in-sample score reported as a held-out one is the single most misleading
        thing this file could carry, and it is one copy-paste away."""
        same = VALID["calibration"] | {"validated_on": VALID["calibration"]["fitted_on"]}

        with pytest.raises(ThresholdsUnusable, match="same span"):
            parse(VALID | {"calibration": same})

    @pytest.mark.parametrize("value", [0, -3, "six"])
    def test_a_nonsensical_gold_day_count_is_refused(self, value: object) -> None:
        """The count reaches the user as "fitted to N days". Zero would read as a fit on
        nothing while `calibrated` still said true."""
        calibration = VALID["calibration"] | {"gold_days_fitted": value}

        with pytest.raises(ThresholdsUnusable, match="positive whole number"):
            parse(VALID | {"calibration": calibration})


class TestTheLightWindExemption:
    """ADR 0009's new field, validated like every other threshold."""

    def test_a_file_without_it_is_refused(self) -> None:
        """Not defaulted, because a default would change the *shape* of the wind condition
        rather than its strictness — a file silently missing this would apply the offshore
        arc to winds ADR 0009 exempts, which is the defect the ADR exists to remove."""
        body = {k: v for k, v in VALID.items() if k != "light_wind_exemption_kmh"}

        with pytest.raises(ThresholdsUnusable, match="light_wind_exemption_kmh"):
            parse(body)

    @pytest.mark.parametrize("exemption", [35.0, 40.0])
    def test_an_exemption_at_or_above_the_cap_is_refused(self, exemption: float) -> None:
        """At or above the cap every wind the cap allows is already exempt, so the offshore
        arc is never consulted for a passing day and the condition degenerates into a bare
        speed limit. Every field would still be a valid positive float."""
        with pytest.raises(ThresholdsUnusable, match="not below maximum_wind_speed_kmh"):
            parse(VALID | {"light_wind_exemption_kmh": exemption})

    def test_it_survives_a_round_trip_through_as_dict(self) -> None:
        """`as_dict` is what the calibration writes back; a key it dropped would produce a
        file the running system then refuses to load."""
        thresholds = parse(VALID)

        assert parse(thresholds.as_dict()).light_wind_exemption_kmh == 16.5


class TestLoading:
    def test_the_environment_variable_overrides_the_shipped_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """#12's "configurable without code changes": recalibrating is pointing at a file."""
        path = write(tmp_path, VALID | {"go_call_minimum_swell_period_s": 15.0})
        monkeypatch.setenv(PATH_VARIABLE, str(path))

        assert load().go_call_minimum_swell_period_s == 15.0

    def test_an_explicit_path_beats_the_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(PATH_VARIABLE, str(tmp_path / "nonexistent.json"))
        path = write(tmp_path, VALID)

        assert load(path).go_call_minimum_swell_period_s == 13.0

    def test_a_missing_file_raises_rather_than_falling_back(self, tmp_path: Path) -> None:
        """No built-in default. A fallback would let a misconfigured deployment issue calls
        from thresholds nobody chose, and the calls would look entirely normal."""
        with pytest.raises(ThresholdsUnusable, match="cannot read thresholds"):
            load(tmp_path / "nothing-here.json")

    def test_malformed_json_names_the_file(self, tmp_path: Path) -> None:
        path = tmp_path / "thresholds.json"
        path.write_text("{not json", encoding="utf-8")

        with pytest.raises(ThresholdsUnusable, match="not valid JSON"):
            load(path)

    def test_a_file_holding_a_list_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ThresholdsUnusable, match="must hold an object"):
            load(write(tmp_path, [VALID]))

    def test_the_shipped_file_loads(self) -> None:
        """The default this release carries is not merely present but valid.

        Its *values* are pinned in `test_baseline_is_fixed.py`, which is where a
        recalibration has to declare itself. This only asserts the release cannot ship a
        file that fails to load at all.
        """
        assert DEFAULT_PATH.exists()
        assert load(DEFAULT_PATH).calibrated is True

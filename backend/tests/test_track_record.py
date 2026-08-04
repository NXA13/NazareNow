"""Loading the published track record, and refusing one that would flatter the system.

Ticket #16. The track record is the page a reader consults *before* deciding whether to
trust a Go Call with their money, so every refusal below describes a file that parses
cleanly and overstates what the system has demonstrated.

Two shapes of check, and they are different in kind:

- **Structural** — a band carrying only one model's error cannot be built at all. ADR 0006
  requires the Heuristic Baseline beside every accuracy figure, and the cheapest way to keep
  a promise like that is to make the alternative unrepresentable rather than to test for it
  at each of the places that render one.
- **Arithmetic** — more Gold Days caught than the split contains, or a Watch tier flagging
  fewer days than the Go Call tier. Each is a plausible-looking file that inverts the meaning
  of the number a reader takes away.

Rates are never read from the file. They are derived from the counts, so a recall the
counts do not support cannot be published — see `TestDerivedRates`.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from nazarenow.track_record import (
    DEFAULT_PATH,
    PATH_VARIABLE,
    TrackRecordUnusable,
    load,
    parse,
)

VALID: dict[str, Any] = {
    "published_at": "2026-08-04",
    "source": "analysis/track_record/publish.py",
    "call_record": {
        "held_out": {
            "span": "2020/21-2025/26",
            "basis": "Hindcast",
            "gold_days": 13,
            "big_wave_seasons": 6.0,
            "tiers": {
                "watch_or_better": {"gold_days_called": 12, "days_flagged": 193},
                "go_call": {"gold_days_called": 9, "days_flagged": 43},
            },
        },
        "full_record": {
            "span": "2011-2025",
            "basis": "Hindcast",
            "gold_days": 38,
            "big_wave_seasons": 15.0,
            "tiers": {
                "watch_or_better": {"gold_days_called": 33, "days_flagged": 574},
                "go_call": {"gold_days_called": 16, "days_flagged": 128},
            },
        },
    },
    "height_record": {
        "scored": {
            "bands": [
                {
                    "name": "all hours",
                    "hours": 28426,
                    "baseline_mae_m": 0.1964,
                    "learned_mae_m": 0.2070,
                },
                {
                    "name": "Gold Day hours",
                    "hours": 120,
                    "baseline_mae_m": 0.8851,
                    "learned_mae_m": 0.5636,
                },
            ]
        },
        "served": {
            "bands": [
                {
                    "name": "all hours",
                    "hours": 28426,
                    "baseline_mae_m": 0.2197,
                    "learned_mae_m": 0.2971,
                },
            ]
        },
    },
    "gold_days": {"fitted": 25, "validated": 13},
    "days": [
        {
            "date": "2011-11-01",
            "season": "2011/12",
            "call": "watch",
            "peak_significant_wave_height_m": 3.40,
            "gold_day": True,
            "gold_tier": "ratified",
        },
        {
            "date": "2013-10-28",
            "season": "2013/14",
            "call": "go",
            "peak_significant_wave_height_m": 4.20,
            "gold_day": True,
            "gold_tier": "documented",
        },
    ],
}


def write(tmp_path: Path, body: object) -> Path:
    path = tmp_path / "track_record.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def without(*path: str) -> dict[str, Any]:
    """A copy of VALID with one nested key removed."""
    body = deepcopy(VALID)
    target: Any = body
    for key in path[:-1]:
        target = target[key]
    del target[path[-1]]
    return body


def having(value: Any, *path: str) -> dict[str, Any]:
    """A copy of VALID with one nested key replaced."""
    body = deepcopy(VALID)
    target: Any = body
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return body


class TestParsing:
    def test_a_valid_file_round_trips(self) -> None:
        record = parse(VALID)

        assert record.published_at == "2026-08-04"
        assert record.source == "analysis/track_record/publish.py"
        assert record.held_out.span == "2020/21-2025/26"
        assert record.held_out.gold_days == 13
        assert record.full_record.gold_days == 38
        assert record.gold_days_total == 38

    def test_the_two_panels_are_kept_apart(self) -> None:
        """The held-out figures and the whole-record ones are different claims.

        The README calls the held-out ones "the honest figures". Collapsing them into one
        would let a reader take a recall measured partly on the days it was fitted on as a
        statement about days it had never seen.
        """
        record = parse(VALID)

        assert record.held_out.tiers["go_call"].gold_days_called == 9
        assert record.full_record.tiers["go_call"].gold_days_called == 16

    def test_days_carry_what_was_called_and_what_the_sea_did(self) -> None:
        record = parse(VALID)

        first = record.days[0]
        assert first.date == "2011-11-01"
        assert first.call == "watch"
        assert first.peak_significant_wave_height_m == 3.40
        assert first.gold_day is True
        assert first.gold_tier == "ratified"

    def test_a_missing_top_level_section_is_refused(self) -> None:
        for section in ("call_record", "height_record", "gold_days", "days"):
            with pytest.raises(TrackRecordUnusable, match=section):
                parse(without(section))

    def test_a_body_that_is_not_an_object_is_refused(self) -> None:
        with pytest.raises(TrackRecordUnusable, match="object"):
            parse([])  # type: ignore[arg-type]


class TestDerivedRates:
    """Recall and precision are computed here, never read from the file.

    A stored rate is a second copy of a number the counts already determine, and the two
    disagreeing is not hypothetical: the rate is what a reader quotes and the counts are
    what someone updates.
    """

    def test_recall_comes_from_the_counts(self) -> None:
        record = parse(VALID)

        assert record.held_out.tiers["go_call"].recall == pytest.approx(9 / 13)
        assert record.held_out.tiers["watch_or_better"].recall == pytest.approx(12 / 13)

    def test_precision_is_a_lower_bound_from_the_counts(self) -> None:
        """A flagged day that is not a Gold Day may still have been an XXL Day nobody
        documented, so this can only ever be a floor — #11's own wording."""
        record = parse(VALID)

        assert record.held_out.tiers["go_call"].precision_lower_bound == pytest.approx(9 / 43)

    def test_wasted_trips_are_the_complement_of_precision(self) -> None:
        """The figure #16 asks to be stated plainly: how often acting on a Go Call would
        have been wasted. An upper bound exactly because precision is a lower one."""
        record = parse(VALID)

        tier = record.held_out.tiers["go_call"]
        assert tier.wasted_upper_bound == pytest.approx(1 - 9 / 43)
        assert tier.days_wasted_upper_bound == 34

    def test_flags_per_big_wave_season_comes_from_the_counts(self) -> None:
        record = parse(VALID)

        assert record.held_out.tiers["go_call"].flags_per_big_wave_season == pytest.approx(43 / 6.0)

    def test_a_panel_spanning_no_seasons_reports_no_rate_rather_than_dividing(self) -> None:
        with pytest.raises(TrackRecordUnusable, match="big_wave_seasons"):
            parse(having(0.0, "call_record", "held_out", "big_wave_seasons"))


class TestBothModelsOrNeither:
    """ADR 0006: no accuracy figure in this project is reported without the baseline.

    Enforced by the shape rather than by the renderer. A band is the pair, so there is no
    way to publish one model's error — and therefore nothing for a template to forget.
    """

    def test_a_band_missing_the_baseline_is_refused(self) -> None:
        body = deepcopy(VALID)
        del body["height_record"]["scored"]["bands"][0]["baseline_mae_m"]

        with pytest.raises(TrackRecordUnusable, match="baseline_mae_m"):
            parse(body)

    def test_a_band_missing_the_learned_model_is_refused(self) -> None:
        body = deepcopy(VALID)
        del body["height_record"]["scored"]["bands"][0]["learned_mae_m"]

        with pytest.raises(TrackRecordUnusable, match="learned_mae_m"):
            parse(body)

    def test_a_null_error_is_refused_rather_than_rendered_as_a_gap(self) -> None:
        body = deepcopy(VALID)
        body["height_record"]["scored"]["bands"][0]["learned_mae_m"] = None

        with pytest.raises(TrackRecordUnusable, match="learned_mae_m"):
            parse(body)

    def test_a_panel_with_no_bands_is_refused(self) -> None:
        body = deepcopy(VALID)
        body["height_record"]["scored"]["bands"] = []

        with pytest.raises(TrackRecordUnusable, match="at least one band"):
            parse(body)

    def test_the_gain_is_derived_and_signed_toward_the_learned_model(self) -> None:
        """Positive means the learned model is closer to the buoy — the sign convention
        every table in `analysis/amplification_model/` already uses."""
        record = parse(VALID)

        scored = {band.name: band for band in record.scored.bands}
        assert scored["all hours"].gain_m == pytest.approx(0.1964 - 0.2070)
        assert scored["all hours"].gain_m < 0
        assert scored["Gold Day hours"].gain_m == pytest.approx(0.8851 - 0.5636)


class TestArithmeticThatWouldOverstate:
    def test_catching_more_gold_days_than_the_split_holds_is_refused(self) -> None:
        body = deepcopy(VALID)
        body["call_record"]["held_out"]["tiers"]["go_call"]["gold_days_called"] = 14

        with pytest.raises(TrackRecordUnusable, match="more Gold Days"):
            parse(body)

    def test_catching_more_gold_days_than_days_flagged_is_refused(self) -> None:
        body = deepcopy(VALID)
        body["call_record"]["held_out"]["tiers"]["go_call"]["days_flagged"] = 4

        with pytest.raises(TrackRecordUnusable, match="days_flagged"):
            parse(body)

    def test_a_watch_tier_narrower_than_the_go_call_tier_is_refused(self) -> None:
        """The tier collapse #12 exists to undo, in the shape it would take on this page.

        A Watch is recall-optimised and reaches further than a Go Call by construction, so a
        Watch tier flagging fewer days is not a worse system — it is a mislabelled table,
        and every figure on it would read as though the precision tier were the broad one.
        """
        body = deepcopy(VALID)
        body["call_record"]["held_out"]["tiers"]["watch_or_better"]["days_flagged"] = 20

        with pytest.raises(TrackRecordUnusable, match="Watch"):
            parse(body)

    def test_a_missing_tier_is_refused(self) -> None:
        """#16 requires Watch and Go Call accuracy reported separately, so neither tier is
        optional. A file with one of them would render a page that silently reports the
        other's figures under both headings."""
        for tier in ("watch_or_better", "go_call"):
            body = deepcopy(VALID)
            del body["call_record"]["held_out"]["tiers"][tier]

            with pytest.raises(TrackRecordUnusable, match=tier):
                parse(body)

    def test_negative_counts_are_refused(self) -> None:
        with pytest.raises(TrackRecordUnusable, match="gold_days_called"):
            parse(having(-1, "call_record", "held_out", "tiers", "go_call", "gold_days_called"))

    def test_a_gold_day_split_that_does_not_add_up_is_refused(self) -> None:
        """`gold_days.fitted + gold_days.validated` is the total the page states as the
        whole basis of the calibration. A total larger than its parts would make the
        thinnest number on the page look less thin."""
        body = deepcopy(VALID)
        body["gold_days"]["validated"] = 4

        with pytest.raises(TrackRecordUnusable, match="held-out"):
            parse(body)


class TestDays:
    def test_a_day_claiming_a_gold_tier_without_being_a_gold_day_is_refused(self) -> None:
        body = deepcopy(VALID)
        body["days"][0]["gold_day"] = False

        with pytest.raises(TrackRecordUnusable, match="gold_tier"):
            parse(body)

    def test_an_unknown_call_status_is_refused(self) -> None:
        """The four statuses are the Decision Model's, and the page renders each one
        differently. A fifth would render as nothing at all."""
        body = deepcopy(VALID)
        body["days"][0]["call"] = "maybe"

        with pytest.raises(TrackRecordUnusable, match="maybe"):
            parse(body)

    def test_days_must_be_in_date_order(self) -> None:
        """The page reads as a chronology. Out-of-order rows are the kind of defect that
        looks like a rendering bug and is actually a regenerated file."""
        body = deepcopy(VALID)
        body["days"] = list(reversed(body["days"]))

        with pytest.raises(TrackRecordUnusable, match="date order"):
            parse(body)


class TestLoading:
    def test_the_shipped_file_loads(self) -> None:
        """The file this release publishes is read by the same validation everything else
        is. A record that ships unloadable is a page that 500s in front of the reader it
        was written to convince."""
        record = load(DEFAULT_PATH)

        assert record.days
        assert record.scored.bands
        assert record.served.bands
        assert record.held_out.tiers["go_call"].days_flagged > 0

    def test_the_environment_variable_is_honoured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(PATH_VARIABLE, str(write(tmp_path, VALID)))

        assert load().published_at == "2026-08-04"

    def test_a_missing_file_raises_rather_than_publishing_nothing(self, tmp_path: Path) -> None:
        with pytest.raises(TrackRecordUnusable, match="cannot read"):
            load(tmp_path / "absent.json")

    def test_a_malformed_file_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "track_record.json"
        path.write_text("{not json", encoding="utf-8")

        with pytest.raises(TrackRecordUnusable, match="valid JSON"):
            load(path)

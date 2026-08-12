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
                    "caveat": "rests on five days",
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
        "range_calibration": {
            "claimed": 0.9,
            "understates_because": "the ensemble term is absent and can only widen",
            "rests_on": "one partial Big-Wave Season",
            "leads": [
                {
                    "lead_days": 1,
                    "all_hours": {
                        "hours": 1593,
                        "covered": 0.9397,
                        "median_width_m": 1.0459,
                        "widening_factor": 0.822,
                    },
                    "big_swell": {
                        "hours": 807,
                        "covered": 0.9257,
                        "median_width_m": 1.6144,
                        "widening_factor": 0.9368,
                    },
                },
                {
                    "lead_days": 7,
                    "all_hours": {
                        "hours": 1593,
                        "covered": 0.9937,
                        "median_width_m": 2.1919,
                        "widening_factor": 0.5264,
                    },
                    "big_swell": {
                        "hours": 807,
                        "covered": 0.9888,
                        "median_width_m": 3.0812,
                        "widening_factor": 0.5767,
                    },
                },
            ],
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

        assert record.held_out.go_call.gold_days_called == 9
        assert record.full_record.go_call.gold_days_called == 16

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

        assert record.held_out.go_call.recall == pytest.approx(9 / 13)
        assert record.held_out.watch_or_better.recall == pytest.approx(12 / 13)

    def test_precision_is_a_lower_bound_from_the_counts(self) -> None:
        """A flagged day that is not a Gold Day may still have been an XXL Day nobody
        documented, so this can only ever be a floor — #11's own wording."""
        record = parse(VALID)

        assert record.held_out.go_call.precision_lower_bound == pytest.approx(9 / 43)

    def test_wasted_trips_are_the_complement_of_precision(self) -> None:
        """The figure #16 asks to be stated plainly: how often acting on a Go Call would
        have been wasted. An upper bound exactly because precision is a lower one."""
        record = parse(VALID)

        tier = record.held_out.go_call
        assert tier.wasted_upper_bound == pytest.approx(1 - 9 / 43)
        assert tier.days_wasted_upper_bound == 34

    def test_flags_per_big_wave_season_comes_from_the_counts(self) -> None:
        record = parse(VALID)

        assert record.held_out.go_call.flags_per_big_wave_season == pytest.approx(43 / 6.0)

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

        scored = {band.name: band for band in record.scored}
        assert scored["all hours"].gain_m == pytest.approx(0.1964 - 0.2070)
        assert scored["all hours"].gain_m < 0
        assert scored["Gold Day hours"].gain_m == pytest.approx(0.8851 - 0.5636)


class TestCaveats:
    """A qualification the source insists on travels with the number, not with the renderer.

    Two rows have one. `analysis/amplification_model/README.md` says the Gold Day figure
    "rests on five days ... and should never be quoted without that", and #52 says of the
    served `Combined Sea >= 3 m` aggregate: do not quote it as robust to the reconstruction
    assumption. Both are figures that look strong and are qualified, which is exactly the
    kind a page drops on the way to a table.
    """

    def test_a_caveat_rides_on_the_band_it_qualifies(self) -> None:
        record = parse(VALID)

        scored = {band.name: band for band in record.scored}
        assert scored["Gold Day hours"].caveat == "rests on five days"
        assert scored["all hours"].caveat is None

    def test_a_band_without_one_reports_none_rather_than_an_empty_string(self) -> None:
        """`None` and `""` render differently: an empty string is a caveat that says
        nothing, and a footnote marker beside a figure with no footnote is worse than no
        marker at all."""
        body = deepcopy(VALID)
        body["height_record"]["scored"]["bands"][0]["caveat"] = ""

        assert parse(body).scored[0].caveat is None

    def test_the_shipped_record_qualifies_both_rows_that_need_it(self) -> None:
        """Pinned against the file this release actually publishes, not a fixture.

        These are the two figures on the page most likely to be quoted out of context — the
        Gold Day comparison, which is the headline, and the aggregate that reverses sign
        under a different residual assumption. A regeneration that dropped either caveat
        would leave both figures reading as unqualified.
        """
        record = load(DEFAULT_PATH)

        scored = {band.name: band for band in record.scored}
        served = {band.name: band for band in record.served}

        assert scored["Gold Day hours"].caveat and "5 Gold Days" in scored["Gold Day hours"].caveat
        fragile = served["Combined Sea 3 m and above"]
        assert fragile.caveat and "Not robust" in fragile.caveat
        # The bands that do hold their sign must not inherit the warning.
        assert served["6 m and above"].caveat is None


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


class TestDeliveredSea:
    """What the sea did on the flagged days (#83), and the files that would overstate it.

    Every refusal here is in the same direction as the rest of this module: a file that
    parses cleanly and makes the system look better than the record holds. The section is
    the page's counterweight to the wasted-trip figure, so an inflated one does not read as
    an error — it reads as reassurance, which is the expensive failure on this page.
    """

    DELIVERED = ("call_record", "held_out", "tiers", "go_call", "delivered")

    def with_delivery(self, delivered: Any) -> dict[str, Any]:
        body = deepcopy(VALID)
        body["call_record"]["held_out"]["tiers"]["go_call"]["delivered"] = delivered
        return body

    def valid(self) -> dict[str, Any]:
        return {
            "minimum_m": 2.82,
            "median_m": 3.8,
            "maximum_m": 5.3,
            "above": [
                {"metres": 3.0, "days": 39},
                {"metres": 4.0, "days": 17},
                {"metres": 5.0, "days": 5},
                {"metres": 6.0, "days": 0},
            ],
        }

    def test_a_tier_without_a_delivery_parses(self) -> None:
        """Optional, unlike every other figure. The Watch tier carries none today (#87), and
        a page missing this sentence is worse than a page not served only in the other
        direction — so its absence must not be an error."""
        record = parse(deepcopy(VALID))

        assert record.held_out.go_call.delivered is None
        assert record.held_out.watch_or_better.delivered is None

    def test_shares_are_derived_from_the_counts(self) -> None:
        """The file carries counts. A file carrying a share as well would carry the same
        fact twice, and the copies drift in the direction the module docstring names."""
        record = parse(self.with_delivery(self.valid()))
        delivered = record.held_out.go_call.delivered

        assert delivered is not None
        assert [step.days for step in delivered.above] == [39, 17, 5, 0]
        assert all(step.of_days == 43 for step in delivered.above)
        assert delivered.above[0].share == 39 / 43

    def test_more_days_over_a_bar_than_were_ever_flagged_is_refused(self) -> None:
        """The arithmetic that lets a page say "97 of 43". It renders as an ordinary
        sentence and is the shape of `TrackRecord.tsx`'s worst survivor in #79."""
        delivered = self.valid()
        delivered["above"][0]["days"] = 97

        with pytest.raises(TrackRecordUnusable, match="more days than the tier ever called"):
            parse(self.with_delivery(delivered))

    def test_a_ladder_that_rises_with_the_bar_is_refused(self) -> None:
        """More days clearing 4 m than clearing 3 m cannot both be true. A file like this
        makes the strongest-looking rung the one nothing supports."""
        delivered = self.valid()
        delivered["above"][1]["days"] = 40

        with pytest.raises(TrackRecordUnusable, match="which cannot both be true"):
            parse(self.with_delivery(delivered))

    def test_thresholds_that_do_not_increase_are_refused(self) -> None:
        delivered = self.valid()
        delivered["above"][1]["metres"] = 2.0

        with pytest.raises(TrackRecordUnusable, match="not increasing"):
            parse(self.with_delivery(delivered))

    def test_a_day_above_the_highest_recorded_peak_is_refused(self) -> None:
        """A rung above the maximum with days on it means the ladder and the summary describe
        different sets of days, and the ladder is the half a reader scans."""
        delivered = self.valid()
        delivered["above"][3]["days"] = 1

        with pytest.raises(TrackRecordUnusable, match="highest day recorded"):
            parse(self.with_delivery(delivered))

    def test_a_summary_out_of_order_is_refused(self) -> None:
        """A minimum above the median is the field swap that would put the flattering number
        where the page says "the lowest peak any of them landed on"."""
        delivered = self.valid()
        delivered["minimum_m"], delivered["median_m"] = (
            delivered["median_m"],
            delivered["minimum_m"],
        )

        with pytest.raises(TrackRecordUnusable, match="not in order"):
            parse(self.with_delivery(delivered))

    def test_an_empty_ladder_is_refused(self) -> None:
        delivered = self.valid()
        delivered["above"] = []

        with pytest.raises(TrackRecordUnusable, match="no thresholds"):
            parse(self.with_delivery(delivered))


class TestRangeCalibration:
    """The measured calibration of the range the interface prints (#94).

    The refusals here are narrower than elsewhere in this file, and that is the point. Every
    other section is guarded against a file that *flatters* — more Gold Days caught than exist,
    a ladder claiming more days than were flagged. This one cannot be, because the flattering
    direction is not a fixed direction: #82 exists to narrow the distribution, and a record
    where the range holds the outcome *less* often than it claims is that repair landing, not
    a corrupt file. So what is refused is incoherence — a subset larger than its superset, a
    Lead Time appearing twice, a share above one — and never a verdict.
    """

    @staticmethod
    def calibration(body: dict[str, Any]) -> dict[str, Any]:
        return body["height_record"]["range_calibration"]

    def test_the_claim_and_the_measurement_both_survive(self) -> None:
        record = parse(deepcopy(VALID)).range_calibration

        assert record.claimed == 0.9
        assert [lead.lead_days for lead in record.leads] == [1, 7]
        assert record.leads[0].all_hours.covered == 0.9397
        assert record.leads[0].big_swell.hours == 807

    def test_the_width_the_outcomes_asked_for_is_derived_rather_than_stored(self) -> None:
        """#80's own sentence, as a number: a seven-day range spanning 2.19 m would have held
        the same share of outcomes at 1.15 m. Derived here so a file cannot carry a width and
        a factor that disagree with the product of the two."""
        seven = parse(deepcopy(VALID)).range_calibration.leads[1]

        assert seven.all_hours.justified_width_m == pytest.approx(2.1919 * 0.5264)
        assert seven.all_hours.justified_width_m < seven.all_hours.median_width_m

    def test_a_record_without_the_section_is_refused(self) -> None:
        """The page prints a range in metres. A record that cannot say whether it holds what
        it claims serves a page that states the claim and omits the check, which is the
        flattering half of the pair."""
        with pytest.raises(TrackRecordUnusable, match="range_calibration"):
            parse(without("height_record", "range_calibration"))

    def test_a_lead_time_carrying_only_one_subset_is_refused(self) -> None:
        """The big-swell rows are the sea a Go Call is issued on and read kinder than the
        whole. A record able to carry them alone can publish the kinder number under a
        heading a reader takes for the whole finding."""
        for subset in ("all_hours", "big_swell"):
            body = deepcopy(VALID)
            del self.calibration(body)["leads"][0][subset]

            with pytest.raises(TrackRecordUnusable, match=subset):
                parse(body)

    def test_a_big_swell_subset_larger_than_the_hours_it_comes_from_is_refused(self) -> None:
        body = deepcopy(VALID)
        self.calibration(body)["leads"][0]["big_swell"]["hours"] = 9999

        with pytest.raises(TrackRecordUnusable, match="not a subset"):
            parse(body)

    def test_a_repeated_lead_time_is_refused(self) -> None:
        body = deepcopy(VALID)
        self.calibration(body)["leads"][1]["lead_days"] = 1

        with pytest.raises(TrackRecordUnusable, match="repeated or out of order"):
            parse(body)

    def test_a_coverage_share_above_one_is_refused(self) -> None:
        body = deepcopy(VALID)
        self.calibration(body)["leads"][0]["all_hours"]["covered"] = 1.4

        with pytest.raises(TrackRecordUnusable, match="between 0 and 1"):
            parse(body)

    def test_a_range_with_no_width_is_refused(self) -> None:
        body = deepcopy(VALID)
        self.calibration(body)["leads"][0]["all_hours"]["median_width_m"] = 0

        with pytest.raises(TrackRecordUnusable, match="no width"):
            parse(body)

    def test_an_empty_qualification_is_refused_rather_than_rendered_as_a_blank_bullet(
        self,
    ) -> None:
        """Both caveats are the reason this table is not a calibration certificate. An empty
        string passes every type check and renders as a bullet a reader skips, so the page
        keeps its shape and loses the sentence."""
        for field in ("understates_because", "rests_on"):
            body = deepcopy(VALID)
            self.calibration(body)[field] = "  "

            with pytest.raises(TrackRecordUnusable, match=field):
                parse(body)

    def test_a_range_that_holds_less_than_it_claims_is_not_refused(self) -> None:
        """The check this section deliberately does not make.

        #82 exists to narrow this distribution. If it lands, coverage falls toward the claim
        and may cross it, and a parser treating that as corruption would make the repair
        unshippable while looking like a safety check. The direction belongs to whatever
        renders the numbers, not to the schema.
        """
        body = deepcopy(VALID)
        self.calibration(body)["leads"][0]["all_hours"]["covered"] = 0.86
        self.calibration(body)["leads"][0]["all_hours"]["widening_factor"] = 1.14

        parsed = parse(body).range_calibration

        assert parsed.leads[0].all_hours.covered == 0.86
        assert parsed.leads[0].all_hours.widening_factor == 1.14


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
        assert record.scored
        assert record.served
        assert record.held_out.go_call.days_flagged > 0

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

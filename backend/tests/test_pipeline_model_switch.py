"""Which Amplification Model runs, and how that is changed without touching code.

Ticket #13. ADR 0006 requires the Heuristic Baseline to remain permanently runnable and the
two models to be swappable behind one interface; ADR 0001 is why the seam exists at all.
This file owns the seam. `test_learned.py` owns what the learned model computes.
"""

from __future__ import annotations

import pytest

from nazarenow.models import HeuristicBaseline, LearnedAmplification
from nazarenow.pipeline import (
    DEFAULT_MODEL,
    MODEL_VARIABLE,
    MODELS,
    amplification_model,
    calibration_of,
)


def test_the_learned_model_ships_active() -> None:
    """#13's decision, pinned where it can be read.

    The learned model is worse across all held-out hours and better in every band above
    3 m, which is the regime the system calls in — `analysis/amplification_model/README.md`
    states both halves. Reversing that decision should be a deliberate edit that fails a
    test, not a default quietly drifting back.
    """
    assert DEFAULT_MODEL == "learned-amplification"
    assert isinstance(amplification_model(), LearnedAmplification)


def test_the_baseline_is_still_runnable(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR 0006: the benchmark is not deleted when a learned model arrives.

    A release that could no longer run the baseline could no longer justify the model it
    ships, because every figure in `analysis/` is a comparison against it.
    """
    monkeypatch.setenv(MODEL_VARIABLE, "heuristic-baseline")

    model = amplification_model()

    assert isinstance(model, HeuristicBaseline)
    assert model.name == "heuristic-baseline"


def test_the_variable_is_read_per_run_not_at_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """The reason `amplification_model` builds its model per run rather than at import.

    A value captured at import would need a restart to take effect, and the only writer in
    this system is a scheduled batch job — so "switchable without code changes" would have
    quietly meant "switchable by redeploying".
    """
    monkeypatch.setenv(MODEL_VARIABLE, "heuristic-baseline")
    first = amplification_model()

    monkeypatch.setenv(MODEL_VARIABLE, "learned-amplification")
    second = amplification_model()

    assert first.name != second.name


def test_an_empty_variable_falls_back_to_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unset variable and one set to the empty string are the same intent.

    Follows `NAZARENOW_DB` and `NAZARENOW_THRESHOLDS`, which both read `or None`. A
    deployment template that exports the name with no value would otherwise fail the run.
    """
    monkeypatch.setenv(MODEL_VARIABLE, "")

    assert amplification_model().name == DEFAULT_MODEL


def test_an_unknown_name_fails_the_run_rather_than_falling_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A typo must not silently run the other model.

    It would leave the store recording one model for a deployment whose operator believed it
    was running the other, and every figure read off that run would be attributed to the
    wrong component. The message names the options, because a run that fails at 03:00 is read
    from a log.
    """
    monkeypatch.setenv(MODEL_VARIABLE, "leaned-amplification")

    with pytest.raises(ValueError, match="leaned-amplification"):
        amplification_model()


def test_every_model_reports_the_name_it_is_keyed_by() -> None:
    """The store records `model.name`, and this switch is keyed on the same string.

    If they drifted, the name in the record would not be the name you could set to reproduce
    the run — which is the one question a stored model name has to answer.
    """
    for name, build in MODELS.items():
        assert build().name == name


def test_both_models_offer_their_calibration_to_the_store() -> None:
    """`calibration_of` reads `.thresholds` off whatever model ran.

    The learned model exposes the same threshold set because it really does delegate every
    condition to it — so a run is recorded against the numbers that actually judged its
    hours, whichever model produced the height.
    """
    for build in MODELS.values():
        calibration = calibration_of(build())

        assert calibration is not None
        assert calibration["gold_days_total"] == 38

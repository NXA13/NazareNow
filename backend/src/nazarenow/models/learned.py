"""The learned Amplification Model: a fitted correction, applied to the forecast's own sea.

Ticket #13, and the first thing in this system entitled to emit a number that differs from
its input. `analysis/amplification_model/` is the fit; this is the inference, and it is
deliberately a dot product — ADR 0004 requires the model be cheap because #15 will run it
hundreds of times per forecast date, and a pure-Python line keeps that obviously true without
putting numpy behind the API.

**What it learned is not Amplification, and this module does not claim it.** It was fitted to
predict the Proxy Target — Significant Wave Height at Monican02 — from the Hindcast's Combined
Sea at a node 1.12 km away. That is the reanalysis's local error at one mooring, not the
canyon's transformation toward Praia do Norte, which is in Face Height and has no historical
archive (ADR 0002). CONTEXT.md's definition of Amplification is specific. The class fills the
Amplification Model *slot*; the name of the slot is not a claim about what it knows.

**Its verdicts are the Heuristic Baseline's, delegated rather than reimplemented.** The
Decision Model branches on `Condition` identities, so anything this class did differently
there would silently re-tier days. It has no business doing so: the shipped
`minimum_significant_wave_height_m` was fitted against offshore Open-Meteo wave height, and
what this model emits is a predicted Proxy Target — a different quantity, which that bar
cannot judge. So the rule keeps deciding *whether*, and the model only changes *how big*.
ADR 0006 keeps the baseline permanently anyway; this makes the dependency explicit rather
than leaving two copies of one rule to drift apart.

**Readings are restated in reanalysis units on the way in.** The fit is on Copernicus IBI and
the Pipeline Run consumes Open-Meteo, which `analysis/overlap/README.md` measured reads about
half a second short on swell period, with a compressed range rather than a clean offset. This
is the second train/serve skew — the one ADR 0004 does not cover, because a Forecast Error
Profile corrects forecast noise and not a fixed difference between two products. The
translation constants ride in the parameter file so this module needs no analysis code.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

from nazarenow.thresholds import Thresholds

from .base import Prediction
from .heuristic import HeuristicBaseline

PARAMETERS_PATH = Path(__file__).resolve().parent.parent / "amplification.json"

TRANSLATED = {
    "significant_wave_height": "significant_wave_height_m",
    "swell_period": "swell_period_s",
}
"""The readings that arrive in operational units and must be restated before use.

Only these two. `analysis/overlap/measure.py` fits a translation for exactly this pair and
deliberately not for the bearings — the measured direction offset is 1-3 degrees, far below
the resolution at which anything decides, and translating it would be arithmetic dressed up
as precision.

**Wind is untranslated, but not for the reason this file used to give.** It said wind reached
the fit and the Pipeline Run alike from ERA5. The fit does read ERA5; a Pipeline Run reads
Open-Meteo's *forecast* product, so the wind feature crosses the same product boundary the two
readings above do. #51 measured that boundary over three Big-Wave Seasons
(`analysis/wind_products/README.md`): the forecast product reads about 1.8 km/h lighter. At
this model's wind coefficient of about -0.007 m per km/h that moves a prediction by roughly
**0.01 m** — against a measured Amplification error of 0.356 m and a served MAE near 0.29 m.

So it stays untranslated because the correction is a hundredth of the error it would sit
inside, which is a measurement rather than a premise. The exemption *threshold* crosses the
same boundary and was translated, because there a 2 km/h shift lands on a bar with 0.2 km/h
of margin — same gap, different consequence, because a threshold has an edge and a coefficient
does not.
"""

FEATURES: dict[str, Callable[[dict[str, float]], float]] = {
    "combined_sea_m": lambda r: r["significant_wave_height"],
    "swell_height_m": lambda r: r["swell_height"],
    "swell_period_s": lambda r: r["swell_period"],
    "swell_direction_sin": lambda r: math.sin(math.radians(r["swell_direction"])),
    "swell_direction_cos": lambda r: math.cos(math.radians(r["swell_direction"])),
    "wind_speed_kmh": lambda r: r["wind_speed"],
    "wind_direction_sin": lambda r: math.sin(math.radians(r["wind_direction"])),
    "wind_direction_cos": lambda r: math.cos(math.radians(r["wind_direction"])),
    "combined_sea_x_period": lambda r: r["significant_wave_height"] * r["swell_period"],
}
"""Every feature name the parameter file may use, built from *translated* readings.

Mirrors `features()` in `analysis/amplification_model/train.py`, and `train.py --check` pins
the two against each other by driving this dictionary directly. Two encodings of one feature
vector that agree only by inspection is a defect nothing on either side can see: the model
would keep predicting, using the wrong coefficient for each column.

Bearings become a sine and a cosine because a linear term on degrees claims 359 and 1 are 358
apart. That discontinuity would sit at north, a little clockwise of the canyon's arc.
"""


def load_parameters(path: Path | None = None) -> dict[str, Any]:
    """The fitted parameters, read from disk on each call.

    Not cached at import, for the reason `pipeline.amplification_model` gives about the
    thresholds: a Pipeline Run builds its model fresh, so a refit takes effect on the next
    scheduled run rather than at the next restart, and a malformed file fails that run with
    its cause attached instead of taking down the API at import.
    """
    target = path if path is not None else PARAMETERS_PATH
    if not target.exists():
        raise FileNotFoundError(
            f"{target} is missing; produce it with "
            "`.venv/Scripts/python.exe analysis/amplification_model/train.py`"
        )
    return json.loads(target.read_text(encoding="utf-8"))


class LearnedAmplification:
    """Predicts the Proxy Target from Offshore Conditions. Deterministic, and a dot product."""

    name = "learned-amplification"

    def __init__(
        self,
        parameters: dict[str, Any] | None = None,
        thresholds: Thresholds | None = None,
    ) -> None:
        """Validates the parameter file up front rather than on first prediction.

        A run that is going to fail on a malformed file should fail before it has written
        half a forecast, and `run_pipeline` records a construction failure with its cause.
        """
        self.parameters = parameters if parameters is not None else load_parameters()
        self.baseline = HeuristicBaseline(thresholds)
        self._features = tuple(self.parameters["features"])
        self._coefficients = tuple(float(v) for v in self.parameters["coefficients"])
        self._intercept = float(self.parameters["intercept"])
        self._translations = self.parameters.get("translations", {})
        self._inversions: dict[str, tuple[float, float]] = {}
        self._validate()

    def _validate(self) -> None:
        if len(self._features) != len(self._coefficients):
            raise ValueError(
                f"{len(self._features)} features but {len(self._coefficients)} coefficients; "
                "a parameter file whose two lists disagree cannot be applied in either order"
            )
        unknown = [name for name in self._features if name not in FEATURES]
        if unknown:
            raise ValueError(
                f"parameter file names features this code cannot build: {', '.join(unknown)}. "
                f"Known features are {', '.join(sorted(FEATURES))}. Treating them as zero "
                "would drop a term from the fit and keep predicting."
            )
        missing = [name for name in TRANSLATED.values() if name not in self._translations]
        if missing:
            raise ValueError(
                f"parameter file carries no translation for: {', '.join(missing)}. The fit is "
                "in Copernicus IBI units and the Pipeline Run reads Open-Meteo; applying the "
                "coefficients untranslated would be wrong by about the size of the offset and "
                "entirely plausible (analysis/overlap/README.md)."
            )

        # Parsed here, not in `_restate`, so a translation that is present but unusable fails
        # construction like a missing one. Checking only that the *keys* exist left a
        # non-numeric or zero slope to raise mid-run, on the first hour of a Pipeline Run —
        # which is precisely the failure this class's docstring promises to move up front.
        unusable = []
        for variable in TRANSLATED.values():
            translation = self._translations[variable]
            try:
                slope = float(translation["slope"])
                intercept = float(translation["intercept"])
            except (KeyError, TypeError, ValueError):
                unusable.append(f"{variable} (needs a numeric slope and intercept)")
                continue
            if slope == 0:
                unusable.append(f"{variable} (slope 0 cannot be inverted)")
                continue
            self._inversions[variable] = (slope, intercept)
        if unusable:
            raise ValueError(
                f"parameter file carries an unusable translation for: {', '.join(unusable)}. "
                "The fit that produced it did not measure a relationship this code can invert."
            )

    @property
    def calibrated(self) -> bool:
        """The baseline's flag, because the baseline's thresholds decided the conditions.

        Not a claim about the fit. Nothing in `analysis/amplification_model/` calibrates a
        threshold — it fits a height correction, and the tiering it is reported against is
        #12's. Reporting `True` on the strength of having been trained would tell the
        interface a calibration story about the wrong component.
        """
        return self.baseline.calibrated

    @property
    def thresholds(self) -> Thresholds:
        """Exposed so `pipeline.calibration_of` records what actually judged the hours.

        `calibration_of` reads this attribute off the model and stores its provenance. The
        learned model really does decide against these thresholds — it delegates every
        condition to them — so surfacing them is accurate rather than convenient.
        """
        return self.baseline.thresholds

    def _restate(self, readings: dict[str, float]) -> dict[str, float]:
        """Operational readings in reanalysis units.

        `Translation` is fitted as `operational = slope x reanalysis + intercept`, so the
        model's own units are reached by inverting it. Readings without a translation are
        carried through unchanged, which is the deliberate choice `TRANSLATED` documents.

        Every inversion here was parsed and checked in `_validate`, so this arithmetic has
        no failure of its own to report.
        """
        restated = dict(readings)
        for reading, variable in TRANSLATED.items():
            slope, intercept = self._inversions[variable]
            restated[reading] = (readings[reading] - intercept) / slope
        return restated

    def predict(self, readings: dict[str, float]) -> Prediction:
        restated = self._restate(readings)
        height = self._intercept + sum(
            coefficient * FEATURES[name](restated)
            for name, coefficient in zip(self._features, self._coefficients, strict=True)
        )

        return Prediction(
            # Floored, because a line fitted on 2-6 m seas has no obligation to stay positive
            # when extrapolated to a flat calm. A negative Significant Wave Height is not a
            # cautious prediction; it is a number with no physical reading, and it would flow
            # into the store and onto the page like any other.
            significant_wave_height=max(height, 0.0),
            # The rule decides whether; the model only decides how big. Delegated to the real
            # object so the two cannot drift, and compared outcome-for-outcome in
            # `test_learned.py` so a future refactor cannot quietly stop delegating.
            conditions=self.baseline.predict(readings).conditions,
        )

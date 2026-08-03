"""Model Spread: how much the independent wave models disagree about a date.

ADR 0003 makes this the system's uncertainty estimate. No ensemble marine forecast is
available to us, so several independent models are asked about the same date and their
disagreement is the doubt. Narrow spread means confidence; wide spread means doubt.

**Each organisation votes once.** Five model identifiers at Praia do Norte are three
organisations — EWAM and GWAM are both DWD, and the two GFS Wave resolutions are both NCEP.
Two resolutions of one centre's model share its physics, its assimilation and its bugs, so
counting them separately makes the ensemble look twice as corroborated as it is. That is the
concrete meaning of ADR 0003's word *independent*, and it is what keeps the number comparable
when one member drops out at its horizon: DWD still has GWAM, so the vote count does not move.

**This is an upper bound on disagreement, not a calibrated uncertainty.** The models publish
on different cycles and their runs are not aligned — run age cannot be read from the provider
at all (`analysis/model_spread/`). #8 measured what that costs: staleness accounts for about
6% of the spread at one day's Lead Time and up to 29% at six. It is safe to leave uncorrected
only because the error has a direction. Sampling two providers at different run ages can make
them look more different than they are but cannot hide genuine agreement, so the contamination
inflates the spread, and an inflated spread reads as more doubt. It errs toward caution and
never toward a Go Call that should not have been issued.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

# The roster, mapped to the organisation that runs each model. ADR 0003 named four models
# including ECMWF WAM, which returns a null Swell partition here and is unusable whatever
# the quality of its wave model; `analysis/forecast_models/` carries the per-model evidence.
PROVIDERS = {
    "meteofrance_wave": "MeteoFrance",
    "dwd_ewam": "DWD",
    "dwd_gwam": "DWD",
    "ncep_gfswave025": "NCEP",
    "ncep_gfswave016": "NCEP",
}

ORGANISATIONS = sorted(set(PROVIDERS.values()))

MINIMUM_PROVIDERS = 2
"""Below this there is no disagreement to measure.

One opinion is not an ensemble, and a spread of zero from a single provider is not confidence
— it is silence wearing confidence's clothes. A date that cannot reach two organisations
carries no Model Spread at all rather than a reassuring number.
"""


@dataclass(frozen=True)
class Spread:
    """One date's disagreement on one variable, and who contributed to it.

    `providers` travels with the number because a spread computed from two organisations and
    one computed from three are not comparable, and nothing else in the record would say
    which happened. ADR 0003's uncertainty estimate degrades when a provider is unavailable;
    it must degrade *visibly*.
    """

    variable: str
    value: float
    providers: tuple[str, ...]
    models_reporting: int

    @property
    def degraded(self) -> bool:
        """Whether this rests on fewer organisations than the full roster."""
        return len(self.providers) < len(ORGANISATIONS)


def by_provider(readings: dict[str, float]) -> dict[str, float]:
    """Collapse each organisation's models to one opinion: the median of what it ran.

    The median rather than the mean, so a single member returning an outlier cannot drag its
    organisation's vote. With two members the two are equivalent; with one it is that model.
    """
    grouped: dict[str, list[float]] = {}
    for model, value in readings.items():
        if model not in PROVIDERS:
            raise KeyError(
                f"{model!r} is not on the roster; a model whose organisation is unknown "
                "cannot be given a vote, and giving it one would silently change the "
                "ensemble's size"
            )
        grouped.setdefault(PROVIDERS[model], []).append(value)
    return {provider: statistics.median(values) for provider, values in grouped.items()}


def spread_of(values: list[float]) -> float:
    """Disagreement as the full range, not the standard deviation.

    With three opinions a standard deviation is computed on too few points to mean what its
    name implies, and it shrinks when one member is missing even if the survivors disagree
    exactly as much. The range says the plain thing: the most and least these forecasters
    think, and the gap between.
    """
    if len(values) < MINIMUM_PROVIDERS:
        raise ValueError("spread needs at least two opinions; one model is not an ensemble")
    return max(values) - min(values)


def derive(variable: str, readings: dict[str, float | None]) -> Spread | None:
    """One variable's Model Spread from the models that reported, or `None` if too few did.

    `None` rather than zero, and rather than raising. A provider being unavailable degrades
    the uncertainty estimate rather than failing the Pipeline Run (ADR 0003), so this has to
    be an outcome the caller stores as "not measurable" — a zero here would be indistinguishable
    from perfect agreement and would read as maximum confidence at exactly the moment the
    system knows least.
    """
    reporting = {model: value for model, value in readings.items() if value is not None}
    if not reporting:
        return None
    opinions = by_provider(reporting)
    if len(opinions) < MINIMUM_PROVIDERS:
        return None
    return Spread(
        variable=variable,
        value=spread_of(list(opinions.values())),
        providers=tuple(sorted(opinions)),
        models_reporting=len(reporting),
    )

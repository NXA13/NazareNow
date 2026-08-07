"""What is Open-Meteo's Swell, in Copernicus terms?

Ticket #39, acceptance criterion 3, and the one question on that ticket that can silently
invalidate everything downstream of it.

The shipped thresholds were fitted on Open-Meteo's operational Swell — `swell_wave_height`,
`swell_wave_period`, `swell_wave_direction`. The reanalysis publishes a **partitioned**
spectrum instead: a primary swell train (`*_SW1`) and a secondary one (`*_SW2`). Nobody has
established which of those Open-Meteo is serving. #36 read the documentation of both and
could not settle it (`analysis/waverys/README.md`, "What could not be verified", items 1
and 2).

Two candidate mappings, and they are not close to each other:

  * **SW1 alone** — Open-Meteo reports the dominant swell train.
  * **SW1 and SW2 combined** — Open-Meteo reports the whole swell field. Partition
    *energies* add, so a combined height is `sqrt(VHM0_SW1² + VHM0_SW2²)`, never the sum.

Getting this wrong does not look like a units bug. It looks like model error: feed SW1 into
a bar fitted on a combined height and the reanalysis reads systematically low, the recall
falls, and the natural conclusion is that the reanalysis is worse — which would be a
conclusion about the wrong thing. #11 already showed that mean-versus-peak period moves this
project's numbers, so this class of mistake has bitten here before.

**The measurement only works on the hours where the answer differs.** When the second train
is absent — and `VHM0_SW2` reaches exactly 0.00 in this record — both hypotheses predict the
same number, and an hour like that cannot tell them apart however well it fits. Averaged
over the whole overlap those hours dominate and every candidate scores about the same. So
the headline is computed on the **discriminating** subset, where SW2 carries real energy
beside SW1, and the full-overlap figures are reported beside it to show the dilution rather
than hide it.

**Direction is the sharpest instrument here**, and it is nearly free. Combining two swell
trains from different bearings gives a direction unlike either one, so if Open-Meteo's
`swell_wave_direction` tracks `VMDR_SW1` through the hours when the trains disagree, that is
a partition being reported and not a field.

**What this cannot settle.** The two series read different grid points (Open-Meteo's MFWAM
node is ~2 km from the Proxy Target, IBI's is 1.12 km) and different model runs — an
operational forecast against a reanalysis. So a candidate is not expected to match exactly,
and the question is only ever which one fits *better*, by a margin larger than that
background disagreement. The background is quantified here as the Combined Sea comparison,
where both sources publish the same unambiguous quantity and any gap is the grid, the run
and nothing else.

Run:
    .venv/Scripts/python.exe analysis/overlap/measure.py
    .venv/Scripts/python.exe analysis/overlap/measure.py --check
"""

from __future__ import annotations

import csv
import math
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUTPUT = HERE / "output"

sys.path.insert(0, str(ROOT / "analysis" / "backtest"))
sys.path.insert(0, str(ROOT / "backend" / "src"))

import hindcast  # noqa: E402
import reanalysis  # noqa: E402

SECOND_TRAIN_SHARE = 0.5
"""How much energy the second train needs before an hour can discriminate.

`VHM0_SW2 >= 0.5 * VHM0_SW1` — the secondary train at least half the height of the primary,
so combining them moves the height by at least 12% and the direction by a real bearing. Set
higher and the subset starves; set lower and it fills with hours where both hypotheses agree
to within the noise, which is the failure this constant exists to avoid.
"""

BIG_SWELL_HEIGHT_M = 3.0
"""The regime the thresholds actually operate in.

Reported separately because the QUID's headline skill numbers are averages over all
conditions, and #36 recorded that they "say nothing about XXL Days". A mapping that fits in
1 m slop and fails at 5 m would be worse than useless here.
"""


@dataclass(frozen=True)
class Paired:
    """One hour where both sources reported, with both candidates computed."""

    at: str
    operational_height: float
    operational_period: float
    operational_direction: float
    operational_combined_sea: float
    sw1_height: float
    sw1_period: float
    sw1_direction: float
    sw2_height: float
    sw2_period: float
    sw2_direction: float
    reanalysis_combined_sea: float

    @property
    def combined_height(self) -> float:
        return reanalysis.combined_swell_height(self.sw1_height, self.sw2_height)

    @property
    def combined_period(self) -> float:
        return energy_weighted(self.sw1_period, self.sw1_height, self.sw2_period, self.sw2_height)

    @property
    def combined_direction(self) -> float:
        return vector_mean_direction(
            self.sw1_direction, self.sw1_height, self.sw2_direction, self.sw2_height
        )

    @property
    def discriminating(self) -> bool:
        return self.sw2_height >= SECOND_TRAIN_SHARE * self.sw1_height


def energy_weighted(value1: float, height1: float, value2: float, height2: float) -> float:
    """Two partition values averaged by the energy of their trains.

    Wave energy goes as the square of significant height, so the weights are `h²`. This is
    the most defensible way to collapse two periods into one — and it is still a construction
    rather than a quantity any model publishes, which is exactly why it is being tested
    against the alternative rather than assumed.
    """
    weight1, weight2 = height1**2, height2**2
    if weight1 + weight2 == 0:
        return value1
    return (value1 * weight1 + value2 * weight2) / (weight1 + weight2)


def vector_mean_direction(
    direction1: float, height1: float, direction2: float, height2: float
) -> float:
    """Two bearings averaged as vectors, weighted by energy.

    Averaging bearings arithmetically puts the mean of 350° and 10° at 180°, pointing at
    precisely the opposite ocean. Resolving to components and back is the only way this
    reads correctly across the 0/360 join.
    """
    weight1, weight2 = height1**2, height2**2
    if weight1 + weight2 == 0:
        return direction1
    east = weight1 * math.sin(math.radians(direction1)) + weight2 * math.sin(
        math.radians(direction2)
    )
    north = weight1 * math.cos(math.radians(direction1)) + weight2 * math.cos(
        math.radians(direction2)
    )
    return math.degrees(math.atan2(east, north)) % 360


def circular_difference(a: float, b: float) -> float:
    """Signed degrees from `b` to `a`, taking the short way round.

    359° and 1° are 2° apart, not 358°. A direction comparison written without this reports
    enormous errors a handful of times a year and buries the real answer in them.
    """
    return (a - b + 180.0) % 360.0 - 180.0


@dataclass(frozen=True)
class Fit:
    """How well one candidate tracks what the thresholds were fitted on."""

    name: str
    n: int
    bias: float
    mae: float
    rmse: float

    def row(self) -> list[str]:
        return [
            self.name,
            str(self.n),
            f"{self.bias:+.3f}",
            f"{self.mae:.3f}",
            f"{self.rmse:.3f}",
        ]


def score(name: str, pairs: list[tuple[float, float]], circular: bool = False) -> Fit:
    """Bias, MAE and RMSE of a candidate against the operational reading.

    Bias is signed on purpose: a candidate that is right on average but noisy is a different
    problem from one that is consistently 40 cm low, and only the second can be a mapping
    mistake.
    """
    if not pairs:
        return Fit(name=name, n=0, bias=0.0, mae=0.0, rmse=0.0)
    errors = [
        circular_difference(candidate, actual) if circular else candidate - actual
        for candidate, actual in pairs
    ]
    n = len(errors)
    return Fit(
        name=name,
        n=n,
        bias=sum(errors) / n,
        mae=sum(abs(e) for e in errors) / n,
        rmse=math.sqrt(sum(e * e for e in errors) / n),
    )


def pair_hours(product: reanalysis.Product = reanalysis.IBI) -> list[Paired]:
    """Every hour where the operational feed and a reanalysis both reported.

    Joined on the Nazaré local stamp, which is what the operational series is keyed by. The
    autumn summer-time fold renders two UTC hours as the same local stamp once a year; the
    operational side already keeps only one of them (`hindcast._parse` builds a dict on that
    key), so the join inherits that and loses nothing further. It is one hour a year and it
    is noted rather than corrected here, because correcting it means changing the series the
    shipped thresholds were fitted on, which is not this ticket's business.

    Runs against WAVERYS too. It is 3-hourly, so it pairs on roughly a third as many hours —
    which is the point of it being the cross-check rather than the primary. Two independent
    reanalyses reaching the same conclusion about the mapping is worth more than one, and
    this is the cheapest place to ask them.
    """
    operational = hindcast.operational_swell().readings
    series = reanalysis.read(product)

    paired: list[Paired] = []
    for reading in series.rows():
        at = str(reading["at"])
        actual = operational.get(at)
        if actual is None:
            continue
        paired.append(
            Paired(
                at=at,
                operational_height=float(actual["swell_wave_height"]),
                operational_period=float(actual["swell_wave_period"]),
                operational_direction=float(actual["swell_wave_direction"]),
                operational_combined_sea=float(actual["wave_height"]),
                sw1_height=float(reading["VHM0_SW1"]),
                sw1_period=float(reading["VTM01_SW1"]),
                sw1_direction=float(reading["VMDR_SW1"]),
                sw2_height=float(reading["VHM0_SW2"]),
                sw2_period=float(reading["VTM01_SW2"]),
                sw2_direction=float(reading["VMDR_SW2"]),
                reanalysis_combined_sea=float(reading["VHM0"]),
            )
        )
    return paired


def fits(hours: list[Paired]) -> list[Fit]:
    """Both candidates, for each of the three variables, over one subset of hours."""
    return [
        score("height: SW1 alone", [(h.sw1_height, h.operational_height) for h in hours]),
        score(
            "height: SW1+SW2 combined", [(h.combined_height, h.operational_height) for h in hours]
        ),
        score("period: VTM01_SW1", [(h.sw1_period, h.operational_period) for h in hours]),
        score(
            "period: energy-weighted",
            [(h.combined_period, h.operational_period) for h in hours],
        ),
        score(
            "direction: VMDR_SW1",
            [(h.sw1_direction, h.operational_direction) for h in hours],
            circular=True,
        ),
        score(
            "direction: energy-weighted",
            [(h.combined_direction, h.operational_direction) for h in hours],
            circular=True,
        ),
        # The control. Both sources publish the Combined Sea unambiguously, so whatever gap
        # shows up here is the grid point and the model run — the floor any Swell candidate
        # should be judged against rather than against zero.
        score(
            "control: Combined Sea",
            [(h.reanalysis_combined_sea, h.operational_combined_sea) for h in hours],
        ),
    ]


@dataclass(frozen=True)
class Translation:
    """A fitted straight line from a reanalysis reading to the operational equivalent.

    #39 calibrates on the reanalysis in its native units — the fit stays internally
    consistent that way, and the backtest reports numbers that belong to the series it
    scored. But `thresholds.json` is read by the **live Pipeline Run**, which consumes
    Open-Meteo and never sees a reanalysis. A bar fitted at 13.5 s of reanalysis period is
    roughly 13.0 s of operational period, and shipping the untranslated number would quietly
    make the deployed system half a second stricter than the fit intended.

    So the three fitted scalars are translated on the way out, and nothing else is. Applying
    the transform to the 134,160-row series instead would push its error through the fit
    itself; applying it to three numbers keeps it where it can be read.

    **Each quantity is fitted on the hours its own measurement supports**, and `regime` says
    which those were. Swell period is fitted on the big-swell subset, because that is the
    regime the bars operate in and the relationship genuinely is not the same at 1 m
    (`README.md`, finding 1). Height is not: see `FITTINGS`, where #58 records why the same
    reasoning does not survive being applied to it.
    """

    variable: str
    slope: float
    intercept: float
    n: int
    residual_rmse: float
    source: str = "reanalysis"
    regime: str = "hours from an unrecorded subset"
    """What the line maps *from*, and the subset it was fitted on.

    The light-wind exemption is translated from a different pairing — ERA5 against the
    forecast product, fitted in a band of wind speed rather than a band of wave height — and
    the shipped `method` blurb quotes `describe()` verbatim, so a transform that could not say
    what it was fitted on would put a sentence about 3 m seas next to a wind speed.

    **The default states nothing rather than guessing.** It used to default to the big-swell
    subset, which was true of every real caller while both quantities shared one. Since #58
    they do not, and `train.py` exports this string to `amplification.json` as `fitted_on` —
    so a defaulted `Translation` would publish a specific claim about hours it was never
    fitted on. Every production caller passes `regime` explicitly; the default is now reached
    only by synthetic transforms in self-tests, where saying nothing is the honest answer.
    """

    def apply(self, value: float) -> float:
        return self.slope * value + self.intercept

    def invert(self, value: float) -> float:
        """An operational reading restated in reanalysis units.

        The direction `backtest.py` needs. The shipped bars are in Open-Meteo units, and
        scoring them against a reanalysis panel without converting would apply a bar to a
        series that reads about half a second longer — which is the +128% over-firing
        `README.md` measures, arriving as a result rather than as a bug.
        """
        return (value - self.intercept) / self.slope

    def describe(self) -> str:
        return (
            f"{self.variable}: operational = {self.slope:.4f} x {self.source} "
            f"{self.intercept:+.4f} (fitted on {self.n} {self.regime}, "
            f"residual RMSE {self.residual_rmse:.3f})"
        )


def least_squares(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    """Slope, intercept and residual RMSE of `ys` on `xs`."""
    n = len(xs)
    if n < 2:
        raise ValueError("a translation needs at least two hours to fit")
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx == 0:
        raise ValueError("every hour carries the same reading; the slope is undefined")
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    residuals = [y - (slope * x + intercept) for x, y in zip(xs, ys, strict=True)]
    return slope, intercept, math.sqrt(sum(r * r for r in residuals) / n)


@dataclass(frozen=True)
class Fitting:
    """One quantity's transform: which hours it is fitted on, and what it reads from them.

    The subset travels *with* the quantity rather than beside it, because the two are only
    correct together. Fitting a line on one subset and describing it with another's hour
    count is precisely the defect #58 was filed about, and a shape that cannot express the
    two separately makes that defect unavoidable rather than merely possible.
    """

    variable: str
    regime: str
    select: Callable[[Paired], bool]
    reanalysis_side: Callable[[Paired], float]
    operational_side: Callable[[Paired], float]
    """The two readings the line is fitted between, named for the series each comes from.

    Not `candidate`/`actual`: `translation_shape.py` uses *Candidate* for a whole transform
    shape under test, and one word meaning two things across two modules that import each
    other is how a reader ends up fitting the wrong pair.
    """

    def hours(self, hours: list[Paired]) -> list[Paired]:
        """The hours this quantity is fitted on, out of a paired set.

        On `Fitting` rather than at each call site because three of them want it —
        `translations_from`, and two in `translation_shape.py` — and a subset rule that lives
        in one place cannot be applied inconsistently in another.
        """
        return [hour for hour in hours if self.select(hour)]


FITTINGS: tuple[Fitting, ...] = (
    Fitting(
        variable="significant_wave_height_m",
        regime="overlapping hours",
        select=lambda _: True,
        reanalysis_side=lambda h: h.reanalysis_combined_sea,
        operational_side=lambda h: h.operational_combined_sea,
    ),
    Fitting(
        variable="swell_period_s",
        regime=f"reanalysis Combined Sea >= {BIG_SWELL_HEIGHT_M:g} m",
        select=lambda h: h.reanalysis_combined_sea >= BIG_SWELL_HEIGHT_M,
        reanalysis_side=lambda h: h.combined_period,
        operational_side=lambda h: h.operational_period,
    ),
)
"""The subset each quantity is fitted on, and why the two are not the same one (#58).

Until #58 both were fitted on the big-swell subset, on the reasoning in `Translation` — the
bars operate at 3 m and up, and the relationship is not the same at 1 m. That reasoning holds
for **swell period** and fails for **height**, and the difference is not a matter of taste:

* **Height is fitted on every overlapping hour.** Fitted on the narrow high slice instead, the
  line comes out `0.9412x + 0.3435`; fitted on the whole overlap it is `1.0127x + 0.0192`,
  very nearly the identity. The +0.34 m intercept is what fitting a line on a narrow high
  slice does to it, not a property of the two products. That intercept was not harmless,
  because `LearnedAmplification` **inverts this transform on every hour it serves** and the
  majority of served hours sit below 2 m, where the shipped line over-predicts Open-Meteo's
  Combined Sea by 0.22-0.27 m. A transform fitted only where the bars decide, but applied
  everywhere, is a transform fitted on the wrong hours.

* **Swell period keeps the big-swell subset**, because for it the regime dependence is real
  and measured. Refitted on all hours it gets *worse where it matters*: -0.232 s at 4-5 m
  against the shipped -0.015 s. #52 measured this; it is not an assumption.

The height subset is a `select` that admits everything rather than an absent filter, so that
both quantities are described the same way and neither can quietly acquire the other's hours.

**The swell period filter reads reanalysis Combined Sea, and #60 settled that it should.**
Until then it read `operational_height` — Open-Meteo's *Swell* height — while `train.py`, the
shipped `amplification.json`, `thresholds.json`'s `method` string and #52's own body all
described it as Combined Sea. The same 3 m bar against two different quantities, selecting
4,366 hours one way and 4,941 the other, with the shipped artifact's `fitted_on_hours: 4366`
proving which one ran. `CONTEXT.md` calls that distinction load-bearing and says conflating the
two silently invalidates the model's evaluation; this was that conflation, in shipped code.

Three things decided it, and the third is why it was a judgement call rather than a bug fix:

* **One concept, one definition.** `train.py` defines its own big-swell regime on
  `combined_sea_m`, the hindcast's Combined Sea. The Translation now names the same quantity,
  so "the regime the system calls in" means one thing across the two modules instead of two.

* **It is more accurate where it is measurable.** Against the reading the line claims to
  produce, on fixed input bands, the Combined Sea subset is better or equal on RMSE in all
  seven bands and better on bias in six.

* **It cost the Watch bar 0.1 s, and the Go Call bar nothing.** #60 measured the period subset
  in isolation from #58's height refit before anything moved. The Go Call bar — the one that
  costs a traveller a flight — is unchanged at 12.9 s. The Watch bar moves 11.5 s to 11.4 s,
  which before rounding is a shift of 0.044 s that happens to cross the 11.45 boundary.

The **reanalysis** side, not the operational one, because that is the quantity `train.py`
means and because a fitting subset is a statement about which hours the relationship is
characterised on — a question the truth side answers. Both were measured and they select 4,941
and 5,501 hours; they land on the same two bars, and the operational reading is additionally
worse than the old subset at 6 m and above.

The one place the old subset was better is 4-5 m, where bias goes -0.015 s to -0.077 s against
0.62 s of RMSE in that band. Named rather than averaged away, because it is the whole cost.
"""


def translations_from(hours: list[Paired]) -> dict[str, Translation]:
    """The transforms, from an already-paired set of hours.

    Split from `fit_translations` so the subset logic can be exercised on hours built to
    order, without the cache or the network — the two subsets being genuinely independent is
    the whole of #58, and it should be testable without needing a decade of real sea.
    """
    fitted: dict[str, Translation] = {}
    for fitting in FITTINGS:
        selected = fitting.hours(hours)
        if not selected:
            raise RuntimeError(
                f"no overlapping hours match {fitting.regime}, so {fitting.variable} cannot "
                "be fitted on the subset its measurement supports"
            )
        slope, intercept, rmse = least_squares(
            [fitting.reanalysis_side(h) for h in selected],
            [fitting.operational_side(h) for h in selected],
        )
        fitted[fitting.variable] = Translation(
            variable=fitting.variable,
            slope=slope,
            intercept=intercept,
            n=len(selected),
            residual_rmse=rmse,
            regime=fitting.regime,
        )
    return fitted


def fit_translations(product: reanalysis.Product = reanalysis.IBI) -> dict[str, Translation]:
    """The reanalysis-to-operational transform for each quantity a threshold is named in.

    Only height and swell period get one. The swell arc and the wind conditions are
    *verified* rather than fitted by `calibrate.py`, and the measured direction offset is
    1-3° against an arc 75° wide — far below the resolution at which that condition decides
    anything. Translating it would be arithmetic dressed up as precision.

    Each quantity is fitted on its own subset (`FITTINGS`). Callers get the same
    `dict[str, Translation]` they always did and none of them has to know which hours went
    into which line — the line carries that itself, in `regime` and `n`.
    """
    hours = pair_hours(product)
    if not hours:
        raise RuntimeError(
            f"{product.name}: no overlapping hours with the operational feed, so no "
            "transform can be fitted at all"
        )
    return translations_from(hours)


SUBSETS = (
    ("all overlapping hours", lambda h: True),
    ("discriminating (SW2 >= 0.5*SW1)", lambda h: h.discriminating),
    (
        f"big swell (>= {BIG_SWELL_HEIGHT_M:g} m)",
        lambda h: h.operational_height >= BIG_SWELL_HEIGHT_M,
    ),
    (
        "discriminating AND big swell",
        lambda h: h.discriminating and h.operational_height >= BIG_SWELL_HEIGHT_M,
    ),
)


def write_csv(rows: list[tuple[str, Fit]]) -> Path:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / "mapping_fits.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["subset", "candidate", "hours", "bias", "mae", "rmse"])
        for subset, fit in rows:
            writer.writerow([subset, *fit.row()])
    return path


def check() -> int:
    """Self-test the arithmetic, without the network or the cache."""
    failures: list[str] = []

    def expect(label: str, got: object, want: object) -> None:
        if got != want:
            failures.append(f"{label}: expected {want!r}, got {got!r}")

    # Energy weighting, not arithmetic averaging. Two trains of equal height average their
    # periods; a train with twice the height carries four times the weight.
    expect("equal trains average", energy_weighted(10.0, 2.0, 14.0, 2.0), 12.0)
    expect("a train twice as tall counts four times", energy_weighted(10.0, 2.0, 15.0, 1.0), 11.0)
    expect("no energy at all falls back to the first", energy_weighted(9.0, 0.0, 4.0, 0.0), 9.0)

    # The 0/360 join. Arithmetic averaging puts these at 180 — the opposite ocean.
    #
    # Compared circularly rather than by equality: the true answer is due north, and due
    # north comes back as either 0 or 360 depending on which side of zero the floating-point
    # east component lands. Both are the same bearing, and asserting one of them literally
    # would be a test of rounding rather than of the function.
    expect(
        "directions average across north",
        round(circular_difference(vector_mean_direction(350.0, 1.0, 10.0, 1.0), 0.0), 6),
        0.0,
    )
    expect(
        "an absent second train leaves the bearing alone",
        round(vector_mean_direction(300.0, 2.0, 100.0, 0.0), 6),
        300.0,
    )

    # ...and the same join in the error metric.
    expect("1 deg minus 359 deg is +2", round(circular_difference(1.0, 359.0), 6), 2.0)
    expect("359 deg minus 1 deg is -2", round(circular_difference(359.0, 1.0), 6), -2.0)
    expect("no wrap needed", round(circular_difference(280.0, 275.0), 6), 5.0)

    # A candidate identical to the reading scores zero on everything; one that is uniformly
    # high scores its offset as bias and as MAE, which is what makes bias readable as a
    # mapping mistake rather than as noise.
    perfect = score("same", [(3.0, 3.0), (4.0, 4.0)])
    expect(
        "an exact candidate has no bias",
        (perfect.bias, perfect.mae, perfect.rmse),
        (0.0, 0.0, 0.0),
    )
    offset = score("high", [(3.5, 3.0), (4.5, 4.0)])
    expect("a uniformly high candidate reads as bias", (offset.bias, offset.mae), (0.5, 0.5))

    # An empty subset must not divide by zero — it is a real outcome if the discriminating
    # filter turns out to select nothing.
    expect("an empty subset scores zero hours", score("none", []).n, 0)

    # The translation recovers a line it is given exactly. Written with the regression the
    # wrong way round it would still look plausible — the slope would simply be 1/2 instead
    # of 2 — and the shipped bar would be wrong in a direction nobody would notice.
    slope, intercept, rmse = least_squares([1.0, 2.0, 3.0], [3.0, 5.0, 7.0])
    expect("slope of a known line", round(slope, 9), 2.0)
    expect("intercept of a known line", round(intercept, 9), 1.0)
    expect("an exact line has no residual", round(rmse, 9), 0.0)

    # ...and the direction it is applied in. The reanalysis reads HIGH, so translating a
    # reanalysis bar into operational units must bring it DOWN.
    high = Translation(variable="swell_period_s", slope=0.9, intercept=0.0, n=10, residual_rmse=0.0)
    expect("a high-reading series translates downward", high.apply(15.0), 13.5)
    expect("inverting undoes applying", round(high.invert(high.apply(15.0)), 9), 15.0)
    expect("...and the other way round", round(high.apply(high.invert(13.5)), 9), 13.5)

    # Each quantity is fitted on the hours its own measurement supports, and #58 turns on the
    # two subsets really being independent. Built from synthetic hours rather than the real
    # pairing so this runs without the cache, and so the discriminating case can be made
    # sharp: the small hours carry a period reading wildly off the line the big hours sit on,
    # so a period transform that leaked them in could not still recover 3x - 2.
    #
    # Since #60 the hours also separate the two *quantities* that could gate the period
    # subset. `swell-decoy` has a big Swell height and a small Combined Sea, so the pre-#60
    # filter would have admitted it and the current one excludes it — and its period reading
    # is one of the off-line ones, so admitting it breaks the recovered line rather than
    # merely changing a count. Reverting `FITTINGS` to `operational_height` fails here.
    def hour(
        at: str, height: float, sea: float, operational_sea: float, sw1: float, period: float
    ) -> Paired:
        return Paired(
            at=at,
            operational_height=height,
            operational_period=period,
            operational_direction=300.0,
            operational_combined_sea=operational_sea,
            sw1_height=height,
            sw1_period=sw1,
            sw1_direction=300.0,
            sw2_height=0.0,
            sw2_period=0.0,
            sw2_direction=0.0,
            reanalysis_combined_sea=sea,
        )

    # Combined Sea sits on operational = 2x + 1 in every hour, big or small. Swell period
    # sits on operational = 3x - 2 in the big hours only. The first two columns after the
    # stamp are Swell height and Combined Sea, and `swell-decoy` is the hour where they
    # disagree about which side of 3 m it falls.
    below = [
        hour(f"small-{i}", 1.0, x, 2.0 * x + 1.0, 10.0, 0.0) for i, x in enumerate((1.0, 1.5, 2.0))
    ]
    below.append(hour("swell-decoy", 5.0, 2.5, 2.0 * 2.5 + 1.0, 10.0, 0.0))
    above = [
        hour(f"big-{i}", 4.0, x, 2.0 * x + 1.0, p, 3.0 * p - 2.0)
        for i, (x, p) in enumerate(((4.0, 1.0), (5.0, 2.0), (6.0, 3.0)))
    ]
    mixed = translations_from(below + above)

    height, period = mixed["significant_wave_height_m"], mixed["swell_period_s"]
    expect("height is fitted on every overlapping hour", height.n, 7)
    expect("swell period keeps the Combined Sea subset", period.n, 3)
    expect(
        "height recovers the line every hour sits on",
        (round(height.slope, 9), round(height.intercept, 9)),
        (2.0, 1.0),
    )
    expect(
        "swell period recovers the line only the big hours sit on",
        (round(period.slope, 9), round(period.intercept, 9)),
        (3.0, -2.0),
    )
    # The counts above could both be right by accident if the two transforms shared a subset
    # that happened to be everything. They must genuinely differ.
    expect("the two quantities are fitted on different subsets", height.n != period.n, True)
    expect("...and each says which subset that was", height.regime != period.regime, True)
    expect(
        "height says so in the prose the shipped file quotes",
        "overlapping hours" in height.describe(),
        True,
    )

    try:
        least_squares([2.0, 2.0], [1.0, 3.0])
    except ValueError:
        pass
    else:
        failures.append("least_squares: expected a ValueError when the slope is undefined")

    for failure in failures:
        print(f"FAIL {failure}")
    print("measure.py --check: " + ("FAILED" if failures else "all checks passed"))
    return 1 if failures else 0


def main() -> int:
    if "--check" in sys.argv:
        return check()

    rows: list[tuple[str, Fit]] = []
    for product in reanalysis.PRODUCTS:
        hours = pair_hours(product)
        if not hours:
            raise RuntimeError(
                f"{product.name}: no overlapping hours with the operational feed; the "
                "local-stamp join found nothing, which means one of the two series is keyed "
                "differently from what this script assumes"
            )
        print(
            f"\n{'=' * 78}\n{product.name.upper()} — {len(hours)} overlapping hours, "
            f"{hours[0].at[:10]} to {hours[-1].at[:10]}, every {product.cadence_hours} h\n"
        )
        for label, predicate in SUBSETS:
            subset = [h for h in hours if predicate(h)]
            print(f"{label}  -  {len(subset)} hours")
            if not subset:
                print("  (empty)\n")
                continue
            print(f"  {'candidate':32s} {'n':>6s} {'bias':>9s} {'MAE':>8s} {'RMSE':>8s}")
            for fit in fits(subset):
                rows.append((f"{product.name}: {label}", fit))
                print(
                    f"  {fit.name:32s} {fit.n:6d} {fit.bias:+9.3f} {fit.mae:8.3f} {fit.rmse:8.3f}"
                )
            print()

    print(f"\n{'=' * 78}\nTranslation applied to the fitted bars before they are shipped\n")
    for translation in fit_translations(reanalysis.IBI).values():
        print(f"  {translation.describe()}")
    print(
        "\n  Fitted on IBI, which is the primary series. Only the quantities "
        "`calibrate.py`\n  actually fits are translated — the swell arc and the wind "
        "conditions are verified\n  rather than fitted, and the measured direction offset "
        "is far inside the arc's width."
    )

    path = write_csv(rows)
    print(f"\nWrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

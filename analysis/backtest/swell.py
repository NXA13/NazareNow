"""Reconstructing Swell from Combined Sea, and measuring what that costs.

The Heuristic Baseline's period and direction thresholds are written in **Swell** terms.
The Hindcast that reaches back to 2011 carries only **Combined Sea** (`hindcast.py`). This
module bridges the two and — more importantly — reports how far the bridge can be trusted,
because the answer turns out to be "not far enough to score the period condition", and a
backtest that quietly hid that would be worse than no backtest.

**Why quantile mapping and not a regression.** Least squares fits a conditional mean, and a
conditional mean shrinks toward the centre of the distribution. The only part of this
distribution anyone cares about is the long-period tail, and shrinkage removes it: fitted
on the overlap, `swell period ~ mean period` predicts 22 hours at or above 14 s where the
truth has 95. Quantile mapping matches the two distributions instead, so the tail keeps its
size by construction. It is the standard correction for exactly this problem.

**Direction is not quantile-mapped.** A bearing is circular, and sorting bearings puts 359°
and 1° at opposite ends of a line they are two degrees apart on. It gets a constant offset
instead, which is what the data supports: the median difference between ERA5's Combined Sea
direction and the operational Swell direction is under two degrees.

Every number in the report comes from a **held-out** split — the map is fitted on 2022-2023
and scored on 2024-2025 — because a quantile map validated on its own fitting data agrees
with itself perfectly and has proven nothing.

Run:
    .venv/Scripts/python.exe analysis/backtest/swell.py --check
"""

from __future__ import annotations

import bisect
import math
import sys
from dataclasses import dataclass

FIT_YEARS = ("2022", "2023")
TEST_YEARS = ("2024", "2025")


@dataclass(frozen=True)
class QuantileMap:
    """Maps a value onto the distribution of a target variable, rank for rank.

    Holds both sorted samples rather than a fitted curve: the map is only ever used
    within the range it was fitted on, and keeping the samples means the report can state
    exactly how many hours stand behind any part of it.
    """

    source: tuple[float, ...]
    target: tuple[float, ...]

    @classmethod
    def fit(cls, source: list[float], target: list[float]) -> QuantileMap:
        if not source or not target:
            raise ValueError("a quantile map needs samples of both variables")
        return cls(source=tuple(sorted(source)), target=tuple(sorted(target)))

    def apply(self, value: float) -> float:
        """The target-distribution value at this value's rank in the source."""
        rank = bisect.bisect_left(self.source, value)
        fraction = rank / max(len(self.source) - 1, 1)
        index = min(int(round(fraction * (len(self.target) - 1))), len(self.target) - 1)
        return self.target[index]


def bearing_difference(a: float, b: float) -> float:
    """`a - b` as a signed angle in (-180, 180].

    Written out rather than subtracted directly because the naive difference between 359°
    and 1° is 358, and a direction condition comparing that against an arc would reject
    two bearings that are two degrees apart.
    """
    return (a - b + 180.0) % 360.0 - 180.0


@dataclass(frozen=True)
class BearingOffset:
    """A constant rotation from one direction variable to another."""

    degrees: float

    @classmethod
    def fit(cls, source: list[float], target: list[float]) -> BearingOffset:
        differences = sorted(bearing_difference(t, s) for s, t in zip(source, target, strict=True))
        return cls(degrees=_median(differences))

    def apply(self, value: float) -> float:
        return (value + self.degrees) % 360.0


def _median(values: list[float]) -> float:
    if not values:
        raise ValueError("no values")
    middle = len(values) // 2
    if len(values) % 2:
        return values[middle]
    return (values[middle - 1] + values[middle]) / 2.0


@dataclass(frozen=True)
class Agreement:
    """How well a reconstruction recovers a variable, on held-out hours.

    `rmse` is the honest average error. `recall` and `precision` are the ones that decide
    whether the reconstruction is usable here: the Heuristic Baseline does not consume the
    period, it consumes *whether the period cleared a threshold*, and a reconstruction can
    have a respectable RMSE while getting nearly every threshold crossing wrong.
    """

    hours: int
    rmse: float
    threshold: float
    recall: float
    precision: float
    predicted: int
    actual: int

    def line(self, label: str) -> str:
        return (
            f"{label:34s} RMSE {self.rmse:5.2f}  at >={self.threshold:g}: "
            f"recall {self.recall:4.0%}  precision {self.precision:4.0%}  "
            f"({self.predicted} predicted, {self.actual} actual)"
        )


def agreement(predicted: list[float], actual: list[float], threshold: float) -> Agreement:
    if len(predicted) != len(actual):
        raise ValueError("predicted and actual must describe the same hours")
    hours = len(actual)
    rmse = math.sqrt(sum((p - a) ** 2 for p, a in zip(predicted, actual, strict=True)) / hours)
    hit = {i for i, p in enumerate(predicted) if p >= threshold}
    true = {i for i, a in enumerate(actual) if a >= threshold}
    return Agreement(
        hours=hours,
        rmse=rmse,
        threshold=threshold,
        recall=len(hit & true) / len(true) if true else 0.0,
        precision=len(hit & true) / len(hit) if hit else 0.0,
        predicted=len(hit),
        actual=len(true),
    )


def bearing_agreement(predicted: list[float], actual: list[float], within: float) -> float:
    """The share of hours whose reconstructed bearing lands within `within` degrees."""
    pairs = zip(predicted, actual, strict=True)
    return sum(1 for p, a in pairs if abs(bearing_difference(p, a)) <= within) / len(actual)


def _check() -> int:
    """Self-test for the arithmetic above.

    Follows `gold_days/build.py`: these scripts are lint-only in CI because they need real
    data, so the parts that are pure arithmetic carry their own check rather than going
    unverified. Ticket #11 keeps the *backtest* out of the automated suite; that is about
    not pinning an accuracy figure to a test, and says nothing about leaving a circular
    subtraction untested.
    """
    failures: list[str] = []

    def expect(claim: str, condition: bool) -> None:
        if not condition:
            failures.append(claim)

    identity = QuantileMap.fit([1.0, 2.0, 3.0, 4.0], [1.0, 2.0, 3.0, 4.0])
    expect("identity map returns its input", identity.apply(3.0) == 3.0)

    shifted = QuantileMap.fit([1.0, 2.0, 3.0], [11.0, 12.0, 13.0])
    expect("a map carries rank across, not value", shifted.apply(1.0) == 11.0)
    expect("the top of the source reaches the top of the target", shifted.apply(9.9) == 13.0)
    expect("a map is monotonic", shifted.apply(1.0) <= shifted.apply(2.0) <= shifted.apply(3.0))

    # The property the whole method rests on: the tail keeps its size.
    source = [float(v) for v in range(100)]
    target = [float(v) * 2 for v in range(100)]
    mapped = QuantileMap.fit(source, target)
    tail = sum(1 for v in source if mapped.apply(v) >= 180.0)
    expect("mapping preserves how many samples clear a high threshold", tail == 10)

    expect("a bearing difference wraps past north", bearing_difference(1.0, 359.0) == 2.0)
    expect("and wraps the other way", bearing_difference(359.0, 1.0) == -2.0)
    expect("an offset wraps past north", BearingOffset(5.0).apply(358.0) == 3.0)

    scores = agreement([1.0, 5.0, 9.0], [1.0, 9.0, 9.0], threshold=8.0)
    expect("agreement counts a missed crossing", scores.recall == 0.5)
    expect("agreement counts a clean hit", scores.precision == 1.0)
    expect("agreement reports both tallies", (scores.predicted, scores.actual) == (1, 2))

    within = bearing_agreement([10.0, 200.0], [355.0, 200.0], within=15.0)
    expect("bearings close across north count as close", within == 1.0)

    for failure in failures:
        print(f"FAIL: {failure}")
    print(f"{'FAILED' if failures else 'ok'}: {len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    if "--check" in sys.argv:
        raise SystemExit(_check())
    print(__doc__)
    raise SystemExit(0)

"""What the candidate wave models actually offer, before #8 differences them.

ADR 0003 makes Model Spread the system's uncertainty estimate: several independent wave
models are asked about the same date and their disagreement is the doubt. `analysis/
forecast_models/` established which models return usable swell at Praia do Norte. This
establishes the three things #8 has to design around, none of which that investigation
could see from a single sampled hour.

**Run age cannot be read from the provider.** Open-Meteo exposes no model run timestamp on
the marine endpoint, so "how stale is this member" is not answerable from a response. See
`report_run_metadata`.

**The ensemble shrinks with Lead Time.** Members do not share a forecast horizon, so the
spread at eight days is computed from a different set of models than the spread at two —
and a member dropping out moves the spread on its own. See `coverage`.

**Members are not independent providers.** Five model identifiers are three organisations.
See `PROVIDERS`.

Run:
    .venv/Scripts/python.exe analysis/model_spread/probe.py
    .venv/Scripts/python.exe analysis/model_spread/probe.py --check
"""

from __future__ import annotations

import csv
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUTPUT = HERE / "output"

MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"

# The Proxy Target's position, matching what the Pipeline Run reads (ADR 0002).
LATITUDE = 39.56
LONGITUDE = -9.21

TIMEZONE = "Europe/Lisbon"
FORECAST_DAYS = 7

PROVIDERS = {
    "meteofrance_wave": "MeteoFrance",
    "dwd_ewam": "DWD",
    "dwd_gwam": "DWD",
    "ncep_gfswave025": "NCEP",
    "ncep_gfswave016": "NCEP",
}
"""The candidate roster, mapped to the organisation that runs each model.

ADR 0003 names "several independent wave models" and lists four, of which ECMWF WAM does
not carry a swell partition here at all (`analysis/forecast_models/`). What is left is five
identifiers and **three** organisations: EWAM and GWAM are both DWD, and the two GFS Wave
resolutions are both NCEP.

That distinction is the whole point of the word *independent*. Two resolutions of one
centre's model share its physics, its assimilation and its bugs; counting them as two
opinions makes the ensemble look twice as corroborated as it is, and Model Spread is
supposed to be the number that stops the system sounding more certain than it is.
"""

# The variables the Heuristic Baseline actually decides on. Spread in anything else would
# be measuring doubt the Decision Model never consults.
VARIABLES = ("swell_wave_height", "swell_wave_period", "swell_wave_direction")


@dataclass(frozen=True)
class Coverage:
    """How much of the forecast range one model answered for."""

    model: str
    provider: str
    first: str | None
    last: str | None
    hours: int
    nulls: int
    interior_nulls: int

    @property
    def horizon_days(self) -> float:
        return (self.hours - self.nulls) / 24.0


def fetch(client: httpx.Client, models: list[str], variables: tuple[str, ...]) -> dict:
    """Every model in one request.

    Open-Meteo accepts a comma-separated `models` list and answers with one series per
    model per variable, suffixed with the model name. That matters for more than the
    request budget: every member is then read from a single response at a single instant,
    so none of the disagreement measured here is our own sampling drifting between calls.

    It does **not** solve the alignment problem `analysis/forecast_models/` raised. That is
    about the members' own publication cadences — six-hourly for NCEP against twelve for
    the others — so one member's run can be six hours older than another's inside the very
    same response. One request removes our contribution to the problem and leaves theirs.
    """
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "hourly": ",".join(variables),
        "models": ",".join(models),
        "forecast_days": FORECAST_DAYS,
        "timezone": TIMEZONE,
        "length_unit": "metric",
    }
    response = client.get(MARINE_URL, params=params, timeout=30)
    response.raise_for_status()
    body = response.json()
    if body.get("timezone") != TIMEZONE:
        raise ValueError(
            f"Open-Meteo returned timestamps on {body.get('timezone')!r}, not {TIMEZONE!r}; "
            "every Lead Time below would be measured against the wrong day boundary"
        )
    return body


def coverage(hourly: dict, models: list[str], variable: str) -> list[Coverage]:
    """Where each model's series starts, stops, and whether it has holes in the middle.

    The distinction between a **horizon** and a **hole** is the reason this reports both.
    A model that stops early is answering a shorter question than the others and can be
    described as such. A model with gaps scattered through its range is unreliable in a way
    that no amount of describing fixes, and #8 would have to drop it rather than plan
    around it.
    """
    times = hourly["time"]
    rows = []
    for model in models:
        series = hourly[f"{variable}_{model}"]
        present = [i for i, value in enumerate(series) if value is not None]
        nulls = [i for i, value in enumerate(series) if value is None]
        interior = [i for i in nulls if min(present) < i < max(present)] if present else []
        rows.append(
            Coverage(
                model=model,
                provider=PROVIDERS[model],
                first=times[min(present)] if present else None,
                last=times[max(present)] if present else None,
                hours=len(times),
                nulls=len(nulls),
                interior_nulls=len(interior),
            )
        )
    return rows


def spread(values: list[float]) -> float:
    """Disagreement as the full range, not the standard deviation.

    With three independent opinions a standard deviation is a statistic computed on too
    few points to mean what its name implies, and it shrinks when one member is missing
    even if the survivors disagree exactly as much. The range says the plain thing: the
    most and least these forecasters think, and the gap between.
    """
    if len(values) < 2:
        raise ValueError("spread needs at least two opinions; one model is not an ensemble")
    return max(values) - min(values)


def by_provider(readings: dict[str, float]) -> dict[str, float]:
    """Collapse each organisation's models to one opinion before differencing.

    Without this, DWD votes twice and NCEP votes twice while MeteoFrance votes once, so the
    range is dominated by whichever centre happens to run two resolutions. The median of a
    provider's models is its opinion; the spread across providers is the ensemble's doubt.

    This is the concrete form of ADR 0003's word "independent", and it is what makes the
    number survive `dwd_ewam` dropping out at its horizon: DWD still has GWAM, so the
    provider count does not change and the spread stays comparable across Lead Times.
    """
    grouped: dict[str, list[float]] = {}
    for model, value in readings.items():
        grouped.setdefault(PROVIDERS[model], []).append(value)
    return {provider: statistics.median(values) for provider, values in grouped.items()}


def report_run_metadata(client: httpx.Client) -> list[tuple[str, str, str]]:
    """Whether the provider will tell us, or let us choose, which model run we are reading.

    Recorded as a table of negative results because the negatives are what #8 has to design
    around, and because each was worth checking: three of the four look plausible enough
    that an implementation might assume one works.

    `model_run` and `init` are the dangerous pair. Both return **200 with the parameter
    silently ignored**, so code that sent one and trusted the status would believe it had
    pinned a run while reading whatever the latest happened to be — this project's
    characteristic failure, a response that looks like agreement and is not.
    """
    probes = [
        ("model_run=latest", {"model_run": "latest"}),
        ("init=latest", {"init": "latest"}),
        ("run=latest", {"run": "latest"}),
    ]
    results = []
    base = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "hourly": "swell_wave_height",
        "models": "meteofrance_wave",
        "forecast_days": 1,
    }
    for label, extra in probes:
        response = client.get(MARINE_URL, params=base | extra, timeout=30)
        verdict = (
            "accepted and ignored — no run field in the response"
            if response.status_code == 200
            else f"rejected: HTTP {response.status_code}"
        )
        results.append((label, str(response.status_code), verdict))

    # The previous-run variable suffix, which does exist on the forecast endpoint.
    response = client.get(
        MARINE_URL,
        params=base | {"hourly": "swell_wave_height_previous_run1"},
        timeout=30,
    )
    results.append(
        (
            "hourly=swell_wave_height_previous_run1",
            str(response.status_code),
            "rejected — the marine endpoint has no previous-run variables"
            if response.status_code >= 400
            else "accepted",
        )
    )
    return results


def write_coverage_csv(rows: list[Coverage]) -> Path:
    path = OUTPUT / "coverage.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "model",
                "provider",
                "first_hour",
                "last_hour",
                "hours_requested",
                "null_hours",
                "interior_null_hours",
                "horizon_days",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.model,
                    row.provider,
                    row.first,
                    row.last,
                    row.hours,
                    row.nulls,
                    row.interior_nulls,
                    f"{row.horizon_days:.1f}",
                ]
            )
    return path


def write_spread_csv(hourly: dict, models: list[str]) -> Path:
    """Spread per hour per variable, with the members that contributed to it.

    The member count travels in the same row as the number, because a spread computed from
    two providers and one computed from three are not comparable and nothing else in the
    row would say which happened.
    """
    path = OUTPUT / "spread_by_hour.csv"
    times = hourly["time"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "hour",
                "lead_time_hours",
                "variable",
                "models_reporting",
                "providers_reporting",
                "model_spread",
                "provider_spread",
            ]
        )
        for index, moment in enumerate(times):
            for variable in VARIABLES:
                readings = {
                    model: hourly[f"{variable}_{model}"][index]
                    for model in models
                    if hourly[f"{variable}_{model}"][index] is not None
                }
                if len(readings) < 2:
                    continue
                opinions = by_provider(readings)
                writer.writerow(
                    [
                        moment,
                        index,
                        variable,
                        len(readings),
                        len(opinions),
                        f"{spread(list(readings.values())):.2f}",
                        f"{spread(list(opinions.values())):.2f}" if len(opinions) >= 2 else "",
                    ]
                )
    return path


def check() -> int:
    """Self-test the arithmetic offline, per the root README's convention.

    What is worth checking is the two functions that turn readings into a number a tier
    will eventually be driven by, because both are easy to write plausibly and wrong.
    """
    failures: list[str] = []

    def expect(label: str, got: object, want: object) -> None:
        if got != want:
            failures.append(f"{label}: expected {want!r}, got {got!r}")

    def expect_close(label: str, got: float, want: float) -> None:
        """Float comparison with a tolerance, because these are medians of decimals.

        The median of 1.2 and 1.4 is 1.2999999999999998, and an exact comparison here
        failed on arithmetic rather than on anything about the ensemble. A tolerance far
        tighter than the provider's own resolution — it reports to 2 decimal places — still
        catches every way these functions could actually be wrong.
        """
        if abs(got - want) > 1e-9:
            failures.append(f"{label}: expected {want!r}, got {got!r}")

    expect("spread is the full range", spread([1.0, 4.0, 2.0]), 3.0)
    expect("spread of agreeing models is zero", spread([2.5, 2.5]), 0.0)

    try:
        spread([1.0])
    except ValueError:
        pass
    else:
        failures.append("spread: expected a ValueError for a single opinion")

    # Each provider votes once. Written without the grouping, DWD's two models would carry
    # twice MeteoFrance's weight and the range below would be 0.4 rather than 0.2.
    readings = {
        "meteofrance_wave": 1.0,
        "dwd_ewam": 1.2,
        "dwd_gwam": 1.4,
        "ncep_gfswave025": 0.8,
        "ncep_gfswave016": 0.8,
    }
    expect(
        "each provider votes exactly once",
        sorted(by_provider(readings)),
        ["DWD", "MeteoFrance", "NCEP"],
    )
    opinions = by_provider(readings)
    expect_close("DWD's vote is the median of its two models", opinions["DWD"], 1.3)
    expect_close("MeteoFrance's single model is its vote", opinions["MeteoFrance"], 1.0)
    expect_close("NCEP's agreeing models give one vote", opinions["NCEP"], 0.8)
    # 0.5 across providers against 0.6 across models: the difference is DWD and NCEP each
    # being allowed two votes, which is the whole reason `by_provider` exists.
    expect_close("provider spread ignores duplicate members", spread(list(opinions.values())), 0.5)
    expect_close("model spread double-counts them", spread(list(readings.values())), 0.6)

    # EWAM dropping out at its horizon must not change DWD's presence in the ensemble —
    # that is the property that makes spread comparable across Lead Times.
    without_ewam = {k: v for k, v in readings.items() if k != "dwd_ewam"}
    expect(
        "a member dropping out leaves its provider represented",
        sorted(by_provider(without_ewam)),
        ["DWD", "MeteoFrance", "NCEP"],
    )

    for failure in failures:
        print(f"FAIL {failure}")
    print("probe.py --check: " + ("FAILED" if failures else "all checks passed"))
    return 1 if failures else 0


def main() -> int:
    if "--check" in sys.argv:
        return check()

    OUTPUT.mkdir(parents=True, exist_ok=True)
    models = list(PROVIDERS)

    with httpx.Client() as client:
        print("Can a model run be identified or chosen?\n")
        print(f"  {'probe':42s} {'status':8s} verdict")
        for label, status, verdict in report_run_metadata(client):
            print(f"  {label:42s} {status:8s} {verdict}")

        body = fetch(client, models, VARIABLES)

    hourly = body["hourly"]
    rows = coverage(hourly, models, "swell_wave_height")

    print(f"\nCoverage over {FORECAST_DAYS} forecast days, on swell height:\n")
    print(f"  {'model':22s} {'provider':13s} {'last hour':17s} {'horizon':>8s} {'holes':>6s}")
    for row in rows:
        print(
            f"  {row.model:22s} {row.provider:13s} {str(row.last):17s} "
            f"{row.horizon_days:7.1f}d {row.interior_nulls:6d}"
        )

    short = [row for row in rows if row.horizon_days < FORECAST_DAYS - 0.5]
    if short:
        names = ", ".join(row.model for row in short)
        verb = "stops" if len(short) == 1 else "stop"
        organisations = len({row.provider for row in rows})
        print(
            f"\n  The ensemble shrinks with Lead Time: {names} {verb} before the others, so "
            "spread at long range is computed from a different set of models than at short "
            "range. Grouping by provider is what keeps the number comparable — every provider "
            f"that drops a model here still has another, so {organisations} organisations "
            "vote at every Lead Time."
        )

    print("\nSpread by Lead Time, one row per day, with the members behind it:\n")
    times = hourly["time"]
    print(
        f"  {'hour':17s} {'models':>7s} {'providers':>10s} "
        f"{'height range':>13s} {'period range':>13s}"
    )
    for index in range(0, len(times), 24):
        reported = {
            model: hourly[f"swell_wave_height_{model}"][index]
            for model in models
            if hourly[f"swell_wave_height_{model}"][index] is not None
        }
        periods = {
            model: hourly[f"swell_wave_period_{model}"][index]
            for model in models
            if hourly[f"swell_wave_period_{model}"][index] is not None
        }
        if len(reported) < 2 or len(periods) < 2:
            print(f"  {times[index]:17s} {'too few members to difference':>40s}")
            continue
        print(
            f"  {times[index]:17s} {len(reported):7d} {len(by_provider(reported)):10d} "
            f"{spread(list(by_provider(reported).values())):11.2f} m "
            f"{spread(list(by_provider(periods).values())):11.2f} s"
        )

    coverage_path = write_coverage_csv(rows)
    spread_path = write_spread_csv(hourly, models)
    print(f"\nWrote {coverage_path.relative_to(ROOT)}")
    print(f"Wrote {spread_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

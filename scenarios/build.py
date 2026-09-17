"""Build a store showing the system in a state worth looking at.

Most days at Praia do Norte are flat, so the running site almost always shows the same
screen: nine cards reading "No call" and a headline saying nothing is worth booking. That is
the correct answer and a useless thing to design against, or to learn from. The interesting
screens — a Go Call on a day the ocean genuinely delivered, a Watch that faded, a verdict
firming as the date approaches — happen a handful of times a year.

This builds those screens from days that actually happened.

**It runs the real pipeline.** Historical provider payloads are reshaped into the form the
live endpoints return and served to `run_pipeline` through a mock transport, so the
validation, the Amplification Model, the Predictive Distribution, the Decision Model and
every store write are the shipped code taking a real decision. Nothing here reimplements a
verdict, and nothing fabricates one. If the system would not have called Go on a day, this
does not produce a Go, and that is the point — a demo that could only ever show success
would teach the wrong thing and be worth nothing to explain to anybody.

**The one fidelity caveat, stated here rather than discovered later.** Open-Meteo's archive
returns what the sea *did*, not the forecast as it was issued at the time. So these scenarios
carry Hindcast conditions presented through the live interface — exactly the distinction the
track record already makes at length, for the same reason. A real forecast is less certain
than this, so treat a scenario as the system at its best rather than as what it will do next
winter. Open-Meteo's historical-forecast API would remove the caveat and is the obvious
upgrade if these ever need to be more than a teaching and design tool.

Usage:

    python scenarios/build.py --list
    python scenarios/build.py gold-day
    python scenarios/build.py gold-day --real-dates

Then point the API at what it wrote:

    NAZARENOW_DB=scenarios/stores/gold-day.db \\
      python -m uvicorn nazarenow.api:app --port 8000

By default the time axis is shifted so the scenario's issue date becomes today, which is
what makes the page render in its live state rather than behind a staleness banner. The
shift is reported on every build, and `--real-dates` turns it off.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "backend" / "src"))

from nazarenow.pipeline import run_pipeline  # noqa: E402
from nazarenow.sources.open_meteo import (  # noqa: E402
    LATITUDE,
    LONGITUDE,
    MARINE_VARIABLES,
    SPREAD_VARIABLES,
    TIMEZONE,
    WEATHER_VARIABLES,
)
from nazarenow.spread import PROVIDERS  # noqa: E402
from nazarenow.store import Store  # noqa: E402

MARINE_ARCHIVE = "https://marine-api.open-meteo.com/v1/marine"
WEATHER_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"

# How far past the issue date to fetch. The provider stops modelling swell around nine days
# out, and the live pipeline asks for sixteen; ten is enough to fill the range the page
# shows without asking the archive for water nobody will look at.
WINDOW_DAYS = 10

# The hour of the issue date that stands in for "now" in the current-conditions block.
# Midday rather than midnight: a reading taken at 00:00 reads as the previous evening to
# anyone glancing at it, and the Pipeline Run it stands in for could have happened at any
# hour anyway.
ISSUE_HOUR = 12


@dataclass(frozen=True)
class Scenario:
    """One day worth looking at, and why it is worth looking at."""

    issue: date
    """The date the imaginary Pipeline Run happens on. Everything is relative to this."""

    target: date
    """The day the scenario is about. Its Lead Time is what decides the tier."""

    headline: str
    teaches: str


# Every scenario here is checked against analysis/backtest/output/daily_calls.csv, so the
# verdict each one should produce is known before it is built and a surprise is a finding
# rather than a mystery. All fall inside Open-Meteo's marine archive, which at this location
# begins in 2022 — earlier giant days, including 18 January 2018, cannot be built at all.
SCENARIOS = {
    "gold-day": Scenario(
        issue=date(2025, 12, 9),
        target=date(2025, 12, 13),
        headline="A Go Call four days out, on a day Nazaré genuinely went giant",
        teaches=(
            "The system at its best, and the screen that has to be worth being proud of. "
            "13 December 2025 peaked at 5.30m and is a ratified Gold Day — independently "
            "confirmed giant, not merely large in the model. The call is issued at Lead "
            "Time 4, inside the 2-to-7-day window a Go Call lives in, so this is the "
            "screen a Traveller would have booked a flight from."
        ),
    ),
    "confirmed": Scenario(
        issue=date(2025, 12, 12),
        target=date(2025, 12, 13),
        headline="The same swell, one day out: Confirmed rather than Go",
        teaches=(
            "The same ocean, a different tier, because tiers are about what you should do "
            "and not about how big the waves are. At Lead Time 1 there is nothing left to "
            "book, so the system stops recommending and starts reporting. Worth seeing "
            "beside 'gold-day': the sea is identical and the advice is not."
        ),
    ),
    "flagged-not-gold": Scenario(
        issue=date(2022, 1, 3),
        target=date(2022, 1, 7),
        headline="A Go Call on a 5.17m day that nobody wrote down",
        teaches=(
            "Why the published precision figure can only ever be an upper bound. The "
            "system called this day, the sea delivered 5.17m, and it appears in no Gold "
            "Day record — because the record is assembled from contests and reports rather "
            "than from a census. Counted as a wasted trip in the track record, and it may "
            "not have been one. This is the single best thing to be able to explain."
        ),
    ),
    "missed-gold-day": Scenario(
        issue=date(2022, 2, 22),
        target=date(2022, 2, 26),
        headline="A ratified Gold Day the system only raised a Watch for",
        teaches=(
            "The failure that matters, shown rather than described. 26 February 2022 was "
            "independently confirmed giant and the system never got past a Watch, so a "
            "Traveller relying on Go Calls alone would have missed it. Recall is what the "
            "Watch tier exists to protect, and this is the day that argues for it."
        ),
    ),
    "quiet": Scenario(
        issue=date(2025, 9, 15),
        target=date(2025, 9, 18),
        headline="An ordinary September: nothing to book",
        teaches=(
            "The baseline, and what the site shows most weeks of the year. Worth building "
            "so the quiet screen can be judged as a designed state rather than treated as "
            "the absence of one — it is what a returning visitor sees almost every time."
        ),
    ),
}


def window(scenario: Scenario) -> tuple[date, date]:
    return scenario.issue, scenario.issue + timedelta(days=WINDOW_DAYS)


def fetch_archive(
    client: httpx.Client, url: str, variables: list[str], start: date, end: date, **extra: Any
) -> dict[str, Any]:
    """One archive request, with the unit parameters the live pipeline sends.

    The units are not merely requested, they are checked downstream: `validate_units` fails
    the run on anything unexpected. Sending the same parameters the live source sends is
    what keeps a scenario honest about that.
    """
    response = client.get(
        url,
        params={
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
            "hourly": ",".join(variables),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "timezone": TIMEZONE,
            "temperature_unit": "celsius",
            "wind_speed_unit": "kmh",
            "length_unit": "metric",
            **extra,
        },
        timeout=120,
    )
    response.raise_for_status()
    return response.json()


def shift(stamp: str, days: int) -> str:
    """Move one timestamp by whole days, keeping the provider's format exactly."""
    moment = datetime.strptime(stamp, "%Y-%m-%dT%H:%M")
    return (moment + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M")


def to_live_shape(
    body: dict[str, Any], variables: list[str], issue: date, offset: int
) -> dict[str, Any]:
    """Reshape an archive response into what the live endpoint returns.

    The archive has no `current` block, because nothing is current about a week in 2022.
    The live pipeline requires one and refuses a null reading in it, so one is assembled
    from the hourly row at the issue date's midday — a real measurement from the window,
    not an invention.
    """
    hourly = dict(body["hourly"])
    times: list[str] = hourly["time"]

    wanted = f"{issue.isoformat()}T{ISSUE_HOUR:02d}:00"
    if wanted not in times:
        raise SystemExit(f"the archive window has no hour at {wanted}")
    index = times.index(wanted)

    current: dict[str, Any] = {"time": shift(times[index], offset)}
    for name in variables:
        value = hourly[name][index]
        if value is None:
            raise SystemExit(
                f"the archive has no {name} at {wanted}. "
                f"Open-Meteo's marine archive begins in 2022 at this location."
            )
        current[name] = value

    hourly["time"] = [shift(stamp, offset) for stamp in times]

    return {
        "latitude": body["latitude"],
        "longitude": body["longitude"],
        "timezone": body["timezone"],
        "current_units": {"time": "iso8601", **{n: body["hourly_units"][n] for n in variables}},
        "current": current,
        "hourly_units": body["hourly_units"],
        "hourly": hourly,
    }


def to_ensemble_shape(body: dict[str, Any], offset: int) -> dict[str, Any]:
    """The ensemble needs no `current` block, so only its time axis moves.

    `fetch_ensemble` deliberately skips `validate`, because ADR 0003 says a provider being
    unavailable must degrade the uncertainty estimate rather than fail the run. Nothing here
    needs to make up for that.
    """
    hourly = dict(body["hourly"])
    hourly["time"] = [shift(stamp, offset) for stamp in hourly["time"]]
    return {**body, "hourly": hourly}


def replaying_client(marine: dict, weather: dict, ensemble: dict) -> httpx.Client:
    """An httpx client that answers the pipeline's three requests from these bodies.

    Routed on the request rather than by patching the source module, so `open_meteo` runs
    exactly as it does in production — same URLs, same params, same retry logic, same
    validation. A scenario that only passed because the validator was bypassed would be
    worth nothing.
    """

    def handle(request: httpx.Request) -> httpx.Response:
        host = urlparse(str(request.url)).netloc
        query = parse_qs(request.url.query.decode())
        if "models" in query:
            return httpx.Response(200, json=ensemble)
        if "marine" in host:
            return httpx.Response(200, json=marine)
        return httpx.Response(200, json=weather)

    return httpx.Client(transport=httpx.MockTransport(handle))


def report(store: Store, scenario: Scenario, offset: int) -> None:
    """Print what the real Decision Model actually decided, per day."""
    # Keyed by date: the most recent call made about each day, which is what the page shows.
    calls = store.calls()
    print()
    print(f"  {'DATE':<12} {'LEAD':>4}  {'VERDICT':<10} {'HEIGHT':>7}  AGREEMENT")
    for shown, call in sorted(calls.items()):
        real = (date.fromisoformat(shown) - timedelta(days=offset)).isoformat()
        is_target = real == scenario.target.isoformat()
        marker = f"  <-- {real}, the day this scenario is about" if is_target else ""
        height = call.get("predicted_significant_wave_height")
        height_text = f"{height:>6.2f}m" if isinstance(height, (int, float)) else f"{'-':>7}"
        print(
            f"  {shown:<12} {call['lead_time_days']:>4}  {call['status']:<10} "
            f"{height_text}  {call.get('model_agreement') or '-':<9}{marker}"
        )


def build(name: str, keep_real_dates: bool) -> None:
    scenario = SCENARIOS[name]
    start, end = window(scenario)
    offset = 0 if keep_real_dates else (date.today() - scenario.issue).days

    print(f"{name}: {scenario.headline}")
    print(
        f"  issued {scenario.issue}, about {scenario.target} "
        f"(Lead Time {(scenario.target - scenario.issue).days})"
    )
    if offset:
        print(f"  shifting the time axis forward {offset} days, so the issue date reads as today")
    else:
        print("  keeping the real dates, so the page will show a staleness banner")

    with httpx.Client() as client:
        print("  fetching the marine archive")
        marine = fetch_archive(client, MARINE_ARCHIVE, MARINE_VARIABLES, start, end)
        print("  fetching the weather archive")
        weather = fetch_archive(client, WEATHER_ARCHIVE, WEATHER_VARIABLES, start, end)
        print("  fetching every wave model, for Model Spread")
        ensemble = fetch_archive(
            client,
            MARINE_ARCHIVE,
            SPREAD_VARIABLES,
            start,
            end,
            models=",".join(PROVIDERS),
        )

    bodies = (
        to_live_shape(marine, MARINE_VARIABLES, scenario.issue, offset),
        to_live_shape(weather, WEATHER_VARIABLES, scenario.issue, offset),
        to_ensemble_shape(ensemble, offset),
    )

    stores = HERE / "stores"
    stores.mkdir(exist_ok=True)
    path = stores / f"{name}.db"
    path.unlink(missing_ok=True)

    print("  running the real pipeline against it")
    store = Store(path)
    with replaying_client(*bodies) as client:
        run_pipeline(store, client)

    report(store, scenario, offset)
    (stores / f"{name}.json").write_text(
        json.dumps(
            {
                "scenario": name,
                "headline": scenario.headline,
                "teaches": scenario.teaches,
                "issued": scenario.issue.isoformat(),
                "target": scenario.target.isoformat(),
                "day_offset_applied": offset,
                "conditions": "Open-Meteo archive (what the sea did), not the forecast as issued",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print()
    print(f"  wrote {path}")
    print(f"  NAZARENOW_DB={path} python -m uvicorn nazarenow.api:app --port 8000")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", nargs="?", help="which scenario to build")
    parser.add_argument("--list", action="store_true", help="show every scenario and exit")
    parser.add_argument(
        "--real-dates",
        action="store_true",
        help="keep the historical dates instead of shifting them to today",
    )
    parser.add_argument("--all", action="store_true", help="build every scenario")
    args = parser.parse_args()

    if args.list or not (args.scenario or args.all):
        for name, scenario in SCENARIOS.items():
            print(f"{name}")
            print(f"  {scenario.headline}")
            print(f"  issued {scenario.issue}, about {scenario.target}")
            print(f"  {scenario.teaches}")
            print()
        return 0

    names = list(SCENARIOS) if args.all else [args.scenario]
    for name in names:
        if name not in SCENARIOS:
            print(f"no scenario called {name!r}. --list shows them all.", file=sys.stderr)
            return 2
        build(name, args.real_dates)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""The scheduler, driven through the store it fills and the provider it calls.

Nothing here mocks a Pipeline Run. The scheduler's whole job is to keep running real
Pipeline Runs unattended, so a test that substituted a fake one would assert the schedule
called something, not that the system stayed current — and the interesting failures all
live in what happens when a real run goes wrong.

The interval and the waiting are injected, so the suite exercises the cadence without
sleeping through it.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import httpx
import pytest

from helpers import GIANT, forecast_provider, ingest
from nazarenow.schedule import INTERVAL_SECONDS, STALE_AFTER_SECONDS, run_scheduled

TODAY = "2026-02-09"


def flaky_provider(fail_first: int) -> tuple[httpx.MockTransport, list[float]]:
    """A provider that refuses the first `fail_first` requests, then behaves.

    Connection errors rather than error statuses: a provider being unreachable is the
    failure a scheduler most needs to survive, and it is the one that bypasses every
    status-code path in the fetch logic.
    """
    good = forecast_provider({"2026-02-13": GIANT}, today=TODAY)
    seen: list[float] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(len(seen))
        if len(seen) <= fail_first:
            raise httpx.ConnectError("provider unreachable")
        return good.handler(request)

    return httpx.MockTransport(handle), seen


def test_a_failed_run_does_not_stop_the_schedule(store) -> None:
    """An unattended system that dies on one bad fetch is worse than no schedule at all.

    Open-Meteo will be briefly unreachable sooner or later. The run that meets it must be
    lost, not the schedule.
    """
    # Enough failures to exhaust every retry of the first run, then a clean provider.
    transport, _ = flaky_provider(fail_first=3)
    slept: list[float] = []

    with httpx.Client(transport=transport) as client:
        completed = run_scheduled(store, client, runs=2, sleep=slept.append)

    assert completed == [False, True], "the first run should fail and the second succeed"
    assert store.latest_conditions() is not None, "the schedule stopped at the failed run"


def test_the_schedule_waits_the_forecast_cycle_between_runs(store) -> None:
    """Three-hourly, because best_match at Nazaré resolves to MeteoFrance's wave model,
    which publishes twice a day — so this keeps the site within three hours of a published
    run rather than up to half an update behind. See analysis/forecast_models/."""
    slept: list[float] = []

    with httpx.Client(transport=forecast_provider({}, today=TODAY)) as client:
        run_scheduled(store, client, runs=3, sleep=slept.append)

    # Two waits for three runs: the first run happens immediately, so a scheduler that
    # slept before the first would leave the site stale for three hours after every start.
    assert slept == [INTERVAL_SECONDS, INTERVAL_SECONDS]
    assert INTERVAL_SECONDS == 3 * 60 * 60


def test_a_run_that_raises_something_unexpected_is_survived_too(store) -> None:
    """Not only provider faults. A bug in our own parsing, a corrupted payload, a disk
    error — the schedule's contract is that the next cycle still happens."""
    calls: list[int] = []

    def exploding(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise ValueError("something nobody anticipated")

    with httpx.Client(transport=httpx.MockTransport(exploding)) as client:
        completed = run_scheduled(store, client, runs=2, sleep=lambda _: None)

    assert completed == [False, False]
    assert calls, "the scheduler never reached the provider"


def test_the_schedule_reports_what_happened_on_each_run(store, capsys) -> None:
    """A scheduler nobody can see is a scheduler nobody trusts. Each run says whether it
    succeeded, so an operator reading logs can tell a quiet system from a stuck one."""
    transport, _ = flaky_provider(fail_first=3)

    with httpx.Client(transport=transport) as client:
        run_scheduled(store, client, runs=2, sleep=lambda _: None)

    output = capsys.readouterr().out
    assert "failed" in output.lower()
    assert "provider unreachable" in output, "the reason a run failed must reach the log"


class TestStaleness:
    """ADR 0005: the site "stays up and honest — showing stale results with a timestamp"
    when the provider is unreachable.

    A timestamp alone is not honest enough. "Fetched 09:04" reads as current to anyone not
    doing subtraction in their head, and the whole point of the tier system is that a user
    acts on what they see. So the backend decides what counts as old and says so outright.

    The threshold lives here rather than in the interface because ADR 0005 makes the
    frontend strictly a reader, and "too old to trust" is domain knowledge. An earlier
    version of this codebase put the rule of thumb's thresholds in the presentation layer
    and got them wrong; this is the same mistake waiting to be repeated.
    """

    def freeze(self, monkeypatch, moment: str) -> None:
        monkeypatch.setattr("nazarenow.api.utc_now", lambda: datetime.fromisoformat(moment))

    def test_data_from_the_last_cycle_is_not_stale(self, store, client, monkeypatch) -> None:
        ingest(store, forecast_provider({"2026-02-13": GIANT}, today=TODAY))
        fetched = datetime.fromisoformat(store.latest_conditions()["fetched_at"])
        self.freeze(monkeypatch, (fetched + timedelta(seconds=INTERVAL_SECONDS)).isoformat())

        assert client.get("/api/conditions/current").json()["stale"] is False
        assert client.get("/api/conditions/forecast").json()["stale"] is False

    def test_data_older_than_two_missed_cycles_is_stale(self, store, client, monkeypatch) -> None:
        """One missed run is a blip; two means something is actually wrong."""
        ingest(store, forecast_provider({"2026-02-13": GIANT}, today=TODAY))
        fetched = datetime.fromisoformat(store.latest_conditions()["fetched_at"])
        self.freeze(monkeypatch, (fetched + timedelta(seconds=STALE_AFTER_SECONDS + 1)).isoformat())

        assert client.get("/api/conditions/current").json()["stale"] is True
        assert client.get("/api/conditions/forecast").json()["stale"] is True

    def test_the_boundary_is_two_whole_cycles(self, store, client, monkeypatch) -> None:
        """Pinned as a literal. Deriving the expected moment from the constant under test
        moves both sides of the assertion together and pins nothing."""
        assert STALE_AFTER_SECONDS == 6 * 60 * 60

        ingest(store, forecast_provider({"2026-02-13": GIANT}, today=TODAY))
        fetched = datetime.fromisoformat(store.latest_conditions()["fetched_at"])
        self.freeze(monkeypatch, (fetched + timedelta(hours=6)).isoformat())

        assert client.get("/api/conditions/current").json()["stale"] is False

    def test_a_timestamp_that_cannot_be_read_counts_as_stale(
        self, store, client, monkeypatch
    ) -> None:
        """The safe direction is the honest one.

        If the age of the data cannot be established, the two options are to report it as
        current or to report it as old. Reporting a run of unknown age as current is the
        project's characteristic failure — a plausible answer with nothing behind it — and
        it is the reading someone would act on.
        """
        monkeypatch.setattr("nazarenow.store.now", lambda: "not a timestamp")
        ingest(store, forecast_provider({"2026-02-13": GIANT}, today=TODAY))

        assert client.get("/api/conditions/current").json()["stale"] is True
        assert client.get("/api/conditions/forecast").json()["stale"] is True

    def test_a_failed_run_leaves_prior_results_readable_and_marked_stale(
        self, store, client, monkeypatch
    ) -> None:
        """The acceptance criterion of #7, end to end.

        A good run, then six hours of the provider being unreachable. What the user sees
        must still be the good run's data — not an error, not zeros — and it must say
        plainly that it is old.
        """
        ingest(store, forecast_provider({"2026-02-13": GIANT}, today=TODAY))
        good = client.get("/api/conditions/current").json()

        transport, _ = flaky_provider(fail_first=99)
        with httpx.Client(transport=transport) as failing:
            completed = run_scheduled(store, failing, runs=2, sleep=lambda _: None)

        assert completed == [False, False]

        fetched = datetime.fromisoformat(store.latest_conditions()["fetched_at"])
        self.freeze(monkeypatch, (fetched + timedelta(seconds=STALE_AFTER_SECONDS + 1)).isoformat())
        after = client.get("/api/conditions/current").json()

        assert after["swell_height"] == good["swell_height"], "the good run's data was lost"
        assert after["observed_at"] == good["observed_at"]
        assert after["stale"] is True
        assert client.get("/api/conditions/forecast").json()["days"], "the forecast was lost"


@pytest.mark.parametrize("command", ["ingest", "schedule"])
def test_both_commands_are_reachable_from_the_command_line(command) -> None:
    """The scheduler is only useful if something can start it. `main` returning 2 for a
    command the module documents is the whole feature failing at the last step."""
    from nazarenow.__main__ import COMMANDS, main

    assert command in COMMANDS
    assert main(["nazarenow", "nonsense"]) == 2


@pytest.mark.parametrize("runs", [0, 1])
def test_the_number_of_runs_is_honoured_exactly(store, runs) -> None:
    """Guards the loop's boundary: an off-by-one here means the production scheduler
    either never runs or runs twice per cycle, and neither is visible in a passing suite
    that only ever asks for two."""
    slept: list[float] = []

    with httpx.Client(transport=forecast_provider({}, today=TODAY)) as client:
        completed = run_scheduled(store, client, runs=runs, sleep=slept.append)

    assert len(completed) == runs
    assert len(slept) == max(runs - 1, 0)

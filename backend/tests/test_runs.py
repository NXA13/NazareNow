"""The record of what each Pipeline Run fetched, produced, and whether it survived.

Driven through `Store` directly and through a real Pipeline Run against a stubbed
provider. No HTTP surface exposes runs, so this is the same deliberate narrow exception
already earned by `raw_responses()` and `call_history()`: the behaviour is required by
ticket #30 and there is nothing else that can observe it. When run diagnostics get an
endpoint, these tests should move to it.

Why this is not logging hygiene. ADR 0005 retains every prediction "by construction"
because ticket #11 scores Go Call precision from that record after the fact. A prediction
whose inputs cannot be recovered is not evidence — and before this ticket, a raw response
and the calls derived from it were correlated only by a loose timestamp, so
reconstructing which fetch produced a given Go Call was inference rather than lookup.
"""

from __future__ import annotations

import sqlite3

import httpx
import pytest

from helpers import GIANT, forecast_provider, ingest, no_sleep, stub_hours
from nazarenow.pipeline import run_pipeline
from nazarenow.runs import FailureKind, RunOutcome
from nazarenow.schedule import run_scheduled
from nazarenow.store import Store, StoreUnavailable

TODAY = "2026-02-09"


def unreachable_provider() -> httpx.MockTransport:
    """A provider that cannot be reached at all — the failure a scheduler most needs to
    survive, and the one that bypasses every status-code path in the fetch logic."""

    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("provider unreachable")

    return httpx.MockTransport(handle)


def nonsense_provider() -> httpx.MockTransport:
    """A provider answering successfully with something this system does not understand.

    Not an outage: the request succeeded, and the payload is the problem. Distinguishing
    these two is an acceptance criterion of #30, and they are indistinguishable in a log
    line that says only "failed".
    """

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    return httpx.MockTransport(handle)


def test_a_successful_run_is_recorded_as_a_run_in_its_own_right(store) -> None:
    """The record #11 scores starts with knowing a run happened at all."""
    ingest(store, forecast_provider({"2026-02-13": GIANT}, today=TODAY))

    runs = store.runs()

    assert len(runs) == 1, "a Pipeline Run left no record of itself"
    assert runs[0]["id"] is not None, "a run with no identifier cannot be referenced"
    assert runs[0]["outcome"] == "succeeded"
    assert runs[0]["started_at"] and runs[0]["finished_at"]
    assert runs[0]["failure_kind"] is None


def test_a_failed_run_leaves_a_durable_queryable_record(store) -> None:
    """The criterion #7 left unmet. Before this, a failed run's only trace was a line on
    stdout and the interface going stale six hours later — so a gap in the record could
    not be told apart from a host nobody had switched on."""
    with httpx.Client(transport=unreachable_provider()) as client:
        completed = run_scheduled(store, client, runs=2, sleep=no_sleep)

    assert completed == [False, False], "the provider was supposed to be unreachable"

    failed = store.failed_runs()

    assert len(failed) == 2, "a failed run left no record of itself"
    assert all(run["outcome"] == RunOutcome.FAILED.value for run in failed)
    assert all(run["finished_at"] for run in failed), "a failed run never closed its record"
    assert "provider unreachable" in failed[0]["failure_detail"], (
        "the reason a run failed must survive in the record, not only in the log"
    )


def test_a_failed_run_stores_nothing_it_fetched(store) -> None:
    """The failure record is an addition to `schedule.py`'s guarantee, not a hole in it.

    A run that could not be trusted to produce conditions must not be trusted to produce
    half of them either — the run record is the one thing it writes.
    """
    ingest(store, forecast_provider({"2026-02-13": GIANT}, today=TODAY))
    good = store.latest_conditions()

    with httpx.Client(transport=nonsense_provider()) as client:
        run_scheduled(store, client, runs=1, sleep=no_sleep)

    assert store.latest_conditions() == good, "a failed run overwrote the last good one"
    assert len(store.runs()) == 2, "the failed attempt is missing from the record"
    assert store.failed_runs()[0]["id"] != store.runs()[0]["id"]


@pytest.mark.parametrize(
    ("transport", "expected"),
    [
        (unreachable_provider, FailureKind.PROVIDER_UNAVAILABLE),
        (nonsense_provider, FailureKind.PAYLOAD_UNRECOGNISED),
    ],
)
def test_the_record_tells_an_outage_apart_from_a_payload_we_no_longer_understand(
    store, transport, expected
) -> None:
    """These two failures call for opposite responses.

    A provider having a bad afternoon is waited out. A payload that no longer means what
    the parser thinks it means will fail identically on every run until someone changes
    the code — and a season of records marked only "failed" would need every detail string
    re-read by hand to notice which had happened.
    """
    with httpx.Client(transport=transport()) as client:
        run_scheduled(store, client, runs=1, sleep=no_sleep)

    assert store.failed_runs()[0]["failure_kind"] == expected.value


def test_a_run_whose_output_rolled_back_is_not_marked_succeeded(store) -> None:
    """The outcome and the output are one transaction, so they cannot disagree.

    Marking success after the write instead of inside it leaves a window where a run
    claims to have produced a forecast that was rolled back — a plausible false answer in
    the very record #11 uses to decide whether this system was right.
    """
    hour = stub_hours("2026-03-01")[0]["readings"]
    run_id = store.begin_run()

    with pytest.raises(sqlite3.IntegrityError):
        store.record_run(
            "2026-03-01T00:00",
            1.0,
            2.0,
            {},
            # Two readings for the same hour: `forecast_hour` is keyed on `valid_at`, so
            # the second insert fails and takes the whole transaction with it.
            [{"at": "2026-03-01T00:00", "readings": hour}] * 2,
            [],
            run_id=run_id,
        )

    assert store.runs()[0]["outcome"] != RunOutcome.SUCCEEDED.value
    assert store.forecast() == [], "the rolled-back forecast was stored anyway"


def test_a_run_that_never_finished_is_not_reported_as_succeeded(store) -> None:
    """A host that dies mid-run cannot write its own epitaph, so the record is opened
    before the work starts and left open until something closes it. `running` long after
    the fact is how that becomes visible rather than invisible."""
    run_id = store.begin_run()

    assert store.runs() == [
        {
            "id": run_id,
            "started_at": store.runs()[0]["started_at"],
            "finished_at": None,
            "outcome": RunOutcome.RUNNING.value,
            "failure_kind": None,
            "failure_detail": None,
        }
    ]
    assert store.failed_runs() == [], "an unfinished run is not a failed one"


class TestTracingAPredictionToItsInputs:
    """The point of the whole ticket. ADR 0005 keeps every prediction because #11 scores
    Go Call precision from them after the fact — and a prediction whose inputs cannot be
    recovered is not evidence."""

    def test_a_stored_call_names_the_run_that_produced_it(self, store) -> None:
        ingest(store, forecast_provider({"2026-02-13": GIANT}, today=TODAY))

        run = store.runs()[0]
        history = store.call_history()

        assert history, "the run stored no calls"
        assert all(call["run_id"] == run["id"] for call in history)

    def test_the_raw_responses_behind_a_call_are_found_by_lookup(self, store) -> None:
        """By identifier, not by looking for a `fetched_at` close enough to the call's
        `issued_at`. Timestamp inference is a guess that gets worse the more runs the
        store accumulates, and it is what this replaces."""
        ingest(store, forecast_provider({"2026-02-13": GIANT}, today=TODAY))
        call = store.call_history()[0]

        inputs = store.inputs_behind(call["run_id"])

        assert {response["source"] for response in inputs} == {
            "open-meteo-marine",
            "open-meteo-weather",
        }, "a call must lead back to every response it was derived from"

    def test_a_later_run_s_call_leads_to_that_run_s_inputs_and_not_an_earlier_one_s(
        self, store
    ) -> None:
        """The failure timestamp correlation actually produces. Two runs minutes apart
        both hold responses and calls; matching on time picks whichever is nearest, which
        is right until it quietly is not."""
        ingest(store, forecast_provider({"2026-02-13": GIANT}, today=TODAY))
        ingest(store, forecast_provider({"2026-02-13": GIANT}, today=TODAY))

        first, second = (run["id"] for run in store.runs())
        latest = [call for call in store.call_history() if call["run_id"] == second]

        assert latest, "the second run stored no calls of its own"
        assert {response["run_id"] for response in store.inputs_behind(second)} == {second}
        assert store.inputs_behind(first) != store.inputs_behind(second)

    def test_a_failed_run_s_record_is_not_mistaken_for_a_call_s_provenance(self, store) -> None:
        """A failed run holds no responses, so tracing to it must come back empty rather
        than falling through to whatever the previous run fetched."""
        with httpx.Client(transport=unreachable_provider()) as client:
            run_scheduled(store, client, runs=1, sleep=no_sleep)

        assert store.inputs_behind(store.failed_runs()[0]["id"]) == []


class TestAStoreWrittenBeforeThisTicket:
    """ADR 0005 makes the accumulated record the asset, so a schema change cannot be an
    instruction to delete it. `CREATE TABLE IF NOT EXISTS` leaves an existing table
    exactly as it found it, which means the tables needing a new column are precisely the
    ones that will not get one.
    """

    def old_database(self, tmp_path):
        """A store in the shape ticket #7 left it: no runs, and no run reference.

        Every table, not only the two that gain a column. A partial one passes for the
        wrong reason — it fails the schema probe on a missing table before ever reaching
        the migrated columns, which is not the thing under test.
        """
        path = tmp_path / "pre-30.db"
        connection = sqlite3.connect(path)
        connection.executescript("""
            CREATE TABLE offshore_conditions (
                id INTEGER PRIMARY KEY, observed_at TEXT NOT NULL, fetched_at TEXT NOT NULL,
                latitude REAL NOT NULL, longitude REAL NOT NULL, readings TEXT NOT NULL
            );
            CREATE TABLE forecast_hour (
                valid_at TEXT PRIMARY KEY, fetched_at TEXT NOT NULL, readings TEXT NOT NULL
            );
            CREATE TABLE raw_response (
                id INTEGER PRIMARY KEY, source TEXT NOT NULL, url TEXT NOT NULL,
                fetched_at TEXT NOT NULL, body TEXT NOT NULL
            );
            CREATE TABLE day_call (
                id INTEGER PRIMARY KEY, date TEXT NOT NULL, issued_at TEXT NOT NULL,
                issued_for_date TEXT NOT NULL, status TEXT NOT NULL,
                lead_time_days INTEGER NOT NULL, reasons TEXT NOT NULL,
                predicted_significant_wave_height REAL NOT NULL, unit TEXT NOT NULL,
                amplification_model TEXT NOT NULL, calibrated INTEGER NOT NULL
            );
            INSERT INTO offshore_conditions (observed_at, fetched_at, latitude, longitude, readings)
                VALUES ('2026-01-01T00:00', '2026-01-01T00:00', 39.56, -9.21, '{}');
            INSERT INTO raw_response (source, url, fetched_at, body)
                VALUES ('open-meteo-marine', 'https://example.test', '2026-01-01T00:00', '{}');
            INSERT INTO day_call VALUES
                (1, '2026-01-05', '2026-01-01T00:00', '2026-01-01', 'go', 4, '[]', 4.2, 'm',
                 'heuristic-baseline', 0);
        """)
        connection.commit()
        connection.close()
        return path

    def test_it_opens_rather_than_demanding_to_be_thrown_away(self, tmp_path) -> None:
        store = Store(self.old_database(tmp_path))
        try:
            assert len(store.call_history()) == 1, "the record this ticket protects was lost"
            assert len(list(store.raw_responses())) == 1
        finally:
            store.close()

    def test_rows_from_before_runs_were_tracked_admit_they_have_no_run(self, tmp_path) -> None:
        """Null rather than backfilled. Inventing a run for a row that predates run
        tracking would fabricate exactly the provenance this ticket exists to make
        trustworthy — a lookup that always answers is worth nothing if some answers are
        made up."""
        store = Store(self.old_database(tmp_path))
        try:
            assert store.call_history()[0]["run_id"] is None
            assert store.inputs_behind(1) == [], "a fabricated run id found inputs"
        finally:
            store.close()

    def test_a_migrated_store_records_new_runs_normally(self, tmp_path) -> None:
        """The migration has to leave a working store, not merely a readable one."""
        store = Store(self.old_database(tmp_path))
        try:
            ingest(store, forecast_provider({"2026-02-13": GIANT}, today=TODAY))

            assert [run["outcome"] for run in store.runs()] == [RunOutcome.SUCCEEDED.value]
            new = [call for call in store.call_history() if call["run_id"] is not None]
            assert new, "the migrated store recorded no provenance for its new calls"
            assert store.inputs_behind(new[0]["run_id"]), "tracing broke after migration"
        finally:
            store.close()

    def test_the_serving_store_refuses_one_nothing_has_migrated_yet(self, tmp_path) -> None:
        """ADR 0005 makes the API strictly a reader, so it cannot migrate anything — and
        an unmigrated store is one it cannot answer from honestly.

        This is an ordering constraint #28 has to respect when an API and a scheduler are
        started against the same file: until the scheduler has opened it once, the reader
        refuses. It refuses at construction, where `StoreUnavailable` is handled, rather
        than inside an endpoint — which is the bare-500-without-CORS outcome eager
        verification exists to prevent.
        """
        with pytest.raises(StoreUnavailable, match="run_id"):
            Store(self.old_database(tmp_path), create=False)

    def test_once_migrated_the_serving_store_reads_it(self, tmp_path) -> None:
        path = self.old_database(tmp_path)
        writer = Store(path)
        writer.close()

        reader = Store(path, create=False)
        try:
            assert len(reader.calls()) == 1, "the migrated record stopped being servable"
        finally:
            reader.close()

    def test_reopening_a_migrated_store_does_not_migrate_it_twice(self, tmp_path) -> None:
        """`ALTER TABLE ADD COLUMN` fails on a column that already exists, which would
        turn every restart after the first into a crash."""
        path = self.old_database(tmp_path)
        first = Store(path)
        first.close()
        second = Store(path)
        second.close()

        reader = Store(path, create=False)
        try:
            assert len(reader.call_history()) == 1
        finally:
            reader.close()


def test_the_one_off_ingest_command_is_recorded_like_any_other_run(store) -> None:
    """The run record belongs to the Pipeline Run, not to the scheduler. A store whose
    provenance depended on which command happened to write it would be provenance in name
    only — and #11 scores whatever is in there."""
    with httpx.Client(transport=forecast_provider({}, today=TODAY)) as client:
        run_pipeline(store, client, sleep=no_sleep)

    assert [run["outcome"] for run in store.runs()] == [RunOutcome.SUCCEEDED.value]

"""Persistence for Pipeline Run output.

SQLite: the whole dataset is small, single-writer, and read by one process. A server
database would add operational weight this project has no use for yet. Swapping it later
means changing this module and nothing else, which is the point of keeping the store
internal to the backend seam (ADR 0005).

Four things are stored for every run: the run itself, the provider's response as received,
the values parsed out of it, and the calls derived from those values. Retaining the raw
response means derived data can be rebuilt without refetching, and that a provider
changing shape can be diagnosed after the fact. Retaining the calls is ADR 0005's promise
that every prediction the system has made survives, which is what ticket #11 scores.

The run record is what joins the other three (ticket #30). Without it a raw response and
the calls derived from it were related only by having been written at about the same
moment, so recovering the inputs behind a given Go Call was inference from timestamps
rather than a lookup — and a prediction whose inputs cannot be recovered is not evidence.
A run that failed appears here too, carrying why, and any response it did manage to fetch
before it failed.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import urllib.parse
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nazarenow.runs import FailureKind, RunOutcome

# Anchored to this file, not the working directory. A relative default meant the store
# you got depended on where you happened to be standing: ingesting from one directory and
# serving from another silently used two different databases, and the API answered "no
# conditions have been ingested yet" while a perfectly good row sat in the other file.
#
# This assumes a source checkout, which is how the project is run and how CI runs it.
# Installed non-editable into site-packages the anchor would land beside the virtualenv,
# so a packaged deployment must set NAZARENOW_DB.
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATABASE = REPO_ROOT / "data" / "nazarenow.db"

SCHEMA = """
-- The run itself, as a record rather than as a timestamp shared by whatever it wrote.
-- Before this table a raw response and the calls derived from it were correlated only by
-- being written at about the same moment, so "which fetch produced this Go Call" was
-- inference. It is now a lookup, which is what ticket #11 needs to score a prediction
-- against what it was actually made from.
--
-- A failed run writes no conditions, forecast or calls -- `record_run` is one transaction
-- and it never reached it -- but the attempt is still part of the record. A gap in the
-- calls with no explanation beside it is indistinguishable from a host nobody had
-- switched on.
--
-- It may still hold raw responses. A run that fetched marine successfully and then lost
-- the weather endpoint keeps what it got, tagged to the run that failed. That is
-- deliberate: the payload is the evidence for `payload_unrecognised`, and discarding it
-- would throw away the one thing needed to work out what the provider had changed.
CREATE TABLE IF NOT EXISTS pipeline_run (
    id             INTEGER PRIMARY KEY,
    started_at     TEXT NOT NULL,
    finished_at    TEXT,
    outcome        TEXT NOT NULL,
    failure_kind   TEXT,
    failure_detail TEXT
);

CREATE TABLE IF NOT EXISTS raw_response (
    id          INTEGER PRIMARY KEY,
    run_id      INTEGER REFERENCES pipeline_run (id),
    source      TEXT NOT NULL,
    url         TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    body        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS offshore_conditions (
    id          INTEGER PRIMARY KEY,
    observed_at TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    latitude    REAL NOT NULL,
    longitude   REAL NOT NULL,
    readings    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS forecast_hour (
    valid_at    TEXT PRIMARY KEY,
    fetched_at  TEXT NOT NULL,
    readings    TEXT NOT NULL
);

-- Append-only, and deliberately so. ADR 0005: "Every prediction the system has ever made
-- is retained by construction. That gives us the record needed to evaluate Go Call
-- precision after the fact." An earlier shape keyed this table on `date` and cleared it
-- at the start of every run, so each Pipeline Run destroyed the record ticket #11 exists
-- to score -- while the module claiming retention sat directly above it.
--
-- A date therefore accumulates one row per run, and the succession of calls made about a
-- single date as it approaches is itself the thing #11 measures: a Watch at ten days that
-- became a Go Call at four and then a flat sea is a different failure from one never
-- called at all.
CREATE TABLE IF NOT EXISTS day_call (
    id                  INTEGER PRIMARY KEY,
    run_id              INTEGER REFERENCES pipeline_run (id),
    date                TEXT NOT NULL,
    issued_at           TEXT NOT NULL,
    issued_for_date     TEXT NOT NULL,
    status              TEXT NOT NULL,
    lead_time_days      INTEGER NOT NULL,
    reasons             TEXT NOT NULL,
    predicted_significant_wave_height REAL NOT NULL,
    unit                TEXT NOT NULL,
    amplification_model TEXT NOT NULL,
    calibrated          INTEGER NOT NULL,
    -- The provenance of the thresholds this call was decided against (#12), as JSON.
    --
    -- Stored per call rather than read from the threshold file when the API answers,
    -- because the file changes and the calls do not. A recalibration landing between a
    -- Pipeline Run and a request would otherwise relabel every historical call with the
    -- provenance of a fit it was never decided under — which is exactly the kind of
    -- untraceable prediction #30 added run records to prevent.
    --
    -- Null for calls written before #12, which genuinely had no calibration.
    calibration         TEXT
);

-- Every wave model's own reading for every forecast hour, kept apart (#8).
--
-- **Not averaged on arrival**, which is the first thing ticket #8 asks for. An average is
-- the one transformation of an ensemble that cannot be undone: once five members become one
-- number, the disagreement ADR 0003 uses as the system's uncertainty estimate is gone and no
-- amount of later work recovers it. Storing the members means a spread can be re-derived on
-- a different rule — the deciding hour rather than the median one, say — without refetching
-- and without a migration.
--
-- Replaced wholesale each run, like `forecast_hour` and for the same reason: this is the
-- current forecast, not a record of what was once said about a date. `day_spread` below is
-- the part that accumulates.
--
-- A model that returned nothing for an hour has no row for that hour. Absence is the
-- record: a row carrying null would need every reader to re-derive "did not answer" from
-- it, and `spread.derive` already treats the two identically.
CREATE TABLE IF NOT EXISTS model_forecast_hour (
    valid_at   TEXT NOT NULL,
    model      TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    readings   TEXT NOT NULL,
    PRIMARY KEY (valid_at, model)
);

-- Model Spread per date per variable, appended run after run.
--
-- Append-only for the same reason `day_call` is, and it is the same record: the spread
-- behind a call is an input to it, so scoring a Go Call after the fact (#11) needs the
-- disagreement that was current when the call was issued, not whatever it became once the
-- date drew closer and the models converged. Overwriting per date would destroy exactly the
-- series that makes the record worth keeping.
--
-- `value` is nullable, and a row is written even when it is null. A date where fewer than
-- two organisations reported has no measurable Model Spread (ADR 0003 degrades the estimate
-- rather than failing the run) — and if that were recorded by writing no row, it would be
-- indistinguishable from a Pipeline Run that never happened. `providers` still lists whoever
-- did answer, so the degradation says how far it went.
CREATE TABLE IF NOT EXISTS day_spread (
    id               INTEGER PRIMARY KEY,
    run_id           INTEGER REFERENCES pipeline_run (id),
    date             TEXT NOT NULL,
    derived_at       TEXT NOT NULL,
    variable         TEXT NOT NULL,
    value            REAL,
    -- The two opinions the spread was measured between. For a bearing these are the arc's
    -- start and end running clockwise, so across north `highest` is the smaller number --
    -- see `spread.Spread`. Null exactly when `value` is.
    lowest           REAL,
    highest          REAL,
    unit             TEXT NOT NULL,
    providers        TEXT NOT NULL,
    models_reporting INTEGER NOT NULL,
    hours_measured   INTEGER NOT NULL,
    hours_total      INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS offshore_conditions_observed_at
    ON offshore_conditions (observed_at DESC);

CREATE INDEX IF NOT EXISTS day_call_date
    ON day_call (date, id DESC);

CREATE INDEX IF NOT EXISTS day_spread_date
    ON day_spread (date, variable, id DESC);
"""


# Written once. The same ten columns were spelled out in the schema probe and in every
# read, so adding or renaming one meant finding all of them — and a rename that missed the
# probe would pass construction and fail inside an endpoint, which is the bare-500 outcome
# eager verification exists to prevent.
CALL_COLUMNS = (
    "date, issued_at, issued_for_date, status, lead_time_days, reasons, "
    "predicted_significant_wave_height, unit, amplification_model, calibrated, calibration"
)

RUN_COLUMNS = "id, started_at, finished_at, outcome, failure_kind, failure_detail"

SPREAD_COLUMNS = (
    "date, derived_at, variable, value, lowest, highest, unit, providers, "
    "models_reporting, hours_measured, hours_total"
)


def _optional_json(value: Any) -> str | None:
    """Serialise a value that may legitimately be absent, keeping absence distinct from `null`.

    A call with no calibration behind it stores SQL NULL rather than the four characters
    "null", so `_call` can tell "written before #12" from "written with a calibration that
    happened to be empty" without parsing anything.
    """
    return None if value is None else json.dumps(value)


class StoreUnavailable(RuntimeError):
    """The store cannot be opened or read.

    Usually a configuration fault — a path pointing at nothing, at a directory, or at a
    file that is not a database. It can also be transient, such as another process
    holding a write lock. What it never means is that the store is simply empty: that is
    reported as an absence of conditions, not as a fault.
    """


def now() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    """A SQLite-backed store, safe to share across threads.

    Connections are per-thread. A single shared `sqlite3.Connection` is not safe under a
    threaded server even with `check_same_thread=False`: FastAPI runs synchronous
    endpoints in a threadpool, and concurrent reads through one connection returned
    `None` for populated columns and raised `IndexError` from the shared statement cache.
    Under load that surfaced as the API reporting no conditions while holding conditions
    — a plausible-looking lie rather than a crash.

    A store that creates its database is writable; one that opens an existing database
    for serving is opened read-only, so ADR 0005's "the API is strictly a reader" is
    enforced by SQLite rather than left to convention.
    """

    def __init__(self, path: str | Path | None = None, *, create: bool = True) -> None:
        self.path = Path(path) if path is not None else DEFAULT_DATABASE
        self.writable = create

        self._local = threading.local()
        # Every connection handed out, so all can be closed. Windows holds a file lock
        # while any remain open, which makes the database impossible to delete.
        self._connections: list[sqlite3.Connection] = []
        self._lock = threading.Lock()

        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = self._connect()
            connection.executescript(SCHEMA)
            self._migrate(connection)
            return

        # Creating the file here would turn a misconfigured path into an empty database,
        # and the API would then answer "no conditions yet" — a config fault wearing the
        # costume of missing data.
        if not self.path.exists():
            raise StoreUnavailable(f"No database at {self.path}")

        # Open and check the schema now rather than on first query. Deferring it meant
        # every open-time fault — a directory, a file that is not a database, an empty
        # file — surfaced inside the endpoint instead of the dependency, where nothing
        # handled it: the browser got a bare 500 with no CORS header rather than an
        # explanation.
        self._verify()

    @staticmethod
    def _migrate(connection: sqlite3.Connection) -> None:
        """Add columns to tables created before the tickets that introduced them.

        Ticket #30's run reference, and ticket #12's threshold provenance.

        `CREATE TABLE IF NOT EXISTS` leaves an existing table exactly as it found it, so a
        store that predates this ticket would otherwise keep its old shape and fail every
        read that names `run_id` — turning a schema change into a "delete the database"
        instruction. ADR 0005 makes that record the asset; it cannot be the thing a
        migration asks you to throw away.

        The column is nullable rather than backfilled. Rows written before runs were
        recorded genuinely have no run to point at, and inventing one would fabricate
        exactly the provenance this ticket exists to make trustworthy. A null here means
        "written before this system tracked runs", which is true and checkable.

        Ticket #8 needed nothing here, and that is worth stating rather than leaving as an
        apparent omission: it added two whole tables rather than columns, and
        `CREATE TABLE IF NOT EXISTS` already creates those on an existing store. A database
        predating #8 opens, gains both tables, and simply holds no Model Spread for the runs
        that happened before there was one — which is true.
        """
        for table in ("raw_response", "day_call"):
            columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
            if "run_id" not in columns:
                connection.execute(
                    f"ALTER TABLE {table} ADD COLUMN run_id INTEGER REFERENCES pipeline_run (id)"
                )

        # Nullable and not backfilled, for the same reason `run_id` is. A call issued
        # before #12 was decided against the rule of thumb and had no calibration behind
        # it; writing today's provenance onto it would claim those calls came from a fit
        # that did not exist when they were made.
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(day_call)")}
        if "calibration" not in columns:
            connection.execute("ALTER TABLE day_call ADD COLUMN calibration TEXT")

        connection.commit()

    def _verify(self) -> None:
        """Run the reads this store performs, against no rows.

        Checking table names alone was not enough: a database carrying the right tables
        with the wrong columns passed construction and then failed inside the endpoint
        with "no such column", which is the bare-500-without-CORS outcome eager
        verification exists to prevent. Executing the real queries with LIMIT 0 checks
        the columns too, and cannot drift from what the store actually asks for.
        """
        probes = (
            "SELECT observed_at, fetched_at, latitude, longitude, readings "
            "FROM offshore_conditions LIMIT 0",
            "SELECT run_id, source, url, fetched_at, body FROM raw_response LIMIT 0",
            "SELECT valid_at, fetched_at, readings FROM forecast_hour LIMIT 0",
            "SELECT valid_at, model, fetched_at, readings FROM model_forecast_hour LIMIT 0",
            f"SELECT id, run_id, {CALL_COLUMNS} FROM day_call LIMIT 0",
            f"SELECT id, run_id, {SPREAD_COLUMNS} FROM day_spread LIMIT 0",
            f"SELECT {RUN_COLUMNS} FROM pipeline_run LIMIT 0",
        )
        try:
            for probe in probes:
                self._connect().execute(probe)
        except sqlite3.Error as error:
            # Close before raising: the connection is registered on a Store no caller
            # can reach, and on Windows it holds a lock that makes the file unlinkable.
            self.close()
            raise StoreUnavailable(f"Cannot read {self.path}: {error}") from error

    def _connect(self) -> sqlite3.Connection:
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            return connection

        try:
            if self.writable:
                connection = sqlite3.connect(self.path, check_same_thread=False)
            else:
                # The path must be percent-encoded. Unescaped, a '#' in any directory
                # name starts a URI fragment: SQLite then reads a truncated path,
                # discards ?mode=ro, and happily creates a read-write database
                # somewhere else entirely — defeating read-only mode and the
                # never-create rule at the same time, silently.
                encoded = urllib.parse.quote(self.path.as_posix())
                connection = sqlite3.connect(
                    f"file:{encoded}?mode=ro", uri=True, check_same_thread=False
                )
        except sqlite3.Error as error:
            raise StoreUnavailable(f"Cannot open {self.path}: {error}") from error

        connection.row_factory = sqlite3.Row
        # SQLite ignores REFERENCES clauses unless this is switched on, per connection.
        # Without it the run references in `raw_response` and `day_call` are documentation
        # that reads like a guarantee — a call could name a run that does not exist, and
        # the lookup this ticket exists to provide would return nothing with no complaint.
        # Set before any statement runs: it is a no-op inside a transaction.
        connection.execute("PRAGMA foreign_keys = ON")
        self._local.connection = connection
        with self._lock:
            self._connections.append(connection)
        return connection

    def close(self) -> None:
        """Close every connection this store has opened."""
        with self._lock:
            for connection in self._connections:
                connection.close()
            self._connections.clear()
        self._local = threading.local()

    def begin_run(self) -> int:
        """Open a Pipeline Run record and return its identifier.

        Committed immediately, before the run fetches anything. Writing the record at the
        end instead would mean the runs that most need explaining — the ones that died
        partway, or took the process down with them — are exactly the ones that leave
        nothing behind.
        """
        connection = self._connect()
        cursor = connection.execute(
            "INSERT INTO pipeline_run (started_at, outcome) VALUES (?, ?)",
            (now(), RunOutcome.RUNNING.value),
        )
        connection.commit()
        run_id = cursor.lastrowid
        if run_id is None:  # pragma: no cover — SQLite always assigns a rowid here
            raise StoreUnavailable("SQLite assigned no identifier to the Pipeline Run")
        return run_id

    def record_run_failed(self, run_id: int, kind: FailureKind, detail: str) -> None:
        """Close a Pipeline Run record as failed, with what went wrong.

        A failed run writes no conditions, forecast or calls — `record_run` is one
        transaction precisely so a bad run leaves the previous ones untouched — but the
        attempt itself is part of the record. Before this, the only trace was a line on
        stdout and, six hours later, the interface going stale.

        Raw responses are the exception, and not an oversight: they are committed as each
        endpoint answers, so a run that failed partway keeps whatever it had already
        fetched. `inputs_behind` will return it.
        """
        connection = self._connect()
        connection.execute(
            "UPDATE pipeline_run SET outcome = ?, finished_at = ?, failure_kind = ?, "
            "failure_detail = ? WHERE id = ?",
            (RunOutcome.FAILED.value, now(), kind.value, detail, run_id),
        )
        connection.commit()

    def runs(self) -> list[dict[str, Any]]:
        """Every Pipeline Run recorded, oldest first."""
        rows = self._connect().execute(f"SELECT {RUN_COLUMNS} FROM pipeline_run ORDER BY id")
        return [dict(row) for row in rows]

    def failed_runs(self) -> list[dict[str, Any]]:
        """Every Pipeline Run that failed, oldest first.

        Queryable rather than requiring the caller to filter, because "show me what went
        wrong this season" is the question this table was added to answer.
        """
        rows = self._connect().execute(
            f"SELECT {RUN_COLUMNS} FROM pipeline_run WHERE outcome = ? ORDER BY id",
            (RunOutcome.FAILED.value,),
        )
        return [dict(row) for row in rows]

    def inputs_behind(self, run_id: int) -> list[dict[str, Any]]:
        """The raw provider responses a given run fetched, oldest first.

        This is the lookup ticket #30 exists to make possible. Given a stored call, its
        `run_id` leads straight here — rather than to a scan of `raw_response` for rows
        whose `fetched_at` looks close enough to the call's `issued_at`, which is a guess
        that gets less reliable the more runs the store accumulates.
        """
        rows = self._connect().execute(
            "SELECT run_id, source, url, fetched_at, body FROM raw_response "
            "WHERE run_id = ? ORDER BY id",
            (run_id,),
        )
        return [dict(row) for row in rows]

    def record_raw_response(self, run_id: int, source: str, url: str, body: dict[str, Any]) -> None:
        """Persist a provider response as received, against the run that fetched it."""
        connection = self._connect()
        connection.execute(
            "INSERT INTO raw_response (run_id, source, url, fetched_at, body) "
            "VALUES (?, ?, ?, ?, ?)",
            (run_id, source, url, now(), json.dumps(body)),
        )
        connection.commit()

    def record_run(
        self,
        observed_at: str,
        latitude: float,
        longitude: float,
        readings: dict[str, dict[str, Any]],
        hours: list[dict[str, Any]],
        calls: list[dict[str, Any]],
        model_hours: list[dict[str, Any]],
        spreads: list[dict[str, Any]],
        *,
        run_id: int,
    ) -> None:
        """Store a Pipeline Run's conditions, forecast, calls and Model Spread, or none of it.

        Two separate commits meant a fault between them advanced the current conditions
        while the forecast stayed behind — the half-updated picture the pipeline's own
        docstring promises never happens. Validating earlier did not fix that; only one
        transaction does.

        `calls` is required rather than defaulted. ADR 0005 retains every prediction "by
        construction", and a construction with an opt-out is a convention: as an optional
        argument, a caller that forgot it stored a forecast with no calls and reported
        success.

        `model_hours` and `spreads` are required for the same reason, and they belong inside
        this transaction rather than beside it. The forecast and the per-model readings the
        ensemble gave for the same hours have to move together: a run that advanced one and
        not the other would leave a Model Spread describing a forecast the store no longer
        holds, which is the half-updated picture the pipeline's docstring promises never to
        produce. An empty `spreads` is a legitimate value — a run whose ensemble was
        unreachable — but it has to be passed deliberately.

        `run_id` is required for the same reason, and marking the run succeeded happens
        inside this transaction rather than after it. A run reported as succeeded whose
        output was rolled back would be worse than no record at all: it is the plausible
        false answer this project keeps having to design against.
        """
        connection = self._connect()
        stamp = now()
        with connection:
            # Forecast first, conditions last. With conditions first, whichever write
            # failed the other had not happened yet, so neither failure direction
            # actually exercised the rollback. This way a failing forecast insert must
            # undo the DELETE, and a failing conditions insert must undo the whole
            # forecast replacement.
            connection.execute("DELETE FROM forecast_hour")
            connection.executemany(
                "INSERT INTO forecast_hour (valid_at, fetched_at, readings) VALUES (?, ?, ?)",
                [(hour["at"], stamp, json.dumps(hour["readings"])) for hour in hours],
            )
            # Replaced alongside the forecast, never independently of it. These are the
            # members the forecast's own hours were compared against.
            connection.execute("DELETE FROM model_forecast_hour")
            connection.executemany(
                "INSERT INTO model_forecast_hour (valid_at, model, fetched_at, readings) "
                "VALUES (?, ?, ?, ?)",
                [
                    (hour["at"], hour["model"], stamp, json.dumps(hour["readings"]))
                    for hour in model_hours
                ],
            )
            # Appended, never cleared. Each run adds this run's calls beside every call
            # the system has already made, which is what ADR 0005 promises and what
            # ticket #11 scores.
            connection.executemany(
                "INSERT INTO day_call (run_id, date, issued_at, issued_for_date, status, "
                "lead_time_days, reasons, predicted_significant_wave_height, unit, "
                "amplification_model, calibrated, calibration) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        run_id,
                        call["date"],
                        stamp,
                        call["issued_for_date"],
                        call["status"],
                        call["lead_time_days"],
                        json.dumps(call["reasons"]),
                        call["predicted_significant_wave_height"],
                        call["unit"],
                        call["amplification_model"],
                        int(call["calibrated"]),
                        _optional_json(call.get("calibration")),
                    )
                    for call in calls
                ],
            )
            # Appended beside the calls of the same run, never cleared, for the reason the
            # table's own comment gives: the disagreement current when a call was issued is
            # an input to that call, and #11 scores calls against their inputs.
            connection.executemany(
                "INSERT INTO day_spread (run_id, date, derived_at, variable, value, lowest, "
                "highest, unit, providers, models_reporting, hours_measured, hours_total) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        run_id,
                        spread["date"],
                        stamp,
                        spread["variable"],
                        spread["value"],
                        spread["lowest"],
                        spread["highest"],
                        spread["unit"],
                        json.dumps(spread["providers"]),
                        spread["models_reporting"],
                        spread["hours_measured"],
                        spread["hours_total"],
                    )
                    for spread in spreads
                ],
            )
            connection.execute(
                "INSERT INTO offshore_conditions "
                "(observed_at, fetched_at, latitude, longitude, readings) "
                "VALUES (?, ?, ?, ?, ?)",
                (observed_at, stamp, latitude, longitude, json.dumps(readings)),
            )
            connection.execute(
                "UPDATE pipeline_run SET outcome = ?, finished_at = ? WHERE id = ?",
                (RunOutcome.SUCCEEDED.value, stamp, run_id),
            )

    def forecast(self) -> list[dict[str, Any]]:
        """Every stored forecast hour, earliest first."""
        rows = self._connect().execute(
            "SELECT valid_at, fetched_at, readings FROM forecast_hour ORDER BY valid_at"
        )
        return [
            {
                "at": row["valid_at"],
                "fetched_at": row["fetched_at"],
                "readings": json.loads(row["readings"]),
            }
            for row in rows
        ]

    def model_forecast(self) -> list[dict[str, Any]]:
        """Every wave model's own forecast hours, earliest first, then by model.

        The ensemble as it arrived, before anything collapsed it into a spread. Nothing
        serves this over HTTP yet: it exists so a later rule for choosing a date's
        representative hour — the deciding hour rather than the median one, which is the
        Decision Model's half of #8 — can be computed from the store rather than from a
        second request to the provider.
        """
        rows = self._connect().execute(
            "SELECT valid_at, model, fetched_at, readings FROM model_forecast_hour "
            "ORDER BY valid_at, model"
        )
        return [
            {
                "at": row["valid_at"],
                "model": row["model"],
                "fetched_at": row["fetched_at"],
                "readings": json.loads(row["readings"]),
            }
            for row in rows
        ]

    def spreads(self) -> dict[str, dict[str, dict[str, Any]]]:
        """The most recent Model Spread for each date and variable: `{date: {variable: …}}`.

        Latest per date by insertion order rather than by `derived_at`, for the reason
        `calls` gives at length: a wall clock can be moved backwards and insertion order
        cannot, and serving a superseded spread as current would understate or overstate
        today's doubt with nothing to show for it.
        """
        rows = self._connect().execute(
            f"SELECT {SPREAD_COLUMNS} FROM day_spread WHERE id IN "
            "(SELECT MAX(id) FROM day_spread GROUP BY date, variable) ORDER BY date, variable"
        )
        by_date: dict[str, dict[str, dict[str, Any]]] = {}
        for row in rows:
            by_date.setdefault(row["date"], {})[row["variable"]] = self._spread(row)
        return by_date

    def spread_history(self) -> list[dict[str, Any]]:
        """Every Model Spread ever derived, oldest first, including superseded ones.

        The counterpart of `call_history`, and the same deliberate exception to the backend
        seam: what a date's disagreement was at ten days and what it had become at three is
        the series #11 needs to say whether narrowing spread actually preceded the swells
        that arrived, and no HTTP surface exposes it yet.
        """
        rows = self._connect().execute(
            f"SELECT run_id, {SPREAD_COLUMNS} FROM day_spread ORDER BY id"
        )
        return [self._spread(row) | {"run_id": row["run_id"]} for row in rows]

    @staticmethod
    def _spread(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "date": row["date"],
            "derived_at": row["derived_at"],
            "variable": row["variable"],
            "value": row["value"],
            "lowest": row["lowest"],
            "highest": row["highest"],
            "unit": row["unit"],
            "providers": json.loads(row["providers"]),
            "models_reporting": row["models_reporting"],
            "hours_measured": row["hours_measured"],
            "hours_total": row["hours_total"],
        }

    def calls(self) -> dict[str, dict[str, Any]]:
        """The most recent call made about each date, keyed by that date.

        Stored rather than computed on request. ADR 0005 makes the API strictly a reader
        and the Pipeline Run the only thing that runs a model — and it promises that every
        prediction the system has made is retained, which is the record ticket #11 needs to
        score Go Call precision after the fact. Computing them per request produced none.

        Latest per date by insertion order, not by `issued_at`. The timestamp usually
        agrees — it carries microseconds, so runs rarely tie — but it is a wall clock, and
        a wall clock can be adjusted backwards by NTP or a timezone change, which silently
        inverts the ordering and serves a superseded call as current. Insertion order
        cannot go backwards. What a reader wants is the newest call, and that is the one
        inserted last.
        """
        rows = self._connect().execute(
            f"SELECT {CALL_COLUMNS} FROM day_call "
            "WHERE id IN (SELECT MAX(id) FROM day_call GROUP BY date) ORDER BY date"
        )
        return {row["date"]: self._call(row) for row in rows}

    def latest_call(self) -> dict[str, Any] | None:
        """The most recently stored call, whichever date it applies to, or None if empty.

        Which Amplification Model produced the current calls, and whether its thresholds
        are calibrated, are properties of the run rather than of any one date — so the
        answer comes from here rather than being reconstructed by the reader. The reader's
        version sorted by `issued_at`, the comparison `calls()` above rules out: a wall
        clock adjusted backwards inverts it, and identical timestamps leave the winner to
        whichever row SQLite happened to return first. It also asked the reader to know
        that the newest call is the newest run, which is the store's business.
        """
        row = (
            self._connect()
            .execute(f"SELECT {CALL_COLUMNS} FROM day_call ORDER BY id DESC LIMIT 1")
            .fetchone()
        )
        return None if row is None else self._call(row)

    def call_history(self) -> list[dict[str, Any]]:
        """Every call ever made, oldest first, including superseded ones.

        No HTTP surface exposes these yet — ticket #11 scores Go Call precision from this
        record, and #16 publishes the result. Like `raw_responses`, this is a deliberate
        narrow exception to the backend seam: retention across runs is required by ADR
        0005 and there is nothing else that can observe it. When the track record gets an
        endpoint, the test should move to it.
        """
        rows = self._connect().execute(f"SELECT run_id, {CALL_COLUMNS} FROM day_call ORDER BY id")
        # `run_id` is carried on the history rather than on `calls()` and `latest_call()`:
        # those two feed the API's responses, and which run produced a call is provenance
        # for whoever audits the record, not something a traveller reading a forecast has
        # any use for. When the track record gets an endpoint (#16), that can change.
        return [self._call(row) | {"date": row["date"], "run_id": row["run_id"]} for row in rows]

    @staticmethod
    def _call(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "issued_at": row["issued_at"],
            "issued_for_date": row["issued_for_date"],
            "status": row["status"],
            "lead_time_days": row["lead_time_days"],
            "reasons": json.loads(row["reasons"]),
            "predicted_significant_wave_height": row["predicted_significant_wave_height"],
            "unit": row["unit"],
            "amplification_model": row["amplification_model"],
            "calibrated": bool(row["calibrated"]),
            "calibration": None if row["calibration"] is None else json.loads(row["calibration"]),
        }

    def latest_conditions(self) -> dict[str, Any] | None:
        """The most recently ingested Offshore Conditions, or None if the store is empty.

        Ordered by insertion rather than observation time: a later run always supersedes
        an earlier one, even if a provider revises a timestamp backwards.
        """
        row = (
            self._connect()
            .execute(
                "SELECT observed_at, fetched_at, latitude, longitude, readings "
                "FROM offshore_conditions ORDER BY id DESC LIMIT 1"
            )
            .fetchone()
        )
        if row is None:
            return None
        return {
            "observed_at": row["observed_at"],
            "fetched_at": row["fetched_at"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "readings": json.loads(row["readings"]),
        }

    def raw_responses(self) -> Iterable[dict[str, Any]]:
        """Every raw provider response retained, oldest first.

        No HTTP surface exposes these, so the test covering their retention drives this
        method directly. That is a deliberate, narrow exception to the backend seam: the
        behaviour is required by ticket #4 and there is nothing else to observe it
        through. When run diagnostics get an endpoint, the test should move to it.
        """
        rows = (
            self._connect()
            .execute("SELECT run_id, source, url, fetched_at, body FROM raw_response ORDER BY id")
            .fetchall()
        )
        return [dict(row) for row in rows]

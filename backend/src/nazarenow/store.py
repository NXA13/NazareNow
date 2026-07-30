"""Persistence for Pipeline Run output.

SQLite: the whole dataset is small, single-writer, and read by one process. A server
database would add operational weight this project has no use for yet. Swapping it later
means changing this module and nothing else, which is the point of keeping the store
internal to the backend seam (ADR 0005).

Three things are stored for every run: the provider's response as received, the values
parsed out of it, and the calls derived from those values. Retaining the raw response
means derived data can be rebuilt without refetching, and that a provider changing shape
can be diagnosed after the fact. Retaining the calls is ADR 0005's promise that every
prediction the system has made survives, which is what ticket #11 scores.
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
CREATE TABLE IF NOT EXISTS raw_response (
    id          INTEGER PRIMARY KEY,
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
    date                TEXT NOT NULL,
    issued_at           TEXT NOT NULL,
    issued_for_date     TEXT NOT NULL,
    status              TEXT NOT NULL,
    lead_time_days      INTEGER NOT NULL,
    reasons             TEXT NOT NULL,
    predicted_significant_wave_height REAL NOT NULL,
    unit                TEXT NOT NULL,
    amplification_model TEXT NOT NULL,
    calibrated          INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS offshore_conditions_observed_at
    ON offshore_conditions (observed_at DESC);

CREATE INDEX IF NOT EXISTS day_call_date
    ON day_call (date, id DESC);
"""


# Written once. The same ten columns were spelled out in the schema probe and in every
# read, so adding or renaming one meant finding all of them — and a rename that missed the
# probe would pass construction and fail inside an endpoint, which is the bare-500 outcome
# eager verification exists to prevent.
CALL_COLUMNS = (
    "date, issued_at, issued_for_date, status, lead_time_days, reasons, "
    "predicted_significant_wave_height, unit, amplification_model, calibrated"
)


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
            self._connect().executescript(SCHEMA)
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
            "SELECT source, url, fetched_at, body FROM raw_response LIMIT 0",
            "SELECT valid_at, fetched_at, readings FROM forecast_hour LIMIT 0",
            f"SELECT id, {CALL_COLUMNS} FROM day_call LIMIT 0",
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

    def record_raw_response(self, source: str, url: str, body: dict[str, Any]) -> None:
        """Persist a provider response as received."""
        connection = self._connect()
        connection.execute(
            "INSERT INTO raw_response (source, url, fetched_at, body) VALUES (?, ?, ?, ?)",
            (source, url, now(), json.dumps(body)),
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
    ) -> None:
        """Store a Pipeline Run's conditions, forecast and calls together, or not at all.

        Two separate commits meant a fault between them advanced the current conditions
        while the forecast stayed behind — the half-updated picture the pipeline's own
        docstring promises never happens. Validating earlier did not fix that; only one
        transaction does.

        `calls` is required rather than defaulted. ADR 0005 retains every prediction "by
        construction", and a construction with an opt-out is a convention: as an optional
        argument, a caller that forgot it stored a forecast with no calls and reported
        success.
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
            # Appended, never cleared. Each run adds this run's calls beside every call
            # the system has already made, which is what ADR 0005 promises and what
            # ticket #11 scores.
            connection.executemany(
                "INSERT INTO day_call (date, issued_at, issued_for_date, status, "
                "lead_time_days, reasons, predicted_significant_wave_height, unit, "
                "amplification_model, calibrated) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
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
                    )
                    for call in calls
                ],
            )
            connection.execute(
                "INSERT INTO offshore_conditions "
                "(observed_at, fetched_at, latitude, longitude, readings) "
                "VALUES (?, ?, ?, ?, ?)",
                (observed_at, stamp, latitude, longitude, json.dumps(readings)),
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
        rows = self._connect().execute(f"SELECT {CALL_COLUMNS} FROM day_call ORDER BY id")
        return [self._call(row) | {"date": row["date"]} for row in rows]

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
            .execute("SELECT source, url, fetched_at, body FROM raw_response ORDER BY id")
            .fetchall()
        )
        return [dict(row) for row in rows]

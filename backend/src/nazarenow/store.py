"""Persistence for Pipeline Run output.

SQLite: the whole dataset is small, single-writer, and read by one process. A server
database would add operational weight this project has no use for yet. Swapping it later
means changing this module and nothing else, which is the point of keeping the store
internal to the backend seam (ADR 0005).

Two things are stored for every run: the provider's response as received, and the values
parsed out of it. Retaining the raw response means derived data can be rebuilt without
refetching, and that a provider changing shape can be diagnosed after the fact.
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

CREATE INDEX IF NOT EXISTS offshore_conditions_observed_at
    ON offshore_conditions (observed_at DESC);
"""


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

    def record_conditions(
        self,
        observed_at: str,
        latitude: float,
        longitude: float,
        readings: dict[str, dict[str, Any]],
    ) -> None:
        connection = self._connect()
        connection.execute(
            "INSERT INTO offshore_conditions "
            "(observed_at, fetched_at, latitude, longitude, readings) VALUES (?, ?, ?, ?, ?)",
            (observed_at, now(), latitude, longitude, json.dumps(readings)),
        )
        connection.commit()

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

    def record_run(
        self,
        observed_at: str,
        latitude: float,
        longitude: float,
        readings: dict[str, dict[str, Any]],
        hours: list[dict[str, Any]],
    ) -> None:
        """Store a Pipeline Run's conditions and forecast together, or not at all.

        Two separate commits meant a fault between them advanced the current conditions
        while the forecast stayed behind — the half-updated picture the pipeline's own
        docstring promises never happens. Validating earlier did not fix that; only one
        transaction does.
        """
        connection = self._connect()
        stamp = now()
        with connection:
            connection.execute(
                "INSERT INTO offshore_conditions "
                "(observed_at, fetched_at, latitude, longitude, readings) "
                "VALUES (?, ?, ?, ?, ?)",
                (observed_at, stamp, latitude, longitude, json.dumps(readings)),
            )
            connection.execute("DELETE FROM forecast_hour")
            connection.executemany(
                "INSERT INTO forecast_hour (valid_at, fetched_at, readings) VALUES (?, ?, ?)",
                [(hour["at"], stamp, json.dumps(hour["readings"])) for hour in hours],
            )

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

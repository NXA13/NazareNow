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

CREATE INDEX IF NOT EXISTS offshore_conditions_observed_at
    ON offshore_conditions (observed_at DESC);
"""


class StoreUnavailable(RuntimeError):
    """The store cannot be opened — a configuration fault, not an absence of data."""


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

    Opened read-only unless it is being written to, so ADR 0005's "the API is strictly a
    reader" is enforced by SQLite rather than left to convention.
    """

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        create: bool = True,
        writable: bool | None = None,
    ) -> None:
        self.path = Path(path) if path is not None else DEFAULT_DATABASE
        self.writable = create if writable is None else writable

        self._local = threading.local()
        # Every connection handed out, so all can be closed. Windows holds a file lock
        # while any remain open, which makes the database impossible to delete.
        self._connections: list[sqlite3.Connection] = []
        self._lock = threading.Lock()

        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._connect().executescript(SCHEMA)
        elif not self.path.exists():
            # Creating the file here would turn a misconfigured path into an empty
            # database, and the API would then answer "no conditions yet" — a config
            # fault wearing the costume of missing data.
            raise StoreUnavailable(f"No database at {self.path}")

    def _connect(self) -> sqlite3.Connection:
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            return connection

        try:
            if self.writable:
                connection = sqlite3.connect(self.path, check_same_thread=False)
            else:
                connection = sqlite3.connect(
                    f"file:{self.path.as_posix()}?mode=ro", uri=True, check_same_thread=False
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

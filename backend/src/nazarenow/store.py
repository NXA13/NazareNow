"""Persistence for Pipeline Run output.

SQLite: the whole dataset is small, single-writer, and read by one process. A server
database would add operational weight this project has no use for yet. Swapping it later
means changing this module and nothing else, which is the point of keeping the store
internal to the backend seam (ADR 0005).

Two things are stored for every run: the provider's raw response exactly as received,
and the values parsed out of it. Retaining the raw response means derived data can be
rebuilt without refetching, and that a provider changing shape can be diagnosed after
the fact rather than guessed at.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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


def now() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript(SCHEMA)
        self._connection.commit()

    def record_raw_response(self, source: str, url: str, body: dict[str, Any]) -> None:
        """Persist a provider response verbatim, before anything interprets it."""
        self._connection.execute(
            "INSERT INTO raw_response (source, url, fetched_at, body) VALUES (?, ?, ?, ?)",
            (source, url, now(), json.dumps(body)),
        )
        self._connection.commit()

    def record_conditions(
        self,
        observed_at: str,
        latitude: float,
        longitude: float,
        readings: dict[str, dict[str, Any]],
    ) -> None:
        self._connection.execute(
            "INSERT INTO offshore_conditions "
            "(observed_at, fetched_at, latitude, longitude, readings) VALUES (?, ?, ?, ?, ?)",
            (observed_at, now(), latitude, longitude, json.dumps(readings)),
        )
        self._connection.commit()

    def latest_conditions(self) -> dict[str, Any] | None:
        """The most recently ingested Offshore Conditions, or None if the store is empty.

        Ordered by insertion rather than observation time: a later run always supersedes
        an earlier one, even if a provider revises a timestamp backwards.
        """
        row = self._connection.execute(
            "SELECT observed_at, fetched_at, latitude, longitude, readings "
            "FROM offshore_conditions ORDER BY id DESC LIMIT 1"
        ).fetchone()
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
        rows = self._connection.execute(
            "SELECT source, url, fetched_at, body FROM raw_response ORDER BY id"
        ).fetchall()
        return [dict(row) for row in rows]

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
from collections.abc import Collection, Iterable
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
    calibration         TEXT,
    -- What the independent wave models said about the hour this call rests on (#8).
    --
    -- Stored rather than derived, because it genuinely cannot be derived from the rest of
    -- the record: `day_spread` below holds the date's *median* hour, and a call is decided
    -- on its best matching hour. Those are different hours. Without this column the record
    -- would carry a call and a spread describing two different moments of one day, and
    -- nothing in it would say so — which is the kind of plausible mismatch #11 would score
    -- straight past.
    --
    -- Null for calls written before the Decision Model read Model Spread at all. Those
    -- calls were issued without consulting the models, and labelling them "agreed" would
    -- claim an agreement nobody ever checked.
    model_agreement     TEXT,
    -- Whether the models refused a Go Call this day's conditions otherwise supported (#8).
    --
    -- Stored rather than derived, because it cannot be derived from the two columns beside
    -- it. A day whose own swell period sits below the Go Call bar has every organisation
    -- below it too and records `divided` while the ensemble decided nothing; only the
    -- Decision Model saw the conditions next to the verdict and can say which happened.
    --
    -- Null, like `model_agreement`, for calls issued before any of this existed.
    go_call_withheld    INTEGER,
    -- The Predictive Distribution this call was decided on (#15, ADR 0004).
    --
    -- The 5th and 95th percentiles as two columns rather than one JSON blob, because #11
    -- scores calls against what the ocean did and "how often did the outcome land inside
    -- the stated range" is the question this ticket makes askable. A blob would put that
    -- behind a parse in every query.
    --
    -- Stored rather than recomputed on read, for the reason `calibration` is: the profile,
    -- the fitted coefficients and the ensemble all change, and a range recomputed at
    -- request time would describe a distribution the call was never decided under. It also
    -- genuinely cannot be recomputed — the ensemble term is measured from the deciding
    -- hour's members, and which hour that was is not recoverable from this table.
    --
    -- Null for calls issued before the pipeline built distributions at all.
    plausible_low_m     REAL,
    plausible_high_m    REAL,
    -- How much of that distribution cleared the calibrated height bar (#15).
    --
    -- The height condition alone. Named `gold_day_probability` until #66, which found the
    -- name claiming all four Go conditions for a number that prices one; the stored values
    -- are unchanged and were carried across by the rename in `_migrate`.
    height_bar_probability REAL,
    -- Whether a measured Forecast Error Profile covered this call's Lead Time.
    --
    -- False past the archive's seven days, where the width is extrapolated and the centre
    -- held at its last measured correction. Carried so the interface can be visibly more
    -- cautious rather than presenting an extrapolation as evidence, and so #11 can tell the
    -- two populations apart when it scores them.
    uncertainty_measured INTEGER,
    -- Whether the distribution, rather than the models, refused a Go Call (#15).
    --
    -- Deliberately a second column beside `go_call_withheld` rather than a widening of it.
    -- Both end in a Watch, and they are different facts about the world: the forecasters
    -- disagreeing about a swell is not the same as one forecast being too uncertain to book
    -- on. A single column would force a reader to guess which, and #11 scores them apart.
    go_call_withheld_for_uncertainty INTEGER
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
    "predicted_significant_wave_height, unit, amplification_model, calibrated, calibration, "
    "model_agreement, go_call_withheld, plausible_low_m, plausible_high_m, "
    "height_bar_probability, uncertainty_measured, go_call_withheld_for_uncertainty"
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


def _optional_flag(value: bool | None) -> int | None:
    """A boolean that may legitimately be absent, keeping absence distinct from `False`.

    The same distinction `_optional_json` protects, on the columns #15 added. A call decided
    without a distribution never asked whether the forecast was too uncertain to book on, and
    storing `0` for it would answer a question nobody put — which is exactly the reading
    `go_call_withheld`'s own docstring warns against one column up.
    """
    return None if value is None else int(value)


def _recent_calls_sql(dates: Collection[str], limit: int) -> tuple[str, tuple[Any, ...]]:
    """The succession query for a given set of dates, and its parameters.

    Split out from `recent_calls` so the *plan* is testable without duplicating the SQL in a
    test. What this ticket fixes is a physical property — whether SQLite walks the table —
    and asserting on a re-typed copy of the query would prove nothing about the one that runs.

    The date predicate sits **inside** the subquery, before the window. Outside it the
    `ROW_NUMBER()` would still be computed over every row and the filter would only discard
    the results, which is the shape being fixed. Placeholders rather than interpolation: the
    dates come from a provider's forecast, and this is the first variable-length collection in
    this store to reach SQL.
    """
    placeholders = ", ".join("?" for _ in dates)
    return (
        "SELECT * FROM (SELECT "
        f"{CALL_COLUMNS}, ROW_NUMBER() OVER (PARTITION BY date ORDER BY id DESC) AS recency "
        f"FROM day_call WHERE date IN ({placeholders})) "
        "WHERE recency <= ? ORDER BY date, recency DESC",
        (*dates, limit),
    )


def _range_columns(value: tuple[float, float] | list[float] | None) -> tuple[Any, Any]:
    """A plausible range as its two columns, or two nulls where there was no distribution.

    Split here rather than at the call site so the pair cannot be written half-present: a row
    carrying a low with no high would describe a range with one end, and nothing downstream
    would have a sensible reading for it.
    """
    if value is None:
        return None, None
    low, high = value
    return float(low), float(high)


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

        # #8's second half, nullable and not backfilled for the third time and the same
        # reason. A call issued before the Decision Model read Model Spread was decided
        # without consulting the other wave models; writing "agreed" onto it would assert an
        # agreement that was never established, on exactly the calls a reader would most want
        # to tell apart from the ones that were.
        if "model_agreement" not in columns:
            connection.execute("ALTER TABLE day_call ADD COLUMN model_agreement TEXT")
        if "go_call_withheld" not in columns:
            connection.execute("ALTER TABLE day_call ADD COLUMN go_call_withheld INTEGER")

        # #66 renames one of #15's columns, and this is the first migration here that
        # carries data instead of admitting there is none. The others are nullable and
        # not backfilled because the fact they record did not exist for older rows. This
        # one did exist: the quantity is unchanged — the share of the incoming reading's
        # draws clearing the height bar — and only the name was wrong, claiming all four
        # Gold Day conditions where one was measured. Adding a fresh column beside the old
        # one would split a single series in two at an arbitrary date, on the record #11
        # scores.
        #
        # Ordered before the add-column loop below so the renamed column is already
        # present when the loop checks, and guarded on the old name so a restart does not
        # try to rename a column that is no longer there.
        if "gold_day_probability" in columns:
            connection.execute(
                "ALTER TABLE day_call RENAME COLUMN gold_day_probability TO height_bar_probability"
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(day_call)")}

        # #15, nullable and not backfilled for the same reason as every column above it. A
        # call issued before the pipeline built distributions was decided on a point
        # estimate; computing a range for it today would use a profile, a fit and an
        # ensemble reading that were not what judged it, and would then sit in the record
        # looking exactly like one that had been.
        for column, kind in (
            ("plausible_low_m", "REAL"),
            ("plausible_high_m", "REAL"),
            ("height_bar_probability", "REAL"),
            ("uncertainty_measured", "INTEGER"),
            ("go_call_withheld_for_uncertainty", "INTEGER"),
        ):
            if column not in columns:
                connection.execute(f"ALTER TABLE day_call ADD COLUMN {column} {kind}")

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
                "amplification_model, calibrated, calibration, model_agreement, "
                "go_call_withheld, plausible_low_m, plausible_high_m, height_bar_probability, "
                "uncertainty_measured, go_call_withheld_for_uncertainty) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                        call["model_agreement"],
                        int(call["go_call_withheld"]),
                        *_range_columns(call.get("plausible_range_m")),
                        call.get("height_bar_probability"),
                        _optional_flag(call.get("uncertainty_measured")),
                        _optional_flag(call.get("go_call_withheld_for_uncertainty")),
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

    def recent_calls(
        self, dates: Collection[str], limit: int = 5
    ) -> dict[str, list[dict[str, Any]]]:
        """The last few calls made about each of `dates`, oldest first, keyed by date.

        #15's eighth criterion asks a user to see how a prediction has shifted across
        successive Pipeline Runs, and this is the record that answers it. `calls()` serves
        the newest call about each date and deliberately throws the rest away; the rest are
        exactly what "shifted" means.

        Ordered and windowed by `id` rather than `issued_at`, for the reason `calls()` gives
        at length: `issued_at` is a wall clock, and a clock adjusted backwards would reorder
        the succession of runs and draw a swell building when it was fading. Insertion order
        is the only total order the store has, and it is the order the runs happened in.

        Bounded twice, and both bounds are load-bearing (#67). `limit` bounds how many calls
        one date contributes, because this feeds a response a traveller reads and a fortnight
        of three-hourly runs puts more than a hundred behind a single date. `dates` bounds how
        much of the table is read at all: without it the window was computed over every call
        ever stored and all but the current forecast's fortnight discarded, so a request cost
        grew with the age of the store rather than the size of its answer. `day_call` is
        append-only by design (ADR 0005) and #11 scores it, so that only ever gets worse.

        Required rather than defaulted, because the safe default is the wrong one. An omitted
        argument meaning "every date" is exactly the unbounded read this removed, and it would
        come back the first time a caller forgot. `call_history` remains for anything that
        genuinely wants the whole record.
        """
        if not dates:
            return {}

        sql, parameters = _recent_calls_sql(dates, limit)
        rows = self._connect().execute(sql, parameters)
        history: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            history.setdefault(row["date"], []).append(self._call(row))
        return history

    def call_history(self) -> list[dict[str, Any]]:
        """Every call ever made, oldest first, including superseded ones.

        Ticket #11 scores Go Call precision from this record, and #16 summarises it for the
        track record endpoint — see `issued_summary`, which is what that endpoint reads.
        Like `raw_responses`, the full history is a deliberate narrow exception to the
        backend seam: retention across runs is required by ADR 0005 and there is nothing
        else that can observe it.
        """
        rows = self._connect().execute(f"SELECT run_id, {CALL_COLUMNS} FROM day_call ORDER BY id")
        # `run_id` is carried on the history rather than on `calls()` and `latest_call()`:
        # those two feed the API's responses, and which run produced a call is provenance
        # for whoever audits the record, not something a traveller reading a forecast has
        # any use for. When the track record gets an endpoint (#16), that can change.
        return [self._call(row) | {"date": row["date"], "run_id": row["run_id"]} for row in rows]

    def issued_summary(self) -> dict[str, Any]:
        """How much this installation has actually issued, and over what stretch.

        Counts only, and deliberately so: scoring a stored call means comparing it against
        an observation, and no buoy reading reaches the running system at all. Counting is
        the honest limit of what the retained record can say about itself.

        Lives here rather than in the API layer because it is a fact about the store's own
        rows, and because the ordering below is this class's knowledge to hold. `first` and
        `last` are the ends of insertion order, not of `issued_at` — `latest_call` documents
        why: two runs inside one second tie on `issued_at`, so the sequence the store
        appended in is the only total order it has. That is the same order `call_history`
        returns and the order the succession of calls about a date actually happened in.
        """
        row = (
            self._connect()
            .execute(
                """
            SELECT
                COUNT(*) AS calls_issued,
                COUNT(DISTINCT issued_for_date) AS dates_covered,
                SUM(CASE WHEN status = 'go' THEN 1 ELSE 0 END) AS go_calls_issued,
                (SELECT issued_at FROM day_call ORDER BY id LIMIT 1) AS first_issued_at,
                (SELECT issued_at FROM day_call ORDER BY id DESC LIMIT 1) AS last_issued_at
            FROM day_call
            """
            )
            .fetchone()
        )

        return {
            "calls_issued": row["calls_issued"],
            "dates_covered": row["dates_covered"],
            # SUM over no rows is NULL, not 0. Coerced here rather than left to the caller:
            # a null reaching the interface would render as "no Go Calls issued" only by
            # accident, and as a blank beside three real counts by default.
            "go_calls_issued": row["go_calls_issued"] or 0,
            # Left null on an empty store rather than substituted. A fresh installation has
            # no first call, and inventing a timestamp for one would make an empty record
            # read as a record.
            "first_issued_at": row["first_issued_at"],
            "last_issued_at": row["last_issued_at"],
        }

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
            "model_agreement": row["model_agreement"],
            # None-preserving, like `calibration` and `model_agreement` above. A null
            # here means the call predates the gate; collapsing it to False would report
            # "the models did not withhold this" about a call that never asked them.
            "go_call_withheld": (
                None if row["go_call_withheld"] is None else bool(row["go_call_withheld"])
            ),
            # None-preserving in both halves, and the pair travels together. A call written
            # before the pipeline built distributions has no range, which is a different
            # thing from a range of zero width.
            "plausible_range_m": (
                None
                if row["plausible_low_m"] is None or row["plausible_high_m"] is None
                else (row["plausible_low_m"], row["plausible_high_m"])
            ),
            "height_bar_probability": row["height_bar_probability"],
            "uncertainty_measured": (
                None if row["uncertainty_measured"] is None else bool(row["uncertainty_measured"])
            ),
            "go_call_withheld_for_uncertainty": (
                None
                if row["go_call_withheld_for_uncertainty"] is None
                else bool(row["go_call_withheld_for_uncertainty"])
            ),
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

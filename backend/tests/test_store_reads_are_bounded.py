"""What a forecast request costs the store, as the record grows underneath it.

Ticket #67. `day_call` is append-only by design (ADR 0005) and #11 scores it, so it only
ever gets bigger — roughly 16 runs a day across 14 dates, about 80,000 rows a year. Nothing
in the serving path may be written so that its cost tracks the age of the store rather than
the size of the answer.

The defect these tests pin is not a wrong answer. `recent_calls` returned exactly the right
succession; it just computed a window over every call ever stored and then discarded all but
the fortnight the forecast asked about. That is invisible on a young store and never becomes
visible as a bug — only as a page that gets slower every month.
"""

from __future__ import annotations

import sqlite3

from nazarenow.store import Store, _recent_calls_sql


def call_row(date: str, height: float) -> tuple:
    return (
        date,
        "2026-02-09T06:00",
        "2026-02-09",
        "watch",
        4,
        "[]",
        height,
        "m",
        "learned-amplification",
        1,
    )


def store_with(tmp_path, dates: list[str], runs: int = 3) -> Store:
    """A store carrying `runs` calls about each of `dates`, written oldest first."""
    store = Store(tmp_path / "bounded.db")
    connection = store._connect()  # noqa: SLF001
    for run in range(runs):
        connection.executemany(
            "INSERT INTO day_call (date, issued_at, issued_for_date, status, lead_time_days, "
            "reasons, predicted_significant_wave_height, unit, amplification_model, calibrated) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [call_row(date, 3.0 + run) for date in dates],
        )
    connection.commit()
    return store


class TestTheSuccessionQueryCostsWhatItServes:
    def test_it_searches_the_index_rather_than_scanning_the_table(self, tmp_path) -> None:
        """The whole ticket, in one assertion.

        A `ROW_NUMBER() OVER (PARTITION BY date ...)` with no predicate under it makes SQLite
        walk `day_call` end to end before the recency filter can throw anything away. The
        `day_call_date` index already existed and could not help, because there was nothing
        to search it *for* — the fix is the date predicate, not the index.
        """
        store = store_with(tmp_path, ["2026-02-12", "2026-02-13", "2026-02-14"])
        try:
            sql, parameters = _recent_calls_sql(["2026-02-12", "2026-02-13"], limit=5)
            plan = " ".join(
                row["detail"]
                for row in store._connect().execute(  # noqa: SLF001
                    f"EXPLAIN QUERY PLAN {sql}", parameters
                )
            )

            assert "SEARCH day_call" in plan, f"the query still walks the table: {plan}"
            assert "SCAN day_call" not in plan, f"the query still walks the table: {plan}"
        finally:
            store.close()

    def test_it_returns_only_the_dates_it_was_asked_about(self, tmp_path) -> None:
        store = store_with(tmp_path, ["2026-02-12", "2026-02-13", "2026-02-14"])
        try:
            got = store.recent_calls(["2026-02-12", "2026-02-14"])

            assert sorted(got) == ["2026-02-12", "2026-02-14"]
        finally:
            store.close()

    def test_asking_about_no_dates_reads_nothing(self, tmp_path) -> None:
        """An empty forecast is a legitimate state, and it must not mean "every date".

        A falsy `dates` collapsing to the unrestricted query is the classic version of this
        bug: correct output, and the one caller that could have bounded it no longer does.
        """
        store = store_with(tmp_path, ["2026-02-12", "2026-02-13"])
        try:
            assert store.recent_calls([]) == {}
        finally:
            store.close()

    def test_bounding_the_dates_changes_no_answer(self, tmp_path) -> None:
        """The succession for a date must be identical either way.

        This is the regression that would matter to a reader: #15's eighth criterion draws
        how a prediction moved between runs, and a window computed over a narrower set of
        rows must still produce the same ordering and the same members.
        """
        dates = ["2026-02-12", "2026-02-13", "2026-02-14"]
        store = store_with(tmp_path, dates, runs=4)
        try:
            everything = store.recent_calls(dates)
            just_one = store.recent_calls(["2026-02-13"])

            assert just_one["2026-02-13"] == everything["2026-02-13"]
        finally:
            store.close()

    def test_it_still_bounds_how_many_calls_a_date_contributes(self, tmp_path) -> None:
        """The date predicate must not have quietly replaced the recency window.

        A fortnight of three-hourly runs puts more than a hundred calls behind one date, and
        this feeds a response a traveller reads.
        """
        store = store_with(tmp_path, ["2026-02-12"], runs=9)
        try:
            got = store.recent_calls(["2026-02-12"], limit=3)

            assert len(got["2026-02-12"]) == 3
        finally:
            store.close()

    def test_the_newest_call_is_last(self, tmp_path) -> None:
        """Oldest first, which is what the interface draws left to right."""
        store = store_with(tmp_path, ["2026-02-12"], runs=3)
        try:
            heights = [
                call["predicted_significant_wave_height"]
                for call in store.recent_calls(["2026-02-12"])["2026-02-12"]
            ]

            assert heights == sorted(heights), "the succession must read oldest first"
        finally:
            store.close()


def test_the_query_parameterises_its_dates(tmp_path) -> None:
    """Built with placeholders, never interpolated.

    The date list is the first thing in this store to reach SQL from a variable-length
    collection, and `IN (...)` is where that is usually got wrong.
    """
    sql, parameters = _recent_calls_sql(["2026-02-12", "2026-02-13"], limit=5)

    assert "2026-02-12" not in sql
    assert list(parameters[:2]) == ["2026-02-12", "2026-02-13"]
    # And it is valid SQL against a real schema, not merely well-formed-looking.
    store = Store(tmp_path / "parameterised.db")
    try:
        store._connect().execute(sql, parameters).fetchall()  # noqa: SLF001
    finally:
        store.close()


def test_a_date_carrying_a_quote_cannot_break_the_query(tmp_path) -> None:
    """Dates come from `group_by_date` and are well-formed today, which is not a guarantee."""
    store = Store(tmp_path / "quoted.db")
    try:
        assert store.recent_calls(["2026-02-12'; DROP TABLE day_call; --"]) == {}
        assert (
            store._connect()  # noqa: SLF001
            .execute("SELECT count(*) AS n FROM day_call")
            .fetchone()["n"]
            == 0
        ), "the table is gone"
    except sqlite3.Error as error:  # pragma: no cover - the failure this guards against
        raise AssertionError(f"a quoted date reached SQL unescaped: {error}") from error
    finally:
        store.close()

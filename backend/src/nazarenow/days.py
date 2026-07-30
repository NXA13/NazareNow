"""Grouping forecast hours into the days a user actually reasons about.

Both the Pipeline Run and the API need the same grouping — one to decide a call per day,
the other to summarise a day for display — and they must agree on where a day starts. Two
copies of the same three lines would drift apart silently: a run deciding calls on one
grouping while the API showed another produces a page whose advice belongs to a different
day from the hours beneath it.

Days are the provider's, in UTC, matching how the interface labels its hourly table.
"""

from __future__ import annotations

from typing import Any


def group_by_date(hours: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Forecast hours keyed by their date, each day's hours in the order given."""
    by_date: dict[str, list[dict[str, Any]]] = {}
    for hour in hours:
        by_date.setdefault(hour["at"][:10], []).append(hour)
    return by_date

"""Grouping forecast hours into the days a user actually reasons about.

Both the Pipeline Run and the API need the same grouping — one to decide a call per day,
the other to summarise a day for display — and they must agree on where a day starts. Two
copies of the same three lines would drift apart silently: a run deciding calls on one
grouping while the API showed another produces a page whose advice belongs to a different
day from the hours beneath it.

Days are Nazaré local days (Europe/Lisbon), matching how the interface labels its hourly
table and, more importantly, matching the day a traveller stands on the beach.

The timestamps arrive already local because the Pipeline Run asks the provider for that
zone and checks it got it (`open_meteo.TIMEZONE`), so slicing the date off the front of a
stamp is correct by construction rather than by a conversion each reader must remember.
Grouping UTC stamps put an hour of every summer-time day on the wrong date — about 28 days
of each Big-Wave Season, 25 of them in early October. See ADR 0008.
"""

from __future__ import annotations

from typing import Any


def group_by_date(hours: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Forecast hours keyed by their date, each day's hours in the order given."""
    by_date: dict[str, list[dict[str, Any]]] = {}
    for hour in hours:
        by_date.setdefault(hour["at"][:10], []).append(hour)
    return by_date

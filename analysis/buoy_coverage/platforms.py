"""The instruments this analysis concerns.

Defined once and imported, because the download and analysis steps previously each
carried their own copy and had already drifted apart — one still described Monican02
as beginning in 2018, a figure the analysis had already disproved.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Platform:
    code: str
    name: str
    note: str


MONICAN01 = Platform(
    code="6200192",
    name="Monican01",
    note="~55 km offshore in deep water. Long record, but measures approximately the "
         "open-ocean swell forecast providers already supply as an input.",
)

MONICAN02 = Platform(
    code="6200199",
    name="Monican02",
    note="~15 km offshore, near the canyon head. Its readings carry the local "
         "Amplification the project exists to learn.",
)

PLATFORMS: tuple[Platform, ...] = (MONICAN01, MONICAN02)

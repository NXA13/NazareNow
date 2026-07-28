"""Find the MONICAN buoys and record what EMODnet claims about them.

This runs first and needs no credentials. It answers "what instruments exist near
Praia do Norte, and what does the catalogue say they recorded?" — which is not the
same question as "what data can we actually get", answered by download_observations.py.

The distinction matters: EMODnet's catalogue advertises a longer and tidier record
than its download endpoints will actually serve.
"""

from __future__ import annotations

import csv
import io
import sys
import urllib.request
from pathlib import Path

# EMODnet Physics publishes a catalogue of every observing platform it knows about.
# We query it rather than hardcoding what we found by hand, so this stays true if
# the buoys are moved, replaced or joined by others.
CATALOGUE_URL = "https://erddap.emodnet-physics.eu/erddap/tabledap/EP_PLATFORMS_METADATA_V2.csv"

FIELDS = [
    "PLATFORMCODE",
    "call_name",
    "latitude",
    "longitude",
    "firstdateobservation",
    "lastdateobservation",
    "parameters",
    "dataownername",
    "platformtypedescription",
]

# A box covering the sea off Nazaré. Praia do Norte is at roughly 39.60N, 9.08W;
# this reaches far enough west to catch deep-water moorings.
LAT_MIN, LAT_MAX = 39.0, 40.3
LON_MIN, LON_MAX = -10.6, -8.6

OUTPUT = Path(__file__).parent / "output" / "platforms_near_nazare.csv"


def catalogue_url() -> str:
    """Build an ERDDAP query: comma-separated variables, then one constraint each.

    ERDDAP wants the comparison operators percent-encoded but leaves commas and
    equals signs alone, which is why this is assembled by hand rather than with
    urlencode.
    """
    variables = ",".join(FIELDS)
    constraints = [
        f"latitude>={LAT_MIN}",
        f"latitude<={LAT_MAX}",
        f"longitude>={LON_MIN}",
        f"longitude<={LON_MAX}",
    ]
    encoded = "&".join(c.replace(">", "%3E").replace("<", "%3C") for c in constraints)
    return f"{CATALOGUE_URL}?{variables}&{encoded}"


def main() -> int:
    print(f"Querying EMODnet catalogue for platforms in "
          f"{LAT_MIN}-{LAT_MAX}N, {abs(LON_MAX)}-{abs(LON_MIN)}W")

    request = urllib.request.Request(catalogue_url(), headers={"User-Agent": "NazareNow/0.1"})
    with urllib.request.urlopen(request, timeout=120) as response:
        body = response.read().decode("utf-8")

    rows = list(csv.DictReader(io.StringIO(body)))
    # ERDDAP puts a units row immediately after the header. It is not data.
    rows = [row for row in rows if row["PLATFORMCODE"]]

    # VHM0 is Significant Wave Height. A platform without it cannot serve as a
    # Proxy Target no matter how long its record is.
    wave_platforms = [row for row in rows if "VHM0" in (row["parameters"] or "")]

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(wave_platforms)

    print(f"\n{len(rows)} platforms in the box, {len(wave_platforms)} reporting "
          f"Significant Wave Height:\n")
    for row in sorted(wave_platforms, key=lambda r: r["firstdateobservation"]):
        print(f"  {row['PLATFORMCODE']:>10}  {row['call_name'][:22]:<22} "
              f"{float(row['latitude']):.2f}N {abs(float(row['longitude'])):.2f}W  "
              f"{row['firstdateobservation'][:10]} -> {row['lastdateobservation'][:10]}")

    print(f"\nWritten to {OUTPUT.relative_to(Path.cwd()) if OUTPUT.is_relative_to(Path.cwd()) else OUTPUT}")
    print("\nNote: these dates are the catalogue's claim about the span of the record.")
    print("They say nothing about gaps inside it. That is what analyse_coverage.py is for.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

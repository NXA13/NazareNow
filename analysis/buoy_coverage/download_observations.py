"""Download the MONICAN buoy records from Copernicus Marine.

EMODnet advertises these files but no longer serves them — every download URL in
its own catalogue returns 404. The data originates from the Copernicus Marine
In Situ TAC ("INSTAC" in the dead EMODnet paths), which still has it.

Requires a free Copernicus Marine account. Log in once with:

    .venv/Scripts/copernicusmarine.exe login

That stores a credentials file in your home directory; this script never sees or
handles your password.
"""

from __future__ import annotations

import sys
from pathlib import Path

import copernicusmarine

from platforms import PLATFORMS, Platform

# In-situ observations for the Iberia-Biscay-Ireland region, which includes the
# Portuguese coast. This one product carries both the historical record and the
# near-real-time feed.
DATASET_ID = "cmems_obs-ins_ibi_phybgcwav_mynrt_na_irr"

# The dataset is split into parts, and the default is "latest" — the last 30 days
# only. That is a trap: a download that looks successful returns a month of data.
# "history" holds the full record as one file per platform.
DATASET_PART = "history"

DESTINATION = Path(__file__).resolve().parents[2] / "data" / "raw" / "buoy"


def download(platform: Platform) -> int:
    print(f"\n--- {platform.name} ({platform.code}) ---")
    result = copernicusmarine.get(
        dataset_id=DATASET_ID,
        dataset_part=DATASET_PART,
        filter=f"*{platform.code}*",
        output_directory=str(DESTINATION),
        no_directories=True,
        overwrite=True,
    )
    if result is None or not result.files:
        print(f"  no files matched *{platform.code}*")
        return 0
    for file in result.files:
        print(f"  {file.filename}")
    return len(result.files)


def main() -> int:
    DESTINATION.mkdir(parents=True, exist_ok=True)
    print(f"Downloading to {DESTINATION}")

    total = 0
    for platform in PLATFORMS:
        try:
            total += download(platform)
        except Exception as error:  # noqa: BLE001 — report and continue to the next platform
            print(f"  FAILED: {type(error).__name__}: {error}")

    if total == 0:
        print("\nNothing downloaded. If you were prompted for a username, run:")
        print("  .venv/Scripts/copernicusmarine.exe login")
        return 1

    print(f"\n{total} files downloaded. Next: analyse_coverage.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())

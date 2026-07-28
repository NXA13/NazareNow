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

# In-situ observations for the Iberia-Biscay-Ireland region, which includes the
# Portuguese coast. This one product carries both the historical record and the
# near-real-time feed.
DATASET_ID = "cmems_obs-ins_ibi_phybgcwav_mynrt_na_irr"

# The dataset is split into parts, and the default is "latest" — the last 30 days
# only. That is a trap: a download that looks successful returns a month of data.
# "history" holds the full record as one file per platform.
DATASET_PART = "history"

# Discovered by discover_platforms.py. Monican01 has the long record but sits ~55km
# offshore in deep water; Monican02 is near the canyon but starts in 2018. We pull
# both, because deciding between them is the point of this analysis.
PLATFORMS = {
    "6200192": "Monican01",
    "6200199": "Monican02",
}

DESTINATION = Path(__file__).resolve().parents[2] / "data" / "raw" / "buoy"


def download(platform_code: str, name: str) -> int:
    print(f"\n--- {name} ({platform_code}) ---")
    result = copernicusmarine.get(
        dataset_id=DATASET_ID,
        dataset_part=DATASET_PART,
        filter=f"*{platform_code}*",
        output_directory=str(DESTINATION),
        no_directories=True,
        overwrite=True,
    )
    if result is None or not result.files:
        print(f"  no files matched *{platform_code}*")
        return 0
    for file in result.files:
        print(f"  {file.filename}")
    return len(result.files)


def main() -> int:
    DESTINATION.mkdir(parents=True, exist_ok=True)
    print(f"Downloading to {DESTINATION}")

    total = 0
    for code, name in PLATFORMS.items():
        try:
            total += download(code, name)
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

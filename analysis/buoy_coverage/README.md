# Buoy coverage analysis

Ticket [#2](https://github.com/NXA13/NazareNow/issues/2).

ADR 0002 makes buoy Significant Wave Height the Proxy Target for the whole project,
on the assumption that the record is substantially complete from 2009. This analysis
tests that assumption before any application code depends on it.

## Running it

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r analysis/buoy_coverage/requirements.txt

# 1. Which instruments exist near Praia do Norte? No credentials needed.
.venv/Scripts/python.exe analysis/buoy_coverage/discover_platforms.py

# 2. Download their records. Needs a free Copernicus Marine account:
#    register at https://data.marine.copernicus.eu/register
.venv/Scripts/python.exe -m copernicusmarine login
.venv/Scripts/python.exe analysis/buoy_coverage/download_observations.py

# 3. Measure what is actually there.
.venv/Scripts/python.exe analysis/buoy_coverage/analyse_coverage.py
```

Raw downloads land in `data/raw/buoy/` and are gitignored — they are large and
reproducible. Results land in `output/` and are committed, because the finding is
the deliverable.

## Findings

### 1. ADR 0002 describes a buoy that does not exist

There are two MONICAN moorings, and ADR 0002's description merges them:

| | Monican01 (`6200192`) | Monican02 (`6200199`) |
|---|---|---|
| Position | 39.51°N, 9.64°W | 39.56°N, 9.21°W |
| Distance offshore | ~55 km | ~15 km |
| Record begins | 2009-04-27 | 2018-01-01 |
| Record ends | 2025-10-01 | ongoing |

ADR 0002 says *"the MONICAN buoy, in 90m of water near the canyon, has recorded
Significant Wave Height hourly since 2009."* No single instrument matches that. The
buoy with the long record is 55 km offshore in deep water; the buoy near the canyon
begins in 2018.

This matters because the two are not interchangeable as a Proxy Target:

- **Monican02** is the meaningful target. It sits near the canyon head, so its
  readings reflect local Amplification — the thing the project exists to learn. But
  it yields roughly **eight winters, not seventeen**.
- **Monican01** has the longer record, but 55 km offshore in deep water it measures
  approximately the same open-ocean swell that the forecast providers already supply
  as an *input*. Training a model to predict it would largely be training a model to
  predict its own inputs.

Monican01 also stopped reporting on 2025-10-01 and may have been lost.

### 2. EMODnet no longer serves the data it advertises

The retrieval route named in the ticket does not work. EMODnet's platform metadata
gives file URLs under `/erddap/files/TS_VHM0_INSTAC/<platform>/`, and every one
returns 404 across all four of their ERDDAP hosts (`erddap`, `er2webapps`,
`er3webapps`, `prod-erddap`). The datasets are absent from EMODnet's own catalogue
and from IFREMER's mirror.

The `INSTAC` in those paths identifies the origin: the Copernicus Marine In Situ TAC,
which still serves the data as product `INSITU_IBI_PHYBGCWAV_DISCRETE_MYNRT_013_033`,
dataset `cmems_obs-ins_ibi_phybgcwav_mynrt_na_irr`. It is free but requires an
account, so `download_observations.py` targets Copernicus rather than EMODnet.

EMODnet metadata is still used for discovery, which does work.

### 3. Coverage and gaps

_Pending — requires the download in step 2. `analyse_coverage.py` produces
`output/coverage.png` and `output/coverage_by_year.csv`, and this section records
what they show: usable hours per year, usable days during the October–March
big-wave season, changes in position or reporting cadence, and which wave variables
can be relied on._

## Verdict on ADR 0002

_Pending the coverage numbers. Finding 1 alone means ADR 0002 needs correcting on a
point of fact regardless of what the coverage shows._

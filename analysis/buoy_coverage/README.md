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
.venv/Scripts/copernicusmarine.exe login
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
| Record | 2009-04-27 → 2025-10-01 | 2010-06-12 → ongoing |
| Readings | 87,530 | 78,456 |
| Cadence | hourly | hourly |
| Position drift | none detected | none detected |
| Highest Hs recorded | 12.71 m | 14.00 m |

ADR 0002 says *"the MONICAN buoy, in 90m of water near the canyon, has recorded
Significant Wave Height hourly since 2009."* No single instrument matches that. The
buoy with the record back to 2009 is 55 km offshore in deep water; the one near the
canyon is a different mooring.

The two are not interchangeable as a Proxy Target. **Monican02** is the meaningful
one — near the canyon head, so its readings carry the local Amplification the project
exists to learn. **Monican01**, 55 km offshore in deep water, measures approximately
the open-ocean swell that forecast providers already supply as an *input*; training a
model to predict it would largely mean predicting its own inputs.

Monican01 stopped reporting on 2025-10-01 and may have been lost.

**Correction to an earlier reading of this.** EMODnet's catalogue reports Monican02
as beginning 2018-01-01. The downloaded record begins **2010-06-12**. An intermediate
version of this finding claimed the project had "eight winters, not seventeen" — that
was wrong, and it came from trusting catalogue metadata instead of the data. Both
buoys span roughly sixteen years.

### 2. Coverage is substantial but severely uneven

Neither buoy runs continuously. Usable hours per year swing between 13% and 97%, and
outages last months rather than days — see `output/coverage.png`, where blank and dark
cells are gaps.

Counting only the October–March big-wave season, and only days where the buoy reported
for at least 75% of hours:

| | Usable winter days |
|---|---|
| Monican01 | 1,733 |
| Monican02 | 1,683 |
| Both on the same day | 1,101 |
| **Either buoy** | **2,315** |

The gaps are largely uncorrelated — 632 winter days have only Monican01 and 582 have
only Monican02 — so the two moorings partially cover for each other.

Some winters are effectively lost. Monican02 recorded 8.2% of winter 2013 and 28.2% of
winter 2024; Monican01 recorded 10.6% of winter 2020. Any evaluation split by season
must account for this rather than assuming even coverage.

Where the buoys do report, the data is good: quality-control flags reject only ~0.05%
of readings, cadence is a stable 60 minutes throughout, and neither mooring has moved.

### 3. Wave variables are reliably present

Percentage of readings carrying each variable, after quality control:

| Variable | | Monican01 | Monican02 |
|---|---|---|---|
| `VHM0` | significant wave height | 99.9% | 97.6% |
| `VTPK` | peak period | 96.1% | 99.8% |
| `VTM02` | mean period | 95.4% | 99.9% |
| `VMDR` | mean direction | 94.1% | 93.5% |
| `VPED` | direction at peak period | 92.4% | 99.9% |
| `VZMX` | maximum wave height | 96.3% | 99.8% |

Nothing here is intermittent. When a buoy is reporting, it reports everything. The
risk is whole-outage, not partial records.

### 4. The buoys do capture big days — but Hs predicts Face Height poorly

Significant Wave Height recorded on days independently known to have been giant:

| Date | Event | Monican01 | Monican02 |
|---|---|---|---|
| 2011-11-01 | McNamara 78 ft world record | 5.27 m | 3.92 m |
| 2013-10-28 | McNamara ~100 ft claim | missing | missing |
| 2017-11-08 | Koxa 80 ft world record | 5.46 m | 5.77 m |
| 2018-01-18 | Gabeira record swell | 8.41 m | 8.69 m |
| 2020-10-29 | Laureano 101 ft claim | missing | 8.72 m |
| 2024-01-22 | Tudor Big Wave Challenge | 5.02 m | 5.24 m |
| 2025-02-18 | Tudor Big Wave Challenge | missing | 4.69 m |
| 2025-12-13 | Tudor Big Wave Challenge | missing | 7.78 m |

Eight of nine are captured by at least one buoy, and the two cover for each other on
four of them. Only 2013-10-28 is missing from both.

The more important observation is the spread. McNamara's 78 ft record came on 5.27 m,
Koxa's 80 ft on 5.46 m, while 2018-01-18 produced 8.41 m — over 50% more Significant
Wave Height — without a comparable headline wave. **Hs alone does not determine Face
Height.** Period, direction and who happened to be in the water all matter.

This is direct evidence for the caveat ADR 0002 already carries, and it sets the
expectation for the Gold Day calibration in #12: a single threshold on predicted Hs
will be noisy, and the honest output is a probability rather than a height.

_These dates were assembled quickly for a sanity check and are not the curated Gold
Day set. One candidate date initially included, a 2022 contest, returned 1.45 m —
almost certainly a wrong date on my part rather than a wrong reading, and a reminder
that #10 needs sourced dates rather than recalled ones._

### 5. EMODnet no longer serves the data it advertises

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

A second trap in the replacement route: the Copernicus dataset is split into parts,
and the default part is `latest` — the most recent 30 days only. A download that
looks entirely successful returns one month of data. The full record is in the
`history` part, which is what `download_observations.py` requests.

## Verdict on ADR 0002

**The strategy holds. The ADR's facts do not.**

ADR 0002 must be corrected: there are two moorings, the one near the canyon is
Monican02, and the retrieval route is Copernicus rather than EMODnet. Those are
factual repairs, not a change of direction.

The underlying decision — train on buoy Significant Wave Height as a Proxy Target,
calibrate against Gold Days — survives, and survives better than the intermediate
reading of this analysis suggested. Monican02 alone offers 1,683 usable winter days
across sixteen seasons, and it captures the big days when it is running.

Two qualifications belong in the revised ADR:

1. **Coverage is uneven enough to matter.** Whole winters are effectively absent.
   Evaluation splits must be made on what was actually recorded, and reporting
   "sixteen years of data" without qualification would be misleading.
2. **The Hs-to-Face-Height relationship is loose**, as finding 4 shows directly. This
   was already acknowledged in the ADR as a caveat; it should be stated as a measured
   property rather than a suspicion.

Recommended: adopt **Monican02** as the Proxy Target. Monican01 is worth retaining,
not as a target but as a measured offshore input and a gap-filler — it independently
covers 632 winter days that Monican02 missed.

Tracked in [#17](https://github.com/NXA13/NazareNow/issues/17).

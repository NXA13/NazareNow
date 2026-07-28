# Buoy coverage analysis

Ticket [#2](https://github.com/NXA13/NazareNow/issues/2).

ADR 0002 makes buoy Significant Wave Height the Proxy Target for the whole project,
on the assumption that the record is substantially complete from 2009. This analysis
tests that assumption before any application code depends on it.

## Running it

Paths below are Windows. On macOS or Linux the interpreter is `.venv/bin/python` and
the CLI is `.venv/bin/copernicusmarine`; nothing else differs.

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r analysis/buoy_coverage/requirements.txt

# 1. Which instruments exist near Praia do Norte? No credentials needed.
.venv/Scripts/python.exe analysis/buoy_coverage/discover_platforms.py

# 2. Download their records. Needs a free Copernicus Marine account:
#    register at https://data.marine.copernicus.eu/register
#    Run the login in a real terminal — it prompts, so it cannot be piped.
.venv/Scripts/copernicusmarine.exe login
.venv/Scripts/python.exe analysis/buoy_coverage/download_observations.py

# 3. Measure what is actually there. Run from inside this directory,
#    which is on the import path for platforms.py.
cd analysis/buoy_coverage && ../../.venv/Scripts/python.exe analyse_coverage.py
```

Raw downloads land in `data/raw/buoy/` and are gitignored — they are large and
reproducible. Results land in `output/` and are committed, because the finding is the
deliverable:

| File | |
|---|---|
| `coverage.png` | monthly gap grid and coverage per Big-Wave Season |
| `coverage_by_season.csv` | per-season hours, coverage and Usable Days |
| `joint_coverage.csv` | what the two moorings cover together |
| `candidate_xxl_day_readings.csv` | Hs on provisional XXL Days |
| `platforms_near_nazare.csv` | what the EMODnet catalogue claims |

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

### 2. Whole seasons are missing, not just days

Coverage is counted per **Big-Wave Season** — October to March, named by the year it
begins in — because a season is the unit that matters and it is not a calendar year.
A **Usable Day** is one where the instrument reported for at least three quarters of
its hours. Denominators are the hours the season actually contains, not the span the
instrument happened to report over.

**Five seasons are effectively dead:**

| Buoy | Seasons recorded | Effectively lost (<5%) |
|---|---|---|
| Monican01 | 17 | 2013/14, 2020/21, 2025/26 |
| Monican02 | 16 | 2013/14, 2016/17 |

Monican01's 2025/26 is dead because the mooring stopped on 2025-10-01, one day into
the season.

Of Monican02's 16 seasons: **9 exceed 50% coverage, 5 are weak** (2010/11, 2012/13,
2021/22, 2024/25, 2025/26 all sit between 16% and 37%), and **2 recorded nothing at
all**. Any evaluation split must be made on what was actually recorded — treating this
as sixteen equivalent seasons would be wrong.

Counting Usable Days across the Big-Wave Season:

| | Usable Days |
|---|---|
| Monican01 | 1,733 |
| Monican02 | 1,683 |
| Both on the same day | 1,101 |
| Only Monican01 | 632 |
| Only Monican02 | 582 |
| **Either buoy** | **2,315** |

The outages are largely uncorrelated, so the two moorings partially cover for each
other — 2013/14 is the only season both lost.

Where the buoys do report, the data is clean. Quality control rejects 0.026% of
Monican01's readings and 0.047% of Monican02's. 99.8% of reporting intervals are
exactly 60 minutes for both; the remainder are outage gaps rather than irregular
sampling, the longest running 448 and 488 days respectively.

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

**What cannot be established.** Criterion 4 of the ticket asked for changes in
instrument, position and reporting cadence. Cadence and position are answered above.
**Instrument changes are not answerable from this source at all** — the files carry no
sensor model, serial number or deployment record, so a swapped instrument would be
invisible. The nearest available proxy is the data-mode flag, and both buoys show a
mix of real-time and delayed-mode processing across their records.

Position is likewise weaker than it first appears: coordinates are stored to 0.01°,
roughly 1.1 km. Each buoy reports a single distinct position throughout, which
establishes that neither was relocated substantially — not that neither ever moved.

### 4. The buoys do capture XXL Days — but Hs predicts Face Height poorly

**This section is provisional and answers no acceptance criterion.** It was a sanity
check on whether the buoys report at all when Praia do Norte goes giant, and the dates
in `candidate_xxl_days.csv` are recalled and spot-checked rather than systematically
sourced. Issue #10 supersedes it. It is kept because what it shows changes how #12
should be approached.

Significant Wave Height recorded on candidate XXL Days:

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

_One date initially included, a 2022 contest, returned 1.45 m — almost certainly a
wrong date rather than a wrong reading. It was removed, and it is the reason #10 needs
sourced dates rather than recalled ones._

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
calibrate against Gold Days — survives. Monican02 offers 1,683 Usable Days, and it
reports on the days Praia do Norte is known to have gone giant.

Three qualifications belong in the revised ADR:

1. **Fourteen usable seasons, not sixteen.** Monican02 recorded nothing in 2013/14 or
   2016/17, and five further seasons sit under 40%. Evaluation splits must be made on
   what was actually recorded; "sixteen years of data" would be misleading.
2. **The Hs-to-Face-Height relationship is loose**, as finding 4 shows directly. This
   was already a caveat in the ADR; it should now be stated as a measured property.
3. **Instrument changes cannot be ruled out.** The source carries no sensor metadata,
   so an undetected instrument swap remains a live risk to the record's consistency.

Recommended: adopt **Monican02** as the Proxy Target. Monican01 is worth retaining,
not as a target but as a measured offshore input and a gap-filler — it independently
covers 632 Usable Days that Monican02 missed, and 2013/14 is the only season both lost.

Tracked in [#17](https://github.com/NXA13/NazareNow/issues/17).

## Review corrections

This analysis was reviewed on both a standards and a spec axis, and two findings
changed the numbers rather than merely the prose:

- **Seasons were being grouped by calendar year**, which split every Big-Wave Season
  across two rows. The committed table showed Monican02's 2016 as 33.4% coverage; that
  figure was January–March 2016, belonging to the *previous* season. The 2016/17 season
  recorded nothing at all. Two dead seasons were hidden this way.
- **Coverage used the observed span as its denominator** rather than the calendar
  period, which flattered partial years. Monican01's 2025 was reported as 87.8% despite
  the mooring dying on 1 October; against the season it is 0.3%.

Both inflated the headline result. The joint-coverage figures and the candidate XXL Day
table were also being computed by hand outside any committed script, and are now
produced by `analyse_coverage.py` so they regenerate.

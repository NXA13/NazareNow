# Can Copernicus WAVERYS extend the Swell record before 2022?

Run `.venv/Scripts/python.exe analysis/waverys/verify_waverys.py` to reproduce. **No credentials
needed** — everything below is catalogue metadata, product documentation, and two public static
mask files. Downloading the wave data itself is the only step that needs a Copernicus account,
and this note does not take it.

Ticket #36. Short answer: **yes**, and the ticket's premise turns out to be slightly too modest —
there is a second Copernicus reanalysis that is better for Nazaré than WAVERYS on every axis that
matters here.

## Finding 1 — WAVERYS carries a real Swell partition, and splits it into two swell trains

This is the question everything else hangs on, and it is settled. `cmems_mod_glo_wav_my_0.2deg_PT3H-i`
(version 202411) carries 17 variables, six of which are Swell partitions distinct from the Combined
Sea:

| Variable | Units | CF standard name |
|---|---|---|
| **`VHM0_SW1`** | m | `sea_surface_primary_swell_wave_significant_height` |
| **`VTM01_SW1`** | s | `sea_surface_primary_swell_wave_mean_period` |
| **`VMDR_SW1`** | degree | `sea_surface_primary_swell_wave_from_direction` |
| **`VHM0_SW2`** | m | `sea_surface_secondary_swell_wave_significant_height` |
| **`VTM01_SW2`** | s | `sea_surface_secondary_swell_wave_mean_period` |
| **`VMDR_SW2`** | degree | `sea_surface_secondary_swell_wave_from_direction` |

Wind sea is separated too (`VHM0_WW`, `VTM01_WW`, `VMDR_WW`), and the Combined Sea keeps its own
unsuffixed variables (`VHM0`, `VMDR`, `VTM02`, `VTM10`, `VTPK`, `VPED`). Height, period *and*
direction, for a primary and a secondary swell train, on the same grid and the same time axis.

Sources: `copernicusmarine describe --product-id GLOBAL_MULTIYEAR_WAV_001_032 --return-fields all`,
reproduced by `verify_waverys.py`; and the [PUM, CMEMS-GLO-PUM-001-032 Issue 1.6, February
2026](https://documentation.marine.copernicus.eu/PUM/CMEMS-GLO-PUM-001-032.pdf), § 2d, which lists
every variable with its long name and standard name. The suffix convention — `_WW` wind wave, `_SW1`
primary swell, `_SW2` secondary swell, no suffix for the total spectrum — is stated by Copernicus
[here](https://help.marine.copernicus.eu/en/articles/6175153-how-to-describe-wave-height-period-and-direction-parameters).

**Two things this is not.** First, `VTM01_SW1` is a *mean* period — spectral moments (0,1) — not a
peak period. WAVERYS publishes a peak period, `VTPK`, but only for the **total spectrum**; there is
no per-partition peak period in the product. Second, "Swell" here arrives as two trains rather than
one. Both matter for comparability with what the pipeline currently reads, and finding 6 deals with
them.

## Finding 2 — the nearest grid point is 4.5 km from the Proxy Target, and it is water

The Proxy Target is Monican02 at **39.56°N, 9.21°W** (`backend/src/nazarenow/sources/open_meteo.py`;
position corroborated in `analysis/buoy_coverage/README.md`). WAVERYS runs on a regular 1/5° grid,
1800 × 899 nodes, 180°W–179.8°E and 89.8°S–89.8°N (PUM § 2b), so the nearest node is **39.6000,
−9.2000**.

| Series | Grid | Nearest node | Distance from the Proxy Target |
|---|---|---|---|
| ERA5 Combined Sea (today's pre-2022 Hindcast) | 0.5° | 39.5000, −9.5000 | **25.7 km WSW** |
| **WAVERYS** | 0.2° | 39.6000, −9.2000 | **4.53 km N** |
| IBI reanalysis (finding 7) | 1/36° | 39.5560, −9.2219 | **1.12 km WSW** |
| Open-Meteo `meteofrance_wave` (today's operational Swell) | 1/12°, cell-centred | 39.5417, −9.2083 | 2 km |
| CMEMS operational MFWAM `..._anfc_0.083deg_PT3H-i` | 1/12° | 39.5833, −9.2500 | 4.30 km NW |

The ERA5 and Open-Meteo rows are from `analysis/backtest/README.md`; the rest are computed by
`verify_waverys.py` (haversine, WGS-84 mean radius). #11 flagged 25.7 km as far enough that distance
alone contributed error. WAVERYS cuts that by a factor of about six.

**The node is not on land.** WAVERYS masks land with `_FillValue` (PUM § 4c), so a node this close
inshore has to be checked rather than assumed. Its own static bathymetry gives **163.5 m** of water
at 39.6, −9.2:

```bash
curl -sSO https://s3.waw3-1.cloudferro.com/mdl-native-14/native/GLOBAL_MULTIYEAR_WAV_001_032/\
cmems_mod_glo_wav_my_0.2deg_static_202311/WAVERYSV1_bathymeter.nc   # 13 MB, no credentials
```

That file is the product's own land/sea mask; the node at −9.0 is still wet at 156 m and the first
dry one east of the target is at −8.8. 163.5 m is a 20-km-cell average of ETOPO2 rather than a real depth — the Nazaré Canyon is nowhere
near resolved at 1/5° — but that is fine and expected. The canyon is the thing the Amplification
Model exists to learn; what WAVERYS is being asked for is Offshore Conditions.

## Finding 3 — coverage reaches every one of the 38 Gold Days, at 3-hourly resolution

`verify_waverys.py` reads the 38 dates straight out of `analysis/gold_days/gold_days.jsonl` and
checks them against the dataset's own time axis:

| | Coverage | Step | Gold Days inside |
|---|---|---|---|
| **WAVERYS** | 1980-01-01 00:00 → 2026-05-31 21:00 UTC | 3 h | **38 of 38** |
| IBI reanalysis | 1980-01-01 00:00 → 2026-04-21 23:00 UTC | 1 h | **38 of 38** |
| CMEMS operational MFWAM | 2022-11-01 03:00 → 2026-08-12 00:00 UTC | 3 h | 3 of 38 |

The Gold Days run 2011-11-01 to 2025-12-13, so WAVERYS covers the record with 31 years to spare at
the front. The PUM states the series as "1st January 1980 to M-2", 3-hourly instantaneous at 00, 03,
06, 09, 12, 15, 18 and 21 UTC (§ 2a, § 2c) — the catalogue's 2026-05-31 end, read on 2026-08-02, is
exactly M-2 and confirms the interim extension is running.

**Is 3-hourly enough to catch a peak?** For the question this project asks, yes, with one
implementation consequence. The Heuristic Baseline is evaluated on Offshore Conditions and reduced
to one call per Day; a North Atlantic groundswell arriving at Nazaré rises and falls over a day or
more, not over minutes. There is also reason to think the hourly series the thresholds were fitted
on is not hourly underneath: CMEMS publishes the operational MFWAM at 3-hourly steps, so Open-Meteo
is likely interpolating — **likely, not verified**, and worth one check during ingestion, because if
it holds then eight genuine samples a day is more information than the current pipeline has rather
than less. Either way `hindcast.py` and
`backtest.py` assume 24 rows per Day and count Usable Days from that, so the ingestion has to change
the denominator rather than quietly score 8-hour "days" against a 3/4 completeness rule.

## Finding 4 — reading the catalogue is free; reading the data needs a free Copernicus account

Plainly: **yes, downloading WAVERYS needs Copernicus Marine credentials**, and that is the same wall
parked on #9.

Everything in this note was produced without them. The toolbox documentation says only `describe`
works unauthenticated, with `subset` and `get` requiring `login` or the
`COPERNICUSMARINE_SERVICE_USERNAME` / `_PASSWORD` environment variables
([quick overview](https://toolbox-docs.marine.copernicus.eu/en/stable/usage/quickoverview.html)),
and that matches what happens here: pointing the toolbox at an empty credentials directory changes
nothing about `describe`.

```bash
COPERNICUSMARINE_CREDENTIALS_DIRECTORY=$(mktemp -d) \
    .venv/Scripts/python.exe analysis/waverys/verify_waverys.py      # works
```

The account is free and self-service; this is registration, not procurement, and it is a much
smaller obstacle than #9's. Two observations that belong in the record and should not be built on:
the ARCO Zarr store answered an anonymous request for
`.../cmems_mod_glo_wav_my_0.2deg_PT3H-i_202411/timeChunked.zarr/.zmetadata` with HTTP 200, and both
static mask files download anonymously. Whether the wave arrays themselves are anonymously readable
was **not tested and should not be relied on** — the supported route is the toolbox with an account,
and the ingestion ticket should use it.

## Finding 5 — the reanalysis runs forward to two months ago, so one homogeneous series covers everything

WAVERYS is not a frozen historical archive with a gap between it and the present. The interim
production has been folded into the same dataset — PUM record table, Issue 1.5, 2025-05-30: "Merge
My dataset and Myinterim dataset" — and the series now runs 1980 to M-2 continuously. The catalogue
confirms data through 2026-05-31 as of 2026-08-02.

That is worth more than the extra months. It means the **whole** record, including the 2022-2025
operational panel #12 fitted on, can be read from a single model with a single grid point and a
single set of conventions. The two-panel split in `analysis/backtest/README.md` — operational Swell
after 2022, reconstructed Swell before — exists only because no single source spanned both. WAVERYS
removes the join, and with it the reconstruction whose 41% recall #11 called "not good enough to
carry a verdict".

M-2 latency means WAVERYS can never serve a Pipeline Run. It is a Hindcast in the CONTEXT.md sense
and belongs in training and backtesting only.

## Finding 6 — it is the same model family as the live pipeline, which is a resemblance and not an identity

The QUID states it directly:

> The CMEMS global wave reanalysis, WAVERYS, was built from the real-time wave system
> GLO-WAVE-001-027. It therefore contains a similar wave physics and model configuration. The core
> of the system is based on the wave model MFWAM …

— [QUID, CMEMS-GLO-QUID-001-032 Issue 1.5, 31 May 2024](https://documentation.marine.copernicus.eu/QUID/CMEMS-GLO-QUID-001-032.pdf), § II.

GLO-WAVE-001-027 is `GLOBAL_ANALYSISFORECAST_WAV_001_027`, the operational MFWAM at 1/12°. And
`analysis/forecast_models/README.md` established that Open-Meteo's `best_match` at Praia do Norte is
identical to `meteofrance_wave`, which Open-Meteo's own model table names as
[MFWAM at 0.08°](https://open-meteo.com/en/docs/marine-weather-api). So the reanalysis this ticket
asks about is the multi-year sibling of the exact model the live pipeline reads. That is the best
possible starting position for a recalibration.

It is still not the same number. Four differences, all documented:

- **Forcing.** WAVERYS is driven by ERA5 winds and GLORYS12V1 currents (PUM § 2b). The operational
  system is driven by an operational atmosphere.
- **Assimilation.** WAVERYS assimilates altimeter Significant Wave Height throughout, plus
  Sentinel-1 SAR directional spectra from March 2016 and CFOSAT/SWIM from February 2020. The QUID is
  explicit that the SAR spectra "correct the low frequency part of the wave spectrum **which
  controls the swell partitions**" — i.e. the constraint on the exact variables this project wants
  arrives partway through our record.
- **Resolution.** 1/5° against the operational 1/12°.
- **Grid registration.** Open-Meteo's MFWAM node (39.5417, −9.2083) is offset half a cell from the
  CMEMS operational node (39.5833, −9.2500), so even the two "same model" series are not sampling
  the same point.

The overlap where both exist is 2022 to 2026-05 — the whole of #11's operational panel, including
both of #12's splits. **Measure the offset there. Do not assume it away.**

## Finding 7 — there is a better product than WAVERYS for this, and it costs the same

`IBI_MULTIYEAR_WAV_005_006`, the Atlantic-Iberian Biscay Irish Ocean Wave Reanalysis, appeared while
enumerating the catalogue's wave products and beats WAVERYS on every axis in this ticket:

| | WAVERYS | IBI reanalysis |
|---|---|---|
| Dataset | `cmems_mod_glo_wav_my_0.2deg_PT3H-i` | `cmems_mod_ibi_wav_my_0.027deg_PT1H-i` |
| Swell partition | SW1 + SW2, height/period/direction | **identical six variables** |
| Resolution | 1/5° (~20 km) | **1/36° (~3 km)** |
| Nearest node | 4.53 km N, 163.5 m depth | **1.12 km WSW, 127.9 m depth, mask = 1 (sea)** |
| Cadence | 3-hourly | **hourly** — same as the current pipeline |
| Coverage | 1980-01-01 → M-2 | 1980-01-01 → M-4 |
| Gold Days covered | 38 of 38 | **38 of 38** |
| Model | MFWAM | MFWAM |
| Credentials | free Copernicus account | same |

The wet-node check used the product's own mask file, again anonymously:
`https://s3.waw3-1.cloudferro.com/mdl-native-10/native/IBI_MULTIYEAR_WAV_005_006/cmems_mod_ibi_wav_my_0.027deg_static_202311/IBI-MFC_005_006_mask_bathy.nc`
(0.6 MB) reports `mask = 1` and `deptho = 127.9 m` at 39.5560, −9.2219.

Its variable list is the WAVERYS list plus `VCMX` (maximum wave height) and `VMXL` (maximum crest
height) — which are not Face Height and must not be treated as it, but are the closest thing any of
these products carries to "how big was the biggest wave", and may be worth a look in a later ticket.

Resolution: [product page](https://data.marine.copernicus.eu/product/IBI_MULTIYEAR_WAV_005_006/description),
which also states the M-4 interim cadence; everything else from `verify_waverys.py`.

**Recommendation: ingest IBI as the primary series and WAVERYS as the cross-check.** Two independent
reanalyses of the same ocean, disagreeing or not, is a far better basis for a recalibration than one
— and it is the same download twice, on the same credentials, for a few megabytes.

## What could not be verified

Marked honestly, because #11's whole lesson was what happens when a period variable is assumed to
mean what its name suggests.

1. **Whether `VTM01_SW1` and Open-Meteo's `swell_wave_period` are the same quantity.** Open-Meteo
   documents its swell period as a mean period, not a peak period, and MFWAM has no per-partition
   peak period to publish, so they are at least the same *kind* of quantity. The exact definition
   Open-Meteo serves is not documented to the level of a spectral moment, and I could not establish
   it. This matters enormously: `analysis/backtest/README.md` found that ERA5 **peak** period beat
   ERA5 **mean** period as a predictor of the operational Swell period, so the mean/peak distinction
   is already known to move this project's numbers.
2. **Whether Open-Meteo's single swell series corresponds to SW1, or to SW1 and SW2 combined.**
   Copernicus is explicit that partition energies add and partition heights do not, so a combined
   swell height would be `sqrt(VHM0_SW1² + VHM0_SW2²)`. There is **no** corresponding way to combine
   two periods — a period threshold is inherently about one train. If Open-Meteo is serving combined
   swell and the ingestion feeds it SW1 alone, the height will read low and the mismatch will look
   like model error.
3. **How WAVERYS behaves on the days this project cares about.** The QUID's headline numbers are
   coastal Significant Wave Height bias −5 cm / RMSD 34 cm / SI 20.7%, and coastal mean period bias
   −0.31 s / RMSD 0.86 s / SI 14.8% (Table 2). Those averages say nothing about XXL Days. Worse, the
   QUID singles out our coast: for peak period, "in an area along the Iberian coast and in the
   Azores, SI reaches around 40% (compared to the average of 26% over all measurements)". The
   validation period is 1994-2015 against coastal buoys.
4. **Whether the series is homogeneous across our record.** Three documented discontinuities: the
   SAR spectra that constrain the swell partitions start in March 2016 — **7 of the 29 pre-2022 Gold
   Days fall before that** — CFOSAT is added in February 2020, and the source code moved from ECWAM
   cy38 to cy42 in 2020. The QUID reports the cy38→cy42 change as a small improvement in Significant
   Wave Height (bias −0.11 → −0.10 m) and says nothing about its effect on partitions. Separately,
   1980-1992 is run with no assimilation and no currents at all; irrelevant to us, since the earliest
   Gold Day is 2011-11-01, but fatal to anyone tempted to go further back.
5. **Download time and true on-disk size.** Estimated, not measured — see below.
6. **Whether the IBI reanalysis is as good as its resolution suggests.** I read its catalogue entry,
   its product page and its mask file, but not its QUID. A 1/36° grid resolves the shelf; it does not
   automatically mean better swell periods.

## Verdict

**Yes. WAVERYS can extend the Swell record before 2022, and the ingestion should go ahead — with
`IBI_MULTIYEAR_WAV_005_006` as the primary series and WAVERYS as the cross-check.**

The three ways this could have failed all came back negative. There is a genuine Swell partition,
not a Combined Sea wearing the name — height, period and direction, for two swell trains, with CF
standard names that say so. Coverage reaches every one of the 38 Gold Days with three decades to
spare. And the nearest grid point is water 4.5 km from the Proxy Target, not the 25.7 km ERA5 forced
on #11.

The prize is the one #36 names: the Gold Days available to calibrate against go from **9 to 38**,
and the reconstruction that recovers 41% of threshold crossings stops being on the critical path.

What it costs:

- **Credentials.** A free, self-service Copernicus Marine account. Nothing in this note needed one;
  the data does. This is a smaller wall than #9's and should not be conflated with it.
- **Data volume.** Trivial. One grid node, seven variables, 2011-2021: about **0.9 MB** for WAVERYS
  at 3-hourly and **2.7 MB** for IBI at hourly, as raw float32. Even with ARCO chunk overhead and
  NetCDF framing this is the same order as the ~10 MB Open-Meteo Hindcast already cached in
  `data/raw/hindcast/`. Storage is a non-issue.
- **Download time.** Unmeasured. Minutes rather than hours is the expectation for a point time
  series, but the ARCO store chunks time in ~6-year blocks, so the ingestion should verify rather
  than promise.
- **The real cost is analytical, not logistical.** Two model swaps at once — Open-Meteo MFWAM to
  CMEMS reanalysis, and a moved grid point — mean the shipped thresholds (`3.75 m`, `12.5 s`,
  `13.0 s`) are written in units that no longer quite apply. #12 must be re-run. Feeding WAVERYS
  numbers into the current bars without refitting would be a silent change of variable, which is
  precisely the failure CONTEXT.md's Combined Sea / Swell distinction exists to prevent.

Nothing here needs re-investigating. The variable identifiers, the grid, the coverage and the
credential position are all settled and reproducible from `verify_waverys.py`. What is left is
measurement, and it needs the data.

---

## Draft follow-up ticket — not filed

#36 says the verification ends by filing the ingestion ticket if the answer is yes. It is yes. The
text below is the draft; **filing it is left to a human**, per the ticket's own separation of
verification from ingestion.

> **Title:** Ingest the Copernicus wave reanalysis and recalibrate on all 38 Gold Days
>
> ## Parent
>
> #1
>
> ## Why
>
> #36 verified that the Copernicus wave reanalyses carry a genuine **Swell** partition — height,
> period and direction, for a primary and a secondary swell train — reaching back to 1980 and
> covering all 38 Gold Days. See `analysis/waverys/README.md`.
>
> Today the Heuristic Baseline is calibrated on **9** Gold Days, because the only free pre-2022
> Hindcast carries the **Combined Sea** only and reconstructing Swell from it recovers 41% of
> threshold crossings at the 13 s bar. That is the binding constraint on every accuracy claim this
> project makes. This ticket removes it.
>
> ## What to build
>
> A Swell series for the Proxy Target's grid point spanning 2011 to the present, read from
> Copernicus and cached beside the existing Hindcast, plus the re-run of #12 that it enables.
>
> Primary source: `IBI_MULTIYEAR_WAV_005_006` / `cmems_mod_ibi_wav_my_0.027deg_PT1H-i` — 1/36°,
> hourly, nearest node 1.12 km WSW of the Proxy Target and confirmed sea.
> Cross-check: `GLOBAL_MULTIYEAR_WAV_001_032` / `cmems_mod_glo_wav_my_0.2deg_PT3H-i` (WAVERYS) —
> 1/5°, 3-hourly, nearest node 4.53 km N.
> Variables: `VHM0`, `VHM0_SW1`, `VTM01_SW1`, `VMDR_SW1`, `VHM0_SW2`, `VTM01_SW2`, `VMDR_SW2`.
>
> ## Acceptance criteria
>
> - [ ] A Copernicus Marine account is registered and its credentials are read from the environment,
>       never committed. The fetch fails with a clear message when they are absent.
> - [ ] Both series are fetched for the Proxy Target's nearest **wet** node — verified against each
>       product's own mask file, not assumed — and cached under `data/raw/` (gitignored), skipped on
>       later runs, as `hindcast.py` already does.
> - [ ] **The relationship between the reanalysis Swell and the operational Swell the thresholds
>       were fitted on is measured on the 2022-2026 overlap and written down.** Specifically:
>       whether Open-Meteo's `swell_wave_period` corresponds to `VTM01_SW1`, and whether its
>       `swell_wave_height` corresponds to `VHM0_SW1` or to `sqrt(VHM0_SW1² + VHM0_SW2²)`. #36 could
>       not settle either from documentation. Partition energies add; partition heights and periods
>       do not.
> - [ ] Units, timezone and completeness are validated on arrival, as the existing Hindcast fetch
>       does. WAVERYS is 3-hourly, so the Usable Day rule cannot keep assuming 24 rows.
> - [ ] **#12's calibration is re-run against the full 38 Gold Days**, split on Big-Wave Season
>       boundaries per CONTEXT.md, with a held-out split that the fit never sees. The shipped
>       thresholds in `backend/src/nazarenow/thresholds.json` are rewritten by the fit, not by hand.
> - [ ] #11's backtest is re-run and its two-panel split — operational against reconstructed —
>       collapses into one panel, or the report says explicitly why it could not.
> - [ ] The known inhomogeneities are stated in the report: SAR spectra constrain the swell
>       partitions only from March 2016, and 7 of the 29 newly available Gold Days fall before that.
>
> ## Notes
>
> Blocked by nothing except a free account registration. Not the same blocker as #9, which needs
> in-situ platform access.
>
> This is a Hindcast, at M-2 (WAVERYS) and M-4 (IBI) latency. It can never serve a Pipeline Run and
> must not be wired into one — training and backtesting only, per CONTEXT.md.
>
> Related: #36 is the verification. #12 is the calibration this invalidates and must re-run. #11 is
> the backtest whose reconstructed panel this replaces.

## Files

| File | What it is |
|---|---|
| `verify_waverys.py` | Queries the Copernicus catalogue, prints each candidate's variables, nearest grid node with distance, and Gold Day coverage. No credentials, no data download. |

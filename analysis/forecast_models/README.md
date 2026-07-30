# Which wave model serves Nazaré, and what that means for #7 and #8

Run `python analysis/forecast_models/identify_model.py` to reproduce. No credentials needed.

Two assumptions this project had been building on turned out to be wrong, and a third
could not be checked from the documentation at all.

## Finding 1 — `best_match` at Praia do Norte is MeteoFrance, and it updates twice a day

The Pipeline Run sends no `models` parameter, so Open-Meteo picks one. At 39.56°N, 9.21°W
that selection is **identical, hour for hour, to `meteofrance_wave`** across every variable
the system reads. Not "closest to" — identical.

That matters because ADR 0005 sets the pipeline's cadence from the premise that

> Third-party wave models publish every six hours.

Open-Meteo's documentation gives six-hourly cycles for ECMWF WAM and NCEP GFS Wave, and
**twelve-hourly** for MeteoFrance's wave model and DWD's EWAM and GWAM. The model actually
feeding this system is one of the twelve-hourly ones. The ADR's premise is not wrong in
general; it is wrong about us.

**Caveat, and it is a real one.** The update frequencies above come from Open-Meteo's
documentation page, which is the same source that gave model identifiers the API itself
rejects (finding 3). It has not been independently verified. Confirming it means observing
when the values actually change over a full day — which is precisely what #7's scheduler
will do once it runs, so the honest move is to record the claim as unverified now and let
the scheduler's own logs settle it.

## Finding 2 — ECMWF WAM cannot supply swell at this location, and three other models can

Requested on its own, `ecmwf_wam` returns `swell_wave_height: null` at Nazaré. It carries
combined `wave_height` and no swell partition. The same holds for `ecmwf_wam025`.

Every model returning usable data for the variables this project reads, sampled at one hour
on a small July day:

| Model | `wave_height` | `swell_wave_height` | Provider | Documented cycle |
|---|---|---|---|---|
| `meteofrance_wave` *(= best_match here)* | 0.72 | 0.64 | MeteoFrance | 12 h |
| `dwd_ewam` | 0.78 | 0.78 | DWD (Europe) | 12 h |
| `dwd_gwam` | 0.76 | 0.74 | DWD (global) | 12 h |
| `ncep_gfswave025` | 0.66 | 0.50 | NCEP | 6 h |
| `ncep_gfswave016` | 0.62 | 0.46 | NCEP | 6 h |
| `ecmwf_wam` | 0.72 | **null** | ECMWF | 6 h |
| `ecmwf_wam025` | 0.70 | **null** | ECMWF | 6 h |

### What this means for #8

ADR 0003 names four models for Model Spread: ECMWF WAM, MeteoFrance MFWAM, DWD EWAM and
NCEP GFS Wave. Three of those four work. **ECMWF WAM does not**, for the swell variables the
Amplification Model consumes, so the ADR's roster needs revising rather than implementing.

The good news is that spread is available and looks substantial: swell height across the
working models spans **0.46 m to 0.78 m at the same hour and place** — a range of about 70%
of the smallest value, on a quiet day. Whatever else Model Spread turns out to be, it will
not be uniformly zero.

The trap is in the last column. MeteoFrance and DWD publish every twelve hours and NCEP
every six, so at many moments one model's forecast is up to six hours older than another's.
Differencing them naively measures **our sampling of their publication schedules** as well
as genuine forecast disagreement, and reports the sum as uncertainty. #8 has to align model
runs before differencing, or it will be reading staleness as doubt — which is exactly the
confident, plausible, wrong number this project is built to avoid.

Also worth noting for "independent": EWAM and GWAM are both DWD. Counting them as two
independent opinions overstates the ensemble.

## Finding 3 — the documented model identifiers are wrong

Open-Meteo's marine API documentation lists `gfs_wave025` and `gfs_wave016`. Both are
**rejected by the API**:

```
HTTP 400: Cannot initialize MultiDomains from invalid String value gfs_wave025
```

The working identifiers are **`ncep_gfswave025`** and **`ncep_gfswave016`**. `ewam` and
`gwam` also work as aliases for the `dwd_`-prefixed forms.

Three further identifiers are accepted but return nothing at this location:
`gfs_seamless`, `gfs_global` and `meteofrance_seamless` all yield null for both wave and
swell height, so an implementation that trusted a 200 response without checking the values
would silently record a model as "agreeing" when it had said nothing at all.

## Consequence for #7's cadence

Our data changes at most twice a day. Polling every three hours means what the site shows
is never more than three hours behind a published run; every six hours means it can be
six hours behind, which is half the model's entire update interval.

Neither is expensive: the pipeline makes two calls per run, so three-hourly is 16 calls a
day against Open-Meteo's free-tier limit of 10,000 a day. **Three-hourly**, on the evidence.

It buys freshness, not accuracy. The forecast is no better; it simply is not needlessly old.

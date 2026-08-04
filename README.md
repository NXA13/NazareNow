# NazaréNow

Forecasts when Praia do Norte in Nazaré, Portugal will produce giant waves — early enough to
book a flight and actually see them.

## The problem

Nazaré's waves are the biggest surfed on Earth, and they are caused by an underwater canyon that
focuses Atlantic swell onto a single beach. The swell that produces them is visible in public
forecasts more than a week ahead. But by the time a swell is reported as news, flights and
accommodation are gone. The information arrives long before the decision is actionable, and
nothing turns one into the other.

## What this is, and what it isn't

This is **not** a wave forecaster. Predicting open-ocean swell is already solved to a standard
this project could not approach — ECMWF and NOAA run physics simulations that publish free
forecasts up to 15 days out, and those are consumed here as an input.

Those models run on a grid of roughly 50km. The Nazaré Canyon is invisible at that resolution.
So they can say what swell will arrive off the Portuguese coast, and they cannot say what the
canyon will do with it.

That gap is what this project models:

```
   ATLANTIC              THE CANYON            PRAIA DO NORTE

   4m swell     ────►    amplification  ────►  how big,
   16s period            (below global          actually?
   from WNW               model resolution)

   free, accurate        ← the model            the question
   already                 lives here           worth asking
```

A second layer turns that prediction into a decision — not "how big will it be" but "should you
book now, or wait for a better forecast?" — issued as tiered calls modelled on how national
weather services separate a *watch* from a *warning*.

## Approach

| | |
|---|---|
| **Inputs** | Open-Meteo Marine API — swell height, period, direction, wind. Since #8 the marine forecast is fetched a second time across **five wave models in one request**, and their disagreement is the uncertainty estimate ADR 0003 calls for. Five identifiers are three independent organisations — EWAM and GWAM are both DWD, the two GFS Wave resolutions both NCEP — and each votes once. The result is displayed per day and **is an upper bound on disagreement, not a calibrated uncertainty**: the members' run ages cannot be read from the provider, which inflates the gap by roughly 6% one day out and 29% at six. That error runs toward caution, never toward a Go Call that should not have been issued. Model Spread does not yet reach the Decision Model. |
| **Training target** | *Built.* Significant wave height from Monican02, the Instituto Hidrográfico mooring 15km off Nazaré near the canyon head. Hourly from 2010, via the Copernicus Marine In Situ TAC. Coverage is uneven and two winters are missing entirely. No buoy data reaches the running system: it is analysed in `analysis/buoy_coverage/` and became a dataset in #9 — **73,601 hours paired with the Hindcast across 14 seasons**, in [`analysis/training_dataset/`](./analysis/training_dataset/). |
| **Calibration** | *Applied.* A hand-verified set of days confirmed as genuinely giant — contest days, ratified records — establishing what a predicted height actually means. Thirty-eight are sourced in `analysis/gold_days/`, and since #36 verified and #39 ingested the Copernicus wave reanalysis, all thirty-eight carry a real Swell partition rather than only the 9 since 2022. [`analysis/calibration/`](./analysis/calibration/) fits the thresholds against them, split on Big-Wave Season boundaries: **25 to choose them, 13 held back to check them**. The interface states that number rather than implying a precision the record cannot support. |
| **Learned model** | *Shipped, and it does not win everywhere.* A least-squares fit on the training dataset, active since #13 and selected by `NAZARENOW_MODEL`. Held out on 2020/21–2025/26 it is **worse across all hours** (0.207m against 0.196m of mean absolute error) and **better in every band above 3m**, reaching 0.621m against 1.031m above 6m and 0.564m against 0.885m on Gold Day hours. It corrects a systematic under-read rather than adding scale: the Hindcast sits about 0.86m below the buoy on the biggest held-out days. It changes the predicted height only — every Watch and Go Call is still the rule's — and what it learned is the difference between a reanalysis and a buoy, **not** the canyon's Amplification. [`analysis/amplification_model/`](./analysis/amplification_model/). |
| **Track record** | *Published.* Since #16 the site carries a page stating what the system called and what happened, at `/api/track-record` and below the forecast. It is a **file, not a computation** — [`analysis/track_record/`](./analysis/track_record/) joins the committed reports into `backend/src/nazarenow/track_record.json` and the API only reads it, because scoring the record at request time would mean re-deriving what the system "would have said" from data that did not exist when it said it. Held out, the Watch tier catches **12 of 13** Gold Days on 193 flagged days and the Go Call tier **9 of 13** on 43, so **at most 34 of 43 Go Calls — 79% — would have been a wasted trip**. Every accuracy figure carries the Heuristic Baseline beside it, structurally: a band without both models is refused by the loader and by the frontend's one runtime check. The served figures are #52's corrected ones, not `served_path_scores.csv`'s, whose two most flattering rows measure the shipped Translation's own extrapolation. Two rows carry a caveat published with them, because their sources insist: the Gold Day comparison rests on five days, and the served `Combined Sea ≥ 3 m` aggregate is **not robust** — it falls from +0.027 to −0.004 under a residual grown with the sea, and it is the shipped fit that reverses. |
| **Baseline** | The surf community's rule of thumb, implemented first and retained permanently as the benchmark any learned model must beat. Scored in [`analysis/backtest/`](./analysis/backtest/). Over the whole 2011–2025 record it catches **33 of 38** Gold Days at Watch or better and 16 at Go Call, on 574 Watch days and 128 Go Calls — about 36 and 8 a season. Read those two together: the Watch tier used to catch 37 of 38 on 1050 days, and #43 halved its cost for four Gold Days that the held-out split says were never worth anything (12 of 13 either way). The honest figures are the held-out ones in [`analysis/calibration/`](./analysis/calibration/). |

## Running it locally

Requires **Python 3.14** and **Node 26**, the versions CI runs and the ones pinned in
`.python-version` and `.nvmrc`. Paths below are Windows; on macOS or Linux the
interpreter is `.venv/bin/python` and the CLI scripts live in `.venv/bin/`.

Every command below is written to be run **from the repository root**. Where a block
changes directory it says so, and the next block starts from the root again.

```bash
git clone https://github.com/NXA13/NazareNow.git
cd NazareNow

# One virtualenv serves both the backend and the analysis scripts.
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e "backend[dev]"

cd frontend && npm install && cd ..
```

Fetch some conditions before starting anything — the API has nothing to serve until a
Pipeline Run has stored something, and says so with a 503 rather than inventing zeros:

```bash
.venv/Scripts/python.exe -m nazarenow ingest
```

That contacts Open-Meteo, keeps the raw responses, and writes the parsed readings to
`data/nazarenow.db` at the repository root. The path is anchored to the repository
rather than the working directory, so ingesting and serving cannot end up on different
databases — they did, and the API reported no conditions while holding a good row.

To keep it current without touching it, run the schedule instead:

```bash
.venv/Scripts/python.exe -m nazarenow schedule
```

That runs immediately and then on the forecast cycle, logging each run's outcome. A failed
run loses the run, never the schedule — Open-Meteo will be unreachable sooner or later,
and a system that dies on one bad fetch stops silently while the site goes on serving old
data. Nothing is written by a failed run, and once two whole cycles have passed without a
successful one, the interface says so at the top of the page rather than leaving a reader
to subtract timestamps.

Both intervals live in `backend/src/nazarenow/cycle.py`, and the figure the page shows a
user is sent by the API rather than written into the page — it was typed there as a
literal once, which a change of cadence would have silently made untrue.

Three hours, not six, on evidence: `best_match` at Praia do Norte resolves to
MeteoFrance's wave model, which publishes twice a day, so this keeps the site within
three hours of a published run instead of up to half an update behind. See
[`analysis/forecast_models/`](./analysis/forecast_models/). It buys freshness, not
accuracy.

Per ADR 0005 these are the only parts of the system that talk to a third party.

Then two processes, in separate terminals:

```bash
# Backend on http://127.0.0.1:8000
cd backend
../.venv/Scripts/python.exe -m uvicorn nazarenow.api:app --app-dir src --reload

# Frontend on http://localhost:5273
cd frontend
npm run dev
```

The frontend port is pinned with `strictPort`, so a clash fails immediately rather than
silently moving to another port. That matters: the backend's CORS list names this exact
origin, and a drifting port would break the app in a way neither test suite can catch —
both seams mock the boundary between them.

### Checks

Each suite runs with one command. These are exactly the checks CI runs on every push —
if all of these pass locally, CI will pass too.

**Backend** (from the repository root):

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest
cd backend && ../.venv/Scripts/python.exe -m ruff check .
cd backend && ../.venv/Scripts/python.exe -m ruff format --check .
```

**Frontend** (from the repository root):

```bash
cd frontend && npm test
cd frontend && npm run typecheck
cd frontend && npm run lint
cd frontend && npm run format:check
cd frontend && npm run build
```

Prettier is configured with `endOfLine: auto`. Most files are LF in the working tree
because of `.gitattributes`, but any file written locally on Windows picks up CRLF, and
Prettier's default of `lf` then fails it while CI — which clones with LF — stays green.
That inversion trains people to ignore the check, so the setting removes it.

**Analysis scripts** — linted only. Running them needs Copernicus credentials and the
downloaded data, so CI checks them statically:

```bash
.venv/Scripts/python.exe -m ruff check analysis/
.venv/Scripts/python.exe -m ruff format --check analysis/
```

Fourteen exceptions, all fully runnable because they need no credentials:

```bash
.venv/Scripts/python.exe analysis/gold_days/build.py --check
.venv/Scripts/python.exe analysis/backtest/swell.py --check
.venv/Scripts/python.exe analysis/calibration/calibrate.py --check
.venv/Scripts/python.exe analysis/model_spread/probe.py --check
.venv/Scripts/python.exe analysis/training_dataset/build.py --check
.venv/Scripts/python.exe analysis/amplification_model/train.py --check
.venv/Scripts/python.exe analysis/amplification_model/served_path.py --check
.venv/Scripts/python.exe analysis/amplification_model/translation_shape.py --check
.venv/Scripts/python.exe analysis/forecast_error/profile.py --check
.venv/Scripts/python.exe analysis/model_spread/alignment.py --check
.venv/Scripts/python.exe analysis/model_spread/agreement.py --check
.venv/Scripts/python.exe analysis/overlap/measure.py --check
.venv/Scripts/python.exe analysis/wind_products/gap.py --check
.venv/Scripts/python.exe analysis/track_record/publish.py --check
```

The Gold Day list is hand-written in `analysis/gold_days/README.md` and built from it into
`gold_days.jsonl`, which the calibration fits against. `--check` fails if the two have drifted
and enforces the sourcing protocol — a missing quote, a missing publication date, a
`Documented` entry resting on a single source. A Gold Day recorded on weak evidence does not
add noise; it silently moves the threshold that decides whether someone is told to book a
flight.

The second self-tests the arithmetic behind the backtest's Combined Sea to Swell
reconstruction — quantile mapping and bearings that wrap past north.

The third self-tests the two rules that choose the thresholds, which are the whole of the
calibration and both easy to write backwards. Since ADR 0010 both tiers take the *lowest*
period they can afford against a stated budget, so the rule written backwards would take the
strictest affordable bar instead — throwing away the recall each tier exists for while still
reporting a rate comfortably inside budget, which is exactly the shape of mistake that looks
correct in a report.

The fourth self-tests which model identifiers the provider actually serves at Praia do Norte,
and that each *organisation* votes once. Five identifiers are three organisations, and counting
them as five makes the ensemble look twice as corroborated as it is. It also established what
#8 could not have worked around: run age cannot be read from the provider at all. See
[`analysis/model_spread/`](./analysis/model_spread/).

The fifth self-tests how the training dataset joins its sources: that an hour missing either
the Proxy Target or the Hindcast is dropped rather than filled from its neighbour, that the
one local stamp a year naming two UTC hours gets no wind rather than a guess, that a season
boundary is read on the Nazaré local day rather than the UTC instant, and that the same rows
written twice are byte-identical. See
[`analysis/training_dataset/`](./analysis/training_dataset/).

The sixth self-tests the learned model's fit: that least squares recovers a relationship it
was handed, that a weighting applied to one side only would show up, that the fitting and
held-out seasons cannot overlap, and — the check no test on either side of the seam could
make — that the feature vector `train.py` fits on is the one
`backend/src/nazarenow/models/learned.py` builds at serving time. Those two encodings
diverging would land every coefficient on the wrong column while the model went on returning
entirely plausible numbers. See
[`analysis/amplification_model/`](./analysis/amplification_model/).

The seventh reproduces the published scored figures from its own feature construction, which is
what makes the served-path table comparable with the fit it is set beside. It scores the model
the site actually runs; the sixth scores one it does not.

The eighth self-tests the arithmetic behind the Forecast Error Profile: bearings that wrap past
north, the split between bias a constant correction removes and noise it cannot, and that the
big-swell subset is chosen on what the sea turned out to be rather than on what the forecast
said. Choosing it on the forecast instead would silently drop every big swell the forecast
missed, flattering exactly the failure the profile exists to find. It also pins the subset to
the marine archive for variables held on another host, which shipped wrong once: wind is
archived elsewhere and carries no wave height, so deciding its subset from its own response
emptied it without erroring. See [`analysis/forecast_error/`](./analysis/forecast_error/).

The ninth self-tests the arithmetic behind the run-staleness measurement ADR 0003 demanded
before Model Spread could be differenced: the growth exponent fitted across measured intervals
rather than assumed, and the extrapolation below that range being reported as extrapolation.
The finding is that staleness accounts for about 6% of the spread one day out and 29% at six —
real, growing with Lead Time, and safe to leave uncorrected only because it inflates the
spread rather than hiding agreement. See
[`analysis/model_spread/`](./analysis/model_spread/).

The fourteenth joins the committed reports into the track record the site publishes (#16), and
self-tests the joins that would each publish an individually correct number in the wrong place:
the Big-Wave Season divisor behind "flags per season", the Gold Day split against the shipped
threshold file, both tiers surviving every join, and — the one that matters most — that the
served figures come from #52's fair generator rather than from `served_path_scores.csv`, whose
`all hours` and `under 2 m` rows read +0.035 and +0.074 against the fair generator's −0.077 and
−0.126. Reading the wrong file does not fail; it publishes eight plausible numbers, two of them
wrong in the direction that flatters the learned model. See
[`analysis/track_record/`](./analysis/track_record/).

**The backtest and the calibration** read only free Open-Meteo data, so they run too, though
the first downloads about 10 MB the first time:

```bash
.venv/Scripts/python.exe analysis/backtest/hindcast.py
cd analysis/backtest && ../../.venv/Scripts/python.exe backtest.py
.venv/Scripts/python.exe analysis/calibration/calibrate.py
```

[`analysis/backtest/`](./analysis/backtest/) is the benchmark of ADR 0006: what the
Heuristic Baseline would have called across 2011-2025, and what it would have missed.
[`analysis/calibration/`](./analysis/calibration/) is where its thresholds come from — fitted
on the 2021/22 and 2022/23 Big-Wave Seasons, validated on 2023/24 onward, and written to
`backend/src/nazarenow/thresholds.json`, which the Decision Model loads at each Pipeline Run.
Set `NAZARENOW_THRESHOLDS` to recalibrate without redeploying.

Both are deliberately outside every test suite — an assertion that fails when accuracy shifts
slightly gets disabled within weeks. `backend/tests/test_baseline_is_fixed.py` pins the shipped
threshold file instead, so the committed reports cannot silently stop matching the rule.

### Known gaps

**Mobile layout has no automated protection.** jsdom has no layout engine, so the
frontend suite cannot measure it. It was verified by hand at 320, 360 and 390px — every
reading and all nine forecast days render, the page never scrolls horizontally, and the
hourly table scrolls inside its own box rather than the page. The CSS uses only fluid
units, but nothing stops a regression; a browser-driven test would close this.

**Conditions at Praia do Norte are still not predicted — the number moved 15km closer,
not all the way.** Ticket #6 asks for "predicted conditions at Praia do Norte … not only
Offshore Conditions". Ticket #13 changed what is shown but did **not** finish closing
this, and it is recorded as still unmet rather than ticked.

What changed: the shipped Amplification Model is now a learned fit (#13), so the height
on every call is a fitted correction rather than the offshore forecast carried through
unchanged. It is a genuinely different number, measurably better where the system makes
calls — 0.564m of mean absolute error against the baseline's 0.885m on held-out Gold Day
hours — and the interface describes it as a correction rather than as a pass-through.

What did not: **the target it was fitted on is Monican02, the mooring 15km offshore near
the canyon head, not the beach.** That is ADR 0002's Proxy Target, adopted because Face
Height at Praia do Norte has no historical archive to fit against. So the model learned
the difference between a reanalysis and a buoy, and the canyon's transformation onto the
beach — which is what `CONTEXT.md` defines Amplification as — remains unmodelled and
unmeasured. Calling this criterion met would mean relabelling a prediction of one place
as a prediction of another, which is the same class of error as inventing an amplification
factor: it would produce a confident, plausible, wrong claim rather than a wrong number.

Closing it properly needs a historical record of conditions at the break itself. Nothing
in this repository has one, and `analysis/training_dataset/README.md` (limitation 1) sets
out why.

**The site shows more than ticket #4 asked for.** The ticket enumerates seven readings;
ten are displayed, adding significant wave height, wave period and wave direction under
a *Combined sea* heading. Significant Wave Height is the Proxy Target the whole project
is built on (ADR 0002), so showing it seemed worth the deviation — but it is a
deviation, recorded here rather than left for a reader to notice. The footer also states
that wind and air temperature come from a different forecast cell than the swell
readings, which the ticket did not ask for but which would otherwise be misleading.

### No test contacts a third-party service

This is enforced rather than asserted, in both suites:

- **Frontend** — MSW runs with `onUnhandledRequest: 'error'`, so any request a test did
  not explicitly mock fails the test instead of escaping to the network.
- **Backend** — `backend/tests/conftest.py` blocks outbound socket connections for every
  test, allowing only loopback. Adding a third-party call inside a request handler, which
  ADR 0005 forbids anyway, fails the suite immediately.

## Documentation

- [`CONTEXT.md`](./CONTEXT.md) — the domain glossary. Deliberately opinionated about vocabulary,
  particularly the distinction between wave *face height* and *significant wave height*.
- [`docs/adr/`](./docs/adr/) — architecture decision records covering why the system is shaped
  the way it is, including the alternatives that were rejected and why.

## Status

Slice 1 complete. Current Offshore Conditions and a nine-day forecast are ingested from
Open-Meteo, stored, and displayed with hour-by-hour detail — and every day now carries a
**Watch**, **Go**, **Confirmed** or **No call**, with the conditions that produced it.
Every call is kept: the store appends rather than replaces, so the succession of calls
made about a date as it approaches survives, which is the record #11 scores.

Below the forecast the site now publishes its own track record (#16): what the rule
would have called across 2011-2025, what actually happened on those days, and how far
off the predicted height was — always with the Heuristic Baseline beside it. It states
its own limits in the same breath, above the figures rather than below them: the calls
are reconstructed from the Hindcast rather than issued in advance, the whole calibration
rests on 38 confirmed days, and the height it predicts is Significant Wave Height and not
the Face Height the news quotes.

Each Pipeline Run is recorded in its own right, and the raw responses it fetched and the
calls it derived both point back at it — so the inputs behind any stored call are a
lookup rather than a guess about which fetch happened nearest in time. Runs that **fail**
are recorded too, with what kind of thing went wrong: a provider being unreachable and a
payload this system no longer understands are the same word in a log and need opposite
responses. A run that begins and never finishes stays marked `running`, which is how a
host that died mid-run shows up afterwards.

The Amplification Model behind those calls is the Heuristic Baseline of ADR 0006: the
surf community's rule of thumb, with no machine learning in it. It ships as the
permanent benchmark a learned model must beat in #13, and the interface says plainly
that its thresholds are not yet calibrated — #12 fits them to Gold Days.

The tiers are decided by Lead Time alone for now. ADR 0003 has them driven by Model
Spread — disagreement between independent wave models — which ticket #8 introduces; a
Watch is kept looser than a Go Call in the meantime by not requiring the wind
condition, and nothing claims the forecast has converged, because nothing measures it.

It predicts Significant Wave Height, not Face Height. The canyon's famous threefold
amplification applies to the wave a surfer rides; multiplying the instrument's measure
by a face-height factor would produce a confident, plausible, wrong number.

The baseline applies no amplification at all: the height it "predicts" is the offshore
forecast's own figure, carried through unchanged, and the interface says so on every
call. That is not an oversight — it is the floor #13's learned model has to clear, and
inventing a multiplier would have made the benchmark meaningless as well as wrong.

The range is nine days rather than sixteen because that is where the provider stops
modelling swell. It pads its time axis to whatever is requested and nulls the hours it
cannot fill; those hours are dropped rather than stored, since a null has no honest
rendering and a zero would draw a flat calm sea.

## Acknowledgements

Wave forecasts from [Open-Meteo](https://open-meteo.com). Buoy observations from the
[Instituto Hidrográfico](https://monican.hidrografico.pt)'s MONICAN network, via the
[Copernicus Marine Service](https://marine.copernicus.eu) In Situ TAC, with platform
discovery through [EMODnet Physics](https://emodnet.ec.europa.eu/en/physics).

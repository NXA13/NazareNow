# NazaréNow

A forecasting system that predicts when Praia do Norte in Nazaré, Portugal will produce
giant waves, early enough for someone to book travel and witness them in person.

## Language

### The place

**Praia do Norte**:
The beach at Nazaré where the giant waves break. The only location this system forecasts.
_Avoid_: Nazaré (the town, ambiguous), the spot, the break

**Nazaré Canyon**:
The submarine canyon that focuses incoming Atlantic swell onto Praia do Norte. The physical
cause of the phenomenon, and the thing global forecast models are too coarse to represent.
_Avoid_: North Canyon, the trench

### Conditions

**Offshore Conditions**:
The state of the open ocean before the canyon acts on it — swell height, swell period, swell
direction, wind speed and wind direction. Freely available from third-party forecast models
and reanalysis. Always consumed, never predicted: the system reads them as inputs and may
display them to a user, but producing its own is out of scope per ADR 0001.
_Avoid_: the weather, sea state, raw data

**Amplification**:
The transformation the canyon applies to Offshore Conditions to produce the waves seen at
Praia do Norte. The relationship this system exists to learn.
_Avoid_: focusing, magnification, the canyon effect

**Face Height**:
The height of a breaking wave at Praia do Norte as a human observer perceives it — the number
quoted in news coverage and world records. Estimated from imagery by expert panels, never
measured instrumentally, and therefore has no reliable historical archive.
_Avoid_: wave height (ambiguous), wave size

**Combined Sea**:
The whole wave field arriving at a point, both long-period Swell from distant storms and
short-period waves raised by local wind. Described by Significant Wave Height. Distinct
from Swell, which is only the travelled component and is what the canyon amplifies.
_Avoid_: sea state, total sea, waves

**Significant Wave Height (Hs)**:
The standard oceanographic measure of a Combined Sea — the mean height of the highest third of
waves over a sampling period. Measured instrumentally. Much smaller than Face Height for the
same sea, and not convertible to it by any fixed ratio.
_Avoid_: wave height (ambiguous), swell height (a different variable)

**Day**:
A calendar day at Nazaré — Europe/Lisbon, which is UTC in winter and UTC+1 under summer
time. Every day this system names means this: the day a Traveller stands on the beach, the
day hours are grouped into, the day a call is issued for, and the day Lead Time counts to.
Never a UTC day and never the reader's own — a viewer in Sydney reading "06:00" is being
told when to be at Praia do Norte, not when to wake up at home. See ADR 0008.
_Avoid_: date (when the local sense matters), UTC day, today

**XXL Day**:
A day on which Praia do Norte produced genuinely giant surf, confirmed by an external
authority such as a contest being run, a record being ratified, or documented coverage.
_Avoid_: big day, epic day, a swell

**Big-Wave Season**:
October through March, the months in which North Atlantic storm activity makes XXL Days
at Praia do Norte possible. Named by the calendar year it begins in, so the 2016/17
season runs from October 2016 to March 2017 — a season is never a calendar year, and
splitting one across two years destroys the unit that matters.
_Avoid_: winter, storm season, the season

**Usable Day**:
A day on which an instrument reported for at least three quarters of its hours. The unit
in which coverage is counted, because a handful of scattered readings cannot establish
what a day did.
_Avoid_: good day, complete day, valid day

### Data

**Proxy Target**:
Significant Wave Height recorded by Monican02, the inshore mooring near the canyon head,
used as the training target in place of Face Height because Face Height cannot be sourced
historically. Abundant and objective, but measures the sea 15km offshore rather than the
wave at the beach.
_Avoid_: label, target variable, ground truth

**Offshore Observation**:
Significant Wave Height and related measurements from Monican01, the deep-water mooring
55km out. A measured rather than modelled reading of the swell arriving at the coast.
Always a system input, never a target — predicting it would mean predicting our own
inputs.
_Avoid_: the other buoy, offshore buoy data

**Gold Day**:
A hand-verified XXL Day, assembled from contest records and ratified measurements. Too few to
train on. Used only to calibrate and validate the alerting threshold.
_Avoid_: test set, validation data, positive example

### The system

**Amplification Model**:
The component that takes Offshore Conditions and predicts the resulting Combined Sea at Nazaré.
Learns what global forecast models cannot resolve. Produces a prediction and an uncertainty.
_Avoid_: the model, the AI, the predictor

**Heuristic Baseline**:
The surf community's rule of thumb for Nazaré, expressed as fixed thresholds on Offshore
Conditions and used as an Amplification Model requiring no training. Ships first, and remains
permanently as the benchmark any learned model must outperform.
_Avoid_: naive model, dumb model, v1, rules engine

**Decision Model**:
The component that consumes the Amplification Model's prediction and uncertainty and produces
a Go Call. Concerned with whether to act, not with how big the waves will be.
_Avoid_: the alerter, the recommender, business logic

**Go Call**:
The system's recommendation to commit — book travel now for a named date. Issued only when
Model Spread has narrowed and predicted conditions clear the Gold Day threshold. Optimised for
precision: a false Go Call costs the user real money.
_Avoid_: alert, notification, prediction, signal

**Watch**:
A long-range warning that a swell may be forming, issued before confidence justifies a Go Call.
Tells the user to start paying attention, not to spend money. Optimised for recall: missing a
forming swell is worse than raising a Watch that fades.
_Avoid_: early alert, heads-up, pre-warning

**Confirmed**:
A short-range statement that the swell has materialised, for users already travelling or
already at Praia do Norte. Carries no booking recommendation.
_Avoid_: nowcast, live alert

**Hindcast**:
A reconstruction of Offshore Conditions as they actually were, built after the fact with the
benefit of observations. Accurate, but never available for a future date. Training material
only, never a system input at serving time.
_Avoid_: historical data, reanalysis, past weather

**Forecast Error Profile**:
The measured distribution of how far third-party forecasts drift from what actually happened,
recorded separately for each Lead Time. Widens as Lead Time grows. Injected into predictions at
serving time so the system's confidence reflects forecast range.
_Avoid_: error bars, noise, bias

**Pipeline Run**:
One scheduled execution that fetches Offshore Conditions and buoy observations, produces
Predictive Distributions for every date in range, derives Watch and Go Calls, and stores them.
The only part of the system that runs a model or contacts a third party.
_Avoid_: job, cron, refresh, update

**Predictive Distribution**:
The system's output for a given date — a range of plausible outcomes with probabilities, rather
than a single number. What the Decision Model consumes to produce a Watch or Go Call.
_Avoid_: prediction, estimate, forecast

**Model Spread**:
The degree of disagreement between independent third-party wave models forecasting the same
date. Used as the system's uncertainty estimate, since no ensemble marine forecast is available.
Narrow spread means confidence; wide spread means doubt.
_Avoid_: variance, error bars, confidence

**Lead Time**:
The interval between a Go Call being issued and the swell arriving. The quantity the system
exists to maximise, and the reason a forecast alone is insufficient.
_Avoid_: warning time, notice, horizon

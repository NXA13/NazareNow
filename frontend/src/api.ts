/**
 * The one place the frontend talks to the backend.
 *
 * Per ADR 0005 the backend is a read-only store of precomputed results, so everything
 * here is a GET. Keeping fetch calls in a single module means tests mock one network
 * boundary rather than scattering handlers across components.
 */

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000';

/**
 * One measured quantity and the unit the provider reported it in.
 *
 * The unit travels with the value rather than being assumed by the interface, so a
 * provider switching from km/h to m/s changes what the page says instead of silently
 * rescaling every number on it.
 */
export interface Reading {
  value: number;
  unit: string;
}

export interface CurrentConditions {
  /** The older of the two providers' observation times: the picture is at least this old. */
  observed_at: string;
  fetched_at: string;
  /** True when no pipeline run has succeeded for two whole cycles. The backend decides
   * this — "too old to trust" is domain knowledge, and ADR 0005 makes this layer a reader. */
  stale: boolean;
  /** How old results must be before `stale` turns true. Sent so this layer can state the
   * figure without knowing it: it was once written here as the literal "six hours", which
   * a change of cadence would have silently made untrue. */
  stale_after_hours: number;
  latitude: number;
  longitude: number;
  swell_height: Reading;
  swell_period: Reading;
  swell_direction: Reading;
  significant_wave_height: Reading;
  wave_period: Reading;
  wave_direction: Reading;
  water_temperature: Reading;
  air_temperature: Reading;
  wind_speed: Reading;
  wind_direction: Reading;
}

/** An hour carries readings only. Everything describing the *run* — when it happened,
 * where, and whether it is now too old to trust — belongs to the response, not to each
 * of its hours. */
export interface ForecastHour extends Omit<
  CurrentConditions,
  'observed_at' | 'fetched_at' | 'latitude' | 'longitude' | 'stale' | 'stale_after_hours'
> {
  at: string;
}

export type CallStatus = 'confirmed' | 'go' | 'watch' | 'none';

export interface DayCall {
  status: CallStatus;
  /** Days from the first day the forecast covers, fixed when the call was issued rather
   * than recomputed against the clock. A Go Call is only worth something if it arrives
   * while flights are still bookable, so the number travels with the call. */
  lead_time_days: number;
  reasons: string[];
  predicted_significant_wave_height: Reading;
  /** Whether the wave models refused a Go Call this day's conditions otherwise supported.
   *
   * The interface cannot derive this, and that is why the backend sends it. A day whose own
   * swell period sits below the Go Call bar has every forecaster below it too, so it reports
   * `divided` while the models decided nothing. Two Watch days that look identical from
   * status alone are a swell the forecasters have not settled on and a swell that was never
   * big enough.
   *
   * Null for a call issued before the backend consulted the models at all. */
  go_call_withheld: boolean | null;
  /** What the wave models said about the hour this call rests on.
   *
   * Not readable off `model_spread`: that is the date's median hour and a call is decided on
   * its best matching hour. Null for a call issued before any of this existed. */
  model_agreement: ModelAgreement | null;
  /** Where the backend's Predictive Distribution puts this date, 5th to 95th percentile.
   *
   * The point of the whole thing: "6.1 metres, 78% confident" is not something a person can
   * act on, and "most likely 6.1 m, plausibly 5.2 to 7.0" is. Null for a call decided
   * without a distribution. */
  plausible_range: HeightRange | null;
  /** How much of that distribution clears the calibrated height bar.
   *
   * **The height condition alone (#66).** A giant day needs four quantities to hold — height,
   * swell period, swell direction and wind — and this prices one. The other three have no
   * archived forecast error to build a distribution from, so no probability exists for them;
   * ADR 0004 carries the reasoning. Rendering this as the chance of a giant day would be the
   * largest overclaim in the interface, which is why `Confidence` names the height condition
   * and then lists what is missing.
   *
   * A share between 0 and 1, not a percentage — the backend leaves the rounding here on
   * purpose, so the figure is stated in one place rather than two. */
  height_bar_probability: number | null;
  /** Whether a measured forecast error profile covered this call's lead time.
   *
   * False past the archive's seven days, where the width is extrapolated. The page has to be
   * visibly more cautious there rather than presenting an extrapolation as evidence — and
   * this arrives as a flag rather than being inferred from `lead_time_days`, because
   * inferring it means keeping a copy of how deep the archive currently is. It grows every
   * season. */
  uncertainty_measured: boolean | null;
  /** Whether the width, rather than the models, refused a Go Call.
   *
   * Separate from `go_call_withheld` because both end in a Watch and they are different
   * facts: forecasters disagreeing about a swell is not the same as one forecast being too
   * uncertain to book on. */
  go_call_withheld_for_uncertainty: boolean | null;
  /** What earlier pipeline runs said about this same date, oldest first.
   *
   * The current call is not among them. Empty on the first run that mentions a date, which
   * is the honest answer rather than a series of one — a date compared against itself would
   * draw a shift of exactly zero and read as settled.
   *
   * Sent rather than accumulated here, because this page has no memory: a traveller opens it
   * once every few days and the runs it would have needed to watch happened while nobody was
   * looking. */
  previous_runs: EarlierCall[];
}

/** A span between two heights, carrying its unit for the reason `Reading` does. */
export interface HeightRange {
  low: number;
  high: number;
  unit: string;
}

/** One superseded call about a date, cut down to what "has this shifted?" needs.
 *
 * Deliberately not a whole `DayCall`. The reasons and the withholding flags describe a
 * judgement that is no longer the system's, and rendering a stale explanation beside a
 * current one would be worse than not showing the history at all.
 */
export interface EarlierCall {
  issued_at: string;
  /** How far out the date was when that run spoke. A range narrowing as a date approaches is
   * the forecast doing its job; the same narrowing at a fixed lead time is not. */
  lead_time_days: number;
  status: CallStatus;
  predicted_significant_wave_height: Reading;
  plausible_range: HeightRange | null;
}

/** The three things the wave models can have said about a call's own hour.
 *
 * `unmeasured` is never agreement. Fewer than two organisations reporting produces no Model
 * Spread rather than a spread of zero, and treating that as agreement would put the system's
 * most confident calls exactly where it knows least. */
export type ModelAgreement = 'agreed' | 'divided' | 'unmeasured';

/**
 * How far apart the independent wave models are on one reading for one date.
 *
 * The backend's uncertainty estimate. Several third-party wave models are asked about the
 * same date and their disagreement is the doubt — narrow means confidence, wide means the
 * forecast has not settled.
 *
 * **An upper bound on disagreement, not a calibrated uncertainty.** The models publish on
 * different cycles and their run ages cannot be read from the provider, which inflates the
 * measured gap by roughly 6% one day out and up to 29% at six. That error always runs toward
 * caution — it can make models look more different than they are, never more alike — so this
 * layer must describe it as models disagreeing, and never as a margin on the forecast.
 */
export interface DaySpread {
  unit: string;
  /** Null when fewer than two independent organisations answered. Null rather than zero: a
   * zero is indistinguishable from perfect agreement and would read as certainty at exactly
   * the moment the system knows least. */
  spread: number | null;
  /** The two opinions the spread was measured between; null exactly when `spread` is.
   *
   * For swell direction these run clockwise around the compass, so across north `highest` is
   * the smaller number — 355 to 5 is the correct 10-degree arc, and rendering them as a
   * minimum and a maximum would name the wrong 350-degree one. */
  lowest: number | null;
  highest: number | null;
  /** The organisations that answered, not the models. Two of the five identifiers are DWD's
   * and two are NCEP's, so five names are three independent opinions. */
  providers: string[];
  /** Whether fewer than the full roster of organisations answered. */
  degraded: boolean;
  /** How many organisations a full read would have heard from — the backend's roster size,
   * sent rather than known here so "two of three" cannot go on saying three after a fourth
   * organisation joins. */
  providers_expected: number;
  /** Whether `lowest` and `highest` are compass points rather than points on a line.
   *
   * Sent by the backend, which names its bearings explicitly, rather than inferred here from
   * the unit string: this decides how the pair is read, and a provider respelling its degree
   * sign would otherwise silently turn an arc into an interval. */
  bearing: boolean;
  /** How many of the date's forecast hours could be measured, out of how many it has. */
  hours_measured: number;
  hours_total: number;
}

export interface ForecastDay {
  date: string;
  /** Null when no pipeline run has made a call about this day — which is not the same as
   * a call of status `none`. That one has been judged and found not worth travelling for;
   * this one has not been judged at all. */
  call: DayCall | null;
  /** Height, period and direction are summarised separately and never collapsed into a
   * single size figure — a short-period 8m sea and an 8m groundswell are different days. */
  peak_swell_height: Reading;
  /** Period and direction *of the largest hour* — not the day's maximum period. */
  swell_period_at_peak: Reading;
  swell_direction_at_peak: Reading;
  /** The day's actual longest period, which can fall at a quieter hour and is the
   * groundswell signal a big-wave forecast lives on. */
  longest_swell_period: Reading;
  /** Model Spread for this date, keyed by the reading it is measured on.
   *
   * The backend always sends every reading it measures spread on, with nulls where nothing
   * could be measured, rather than omitting the failures — an absent key would be read as
   * agreement. Empty only for a date stored before the backend derived any. */
  model_spread: Record<string, DaySpread | undefined>;
  hours: ForecastHour[];
}

export interface Forecast {
  fetched_at: string;
  /** As on CurrentConditions: both endpoints serve the same pipeline run. */
  stale: boolean;
  stale_after_hours: number;
  /** Null when the backend holds no calls, so nothing has named a model. */
  amplification_model: string | null;
  /** Whether the thresholds behind these calls were fitted to Gold Days, or are the surf
   * community's rule of thumb. Read from the stored call, so a call issued before the fit
   * keeps saying so. */
  calibrated: boolean;
  /** What the fit rests on. Null for calls decided before there was one. */
  calibration: Calibration | null;
  days: ForecastDay[];
}

/** The provenance of the thresholds a call was decided against.
 *
 * Rendered rather than merely carried: dropping the "uncalibrated" warning without saying
 * what replaced it would turn a stated limitation into an unstated one, and the fit is nine
 * Gold Days wide. */
export interface Calibration {
  fitted_on: string;
  validated_on: string;
  gold_days_fitted: number;
  gold_days_validated: number;
  gold_days_total: number;
  method: string;
  source: string;
  fitted_at: string;
}

/**
 * One tier's record against the days independently confirmed as giant.
 *
 * Every rate arrives already worked out. This layer does no arithmetic on them, for the
 * same reason it does not derive `degraded` or count the provider roster: a second
 * implementation of a figure is a second answer, and the one on the page is the one nobody
 * re-derives. The counts travel too, because a rate without them is not checkable — "69% of
 * the days that mattered" reads the same whether it rests on thirteen days or thirteen
 * hundred, and it rests on thirteen.
 */
export interface TierRecord {
  gold_days_called: number;
  gold_days_in_panel: number;
  days_flagged: number;
  recall: number;
  /** A **lower** bound. A flagged day missing from the hand-verified list may still have
   * been a genuinely giant day nobody documented, so the truth can only be kinder. */
  precision_lower_bound: number;
  /** How often acting on this tier would have been wasted, at worst — the complement of a
   * lower bound. Rendered as given, and never softened: the page is asking someone to
   * spend money on the strength of it. */
  wasted_upper_bound: number;
  days_wasted_upper_bound: number;
  flags_per_big_wave_season: number;
}

/** One span the record was scored over.
 *
 * Both tiers are fields rather than a map, so a panel missing one cannot be constructed —
 * a watch and a go call are different promises and are never reported as one figure. */
export interface PanelRecord {
  span: string;
  /** What produced the calls. A reconstruction of the conditions built afterwards is not
   * the same evidence as a forecast issued in advance, and the page says which. */
  basis: string;
  gold_days: number;
  big_wave_seasons: number;
  watch_or_better: TierRecord;
  go_call: TierRecord;
}

/**
 * How close each model came, over one subset of hours.
 *
 * Both errors are required. ADR 0006 forbids reporting an accuracy figure without the
 * Heuristic Baseline beside it, and a required pair is a promise the type keeps — there is
 * no shape here in which one model's number travels alone.
 */
export interface AccuracyBand {
  name: string;
  hours: number;
  baseline_mae_m: number;
  learned_mae_m: number;
  /** Positive means the learned model is closer to the buoy. */
  gain_m: number;
  /** What this row cannot carry on its own, on the rows whose source says so.
   *
   * Sent with the band rather than written into the page, so the qualification travels with
   * the number instead of living next to one particular table. Two rows have one, and both
   * are figures that look strong until qualified — which is the kind a page drops. */
  caveat: string | null;
}

export interface RecordedDay {
  date: string;
  season: string;
  call: CallStatus;
  /** The largest significant wave height that day **in the reconstruction the call was made
   * from** — not an independent measurement of how the day turned out. The independently
   * verified part of a row is `gold_day`.
   *
   * The whole sea, 15km offshore near the head of the canyon. Not the height of a wave face
   * at the beach, and not convertible to it by any fixed ratio. */
  peak_significant_wave_height_m: number;
  gold_day: boolean;
  gold_tier: string | null;
}

/** What this installation has actually issued, as opposed to what the reports reconstruct.
 *
 * Deliberately unscored, and the page says why: no buoy reading reaches the running system,
 * so there is nothing here to score a stored call against. Counting them is the honest
 * limit of what this section can claim. */
export interface IssuedRecord {
  calls_issued: number;
  dates_covered: number;
  go_calls_issued: number;
  /** Null on a fresh installation, which is shown as "nothing yet" rather than as an empty
   * record of success. */
  first_issued_at: string | null;
  last_issued_at: string | null;
}

export interface TrackRecord {
  published_at: string;
  /** The path in the repository that regenerates the record, rendered so a reader can go
   * and check it rather than take it on trust. */
  source: string;
  /** Two panels, never averaged. One is measured only on seasons the thresholds never saw;
   * the other is larger and partly covers the seasons they were chosen on. */
  held_out: PanelRecord;
  full_record: PanelRecord;
  /** The two models compared on identical hours, each reading the reconstruction. */
  scored: AccuracyBand[];
  /** The same comparison along the path the running system actually takes. They disagree,
   * and the disagreement is the finding rather than a discrepancy to tidy away. */
  served: AccuracyBand[];
  gold_days_fitted: number;
  gold_days_validated: number;
  gold_days_total: number;
  days: RecordedDay[];
  /** Null when the backend could not open its store at all. Distinct from a store with
   * nothing in it, which reports zeros: this one is "we do not know", and the page says so
   * rather than showing a fresh installation's numbers for a database nobody could read. */
  issued: IssuedRecord | null;
}

/**
 * The one runtime check in this module, and it earns its place.
 *
 * `AccuracyBand` requires both models' error, but a type is a compile-time promise and the
 * body arriving here is untyped JSON. ADR 0006 forbids reporting an accuracy figure without
 * the Heuristic Baseline beside it, and without this the failure is not a missing column —
 * it is a crash inside the number formatter, which React renders as a blank page. Neither
 * outcome tells a reader anything, and one of them looks like a system with no track record
 * rather than a page that could not load one.
 *
 * So a band missing either model makes the whole record unusable, deliberately. Dropping the
 * row instead would publish a shorter table with no sign it was ever longer.
 */
function bandsAreComplete(bands: AccuracyBand[]): boolean {
  return bands.every(
    (band) => typeof band?.baseline_mae_m === 'number' && typeof band?.learned_mae_m === 'number',
  );
}

export async function fetchTrackRecord(): Promise<TrackRecord> {
  const response = await fetch(`${API_BASE}/api/track-record`);
  if (!response.ok) {
    throw new Error(`Track record request failed with status ${response.status}`);
  }
  const record = (await response.json()) as TrackRecord;

  if (!bandsAreComplete(record.scored ?? []) || !bandsAreComplete(record.served ?? [])) {
    throw new Error(
      'Track record carries an accuracy band without both models, which ADR 0006 does not permit',
    );
  }
  return record;
}

export async function fetchForecast(): Promise<Forecast> {
  const response = await fetch(`${API_BASE}/api/conditions/forecast`);
  if (!response.ok) {
    throw new Error(`Forecast request failed with status ${response.status}`);
  }
  return (await response.json()) as Forecast;
}

export async function fetchCurrentConditions(): Promise<CurrentConditions> {
  const response = await fetch(`${API_BASE}/api/conditions/current`);
  if (!response.ok) {
    throw new Error(`Conditions request failed with status ${response.status}`);
  }
  return (await response.json()) as CurrentConditions;
}

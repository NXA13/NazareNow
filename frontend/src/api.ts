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
}

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

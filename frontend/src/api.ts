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
  'observed_at' | 'fetched_at' | 'latitude' | 'longitude' | 'stale'
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
  hours: ForecastHour[];
}

export interface Forecast {
  fetched_at: string;
  /** As on CurrentConditions: both endpoints serve the same pipeline run. */
  stale: boolean;
  /** Null when the backend holds no calls, so nothing has named a model. */
  amplification_model: string | null;
  /** False while thresholds are a rule of thumb rather than values fitted to Gold Days.
   * The interface must not imply a precision the numbers do not have. */
  calibrated: boolean;
  days: ForecastDay[];
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

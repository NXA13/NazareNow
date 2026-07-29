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

export interface ForecastHour extends Omit<
  CurrentConditions,
  'observed_at' | 'fetched_at' | 'latitude' | 'longitude'
> {
  at: string;
}

export type CallStatus = 'confirmed' | 'go' | 'watch' | 'none';

export interface DayCall {
  status: CallStatus;
  /** Days from the day the forecast was fetched. A Go Call is only worth something if
   * it arrives while flights are still bookable, so the number travels with the call. */
  lead_time_days: number;
  reasons: string[];
  predicted_significant_wave_height: Reading;
}

export interface ForecastDay {
  date: string;
  call: DayCall;
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
  model: string;
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

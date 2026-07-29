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

export async function fetchCurrentConditions(): Promise<CurrentConditions> {
  const response = await fetch(`${API_BASE}/api/conditions/current`);
  if (!response.ok) {
    throw new Error(`Conditions request failed with status ${response.status}`);
  }
  return (await response.json()) as CurrentConditions;
}

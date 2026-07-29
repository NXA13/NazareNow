import { useEffect, useState } from 'react';

import { fetchForecast, type CallStatus, type Forecast, type ForecastDay } from './api';
import { compassPoint, formatTimestamp, formatValue } from './format';

type LoadState =
  { status: 'loading' } | { status: 'loaded'; forecast: Forecast } | { status: 'failed' };

/** What each status says, in the fewest words that are still honest. */
const CALL_LABELS: Record<CallStatus, string> = {
  confirmed: 'Confirmed',
  go: 'Go',
  watch: 'Watch',
  none: 'No call',
};

const CALL_MEANINGS: Record<CallStatus, string> = {
  confirmed: 'It is happening. For anyone already travelling.',
  go: 'Worth booking. Every condition of the rule holds at this range.',
  watch: 'Something may be forming. Start watching flights, do not book yet.',
  none: 'Not a day to travel for.',
};

/** How a day compares with the rest of the range on screen.
 *
 * Relative, not absolute. An earlier version used fixed thresholds lifted from the surf
 * community's rule of thumb — which reimplemented ADR 0006's Heuristic Baseline in the
 * presentation layer, on swell height rather than the Significant Wave Height the
 * baseline is actually defined on, in a layer ADR 0005 says only reads. It also did
 * nothing useful: every day of a real summer week fell in the same bucket, so nine
 * tiles looked identical.
 *
 * Comparing each day with the largest day shown needs no domain knowledge and always
 * distinguishes the standout day, whether the week peaks at 1.2m or at 12m.
 */
export type Prominence = 'leading' | 'notable' | 'ordinary';

function prominence(value: number, largest: number): Prominence {
  if (largest <= 0) return 'ordinary';
  const share = value / largest;
  if (share >= 0.95) return 'leading';
  if (share >= 0.6) return 'notable';
  return 'ordinary';
}

/** The day, as a weekday and date a reader can place without doing arithmetic. */
function dayLabel(date: string): string {
  const parsed = new Date(`${date}T12:00:00Z`);
  if (Number.isNaN(parsed.getTime())) {
    return date;
  }
  return parsed.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' });
}

function DaySummary({
  day,
  largest,
  selected,
  onSelect,
}: {
  day: ForecastDay;
  largest: number;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      className={`day rank-${prominence(day.peak_swell_height.value, largest)}${selected ? ' selected' : ''}`}
      aria-pressed={selected}
      // The label carries every summarised figure. An earlier version named only the
      // height, which overrode the card's content for screen readers and lost the
      // period and direction entirely — the two values that separate a groundswell
      // worth travelling for from a big messy sea.
      aria-label={
        `${day.date} — peak swell ${day.peak_swell_height.value}${day.peak_swell_height.unit}, ` +
        `period ${day.swell_period_at_peak.value}${day.swell_period_at_peak.unit}, ` +
        `from ${compassPoint(day.swell_direction_at_peak.value)}, ` +
        `longest period ${day.longest_swell_period.value}${day.longest_swell_period.unit}`
      }
      onClick={onSelect}
    >
      <span className="day-date" data-testid={`day-label-${day.date}`}>
        {dayLabel(day.date)}
      </span>
      <span className={`call call-${day.call.status}`} data-testid={`call-${day.date}`}>
        {CALL_LABELS[day.call.status]}
      </span>
      <span className="day-swell">
        <span className="value">{formatValue(day.peak_swell_height.value)}</span>
        <span className="unit">{day.peak_swell_height.unit}</span>
      </span>
      {/* Period and direction sit beside the height rather than being folded into it.
          An 8m short-period sea and an 8m groundswell are entirely different days, and
          the difference is the whole reason someone would get on a plane. */}
      <span className="day-detail">
        <span className="value">{formatValue(day.swell_period_at_peak.value)}</span>
        <span className="unit">{day.swell_period_at_peak.unit}</span>
        <span className="bearing">{compassPoint(day.swell_direction_at_peak.value)}</span>
      </span>
    </button>
  );
}

function HourTable({ day }: { day: ForecastDay }) {
  return (
    <div className="hours-scroll">
      <table>
        {/* Times are the provider's, in UTC, and labelled as such. Rendering them in
            the viewer's zone beside a locally-formatted date would shift hours across
            the day boundary and quietly disagree with the date above. */}
        <caption>Hour by hour on {dayLabel(day.date)}, times in UTC</caption>
        <thead>
          <tr>
            <th scope="col">Time (UTC)</th>
            <th scope="col">Swell</th>
            <th scope="col">Period</th>
            <th scope="col">Dir</th>
            <th scope="col">Wind</th>
          </tr>
        </thead>
        <tbody>
          {day.hours.map((hour) => (
            <tr key={hour.at}>
              <th scope="row">{hour.at.slice(11, 16)}</th>
              <td>
                {formatValue(hour.swell_height.value)}
                <span className="unit">{hour.swell_height.unit}</span>
              </td>
              <td>
                {formatValue(hour.swell_period.value)}
                <span className="unit">{hour.swell_period.unit}</span>
              </td>
              <td>{compassPoint(hour.swell_direction.value)}</td>
              <td>
                {formatValue(hour.wind_speed.value)}
                <span className="unit">{hour.wind_speed.unit}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ForecastRange() {
  const [state, setState] = useState<LoadState>({ status: 'loading' });
  const [openDate, setOpenDate] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    fetchForecast()
      .then((forecast) => active && setState({ status: 'loaded', forecast }))
      .catch(() => active && setState({ status: 'failed' }));
    return () => {
      active = false;
    };
  }, []);

  if (state.status === 'loading') {
    return <p>Loading forecast...</p>;
  }

  if (state.status === 'failed') {
    return (
      <p role="alert" className="alert">
        Could not load the forecast. The service may be unavailable, or no pipeline run has stored
        one yet.
      </p>
    );
  }

  const open = state.forecast.days.find((day) => day.date === openDate) ?? null;
  const largest = Math.max(...state.forecast.days.map((day) => day.peak_swell_height.value));

  return (
    <section aria-labelledby="forecast-heading">
      <h2 id="forecast-heading">The next {state.forecast.days.length} days</h2>

      <div className="days">
        {state.forecast.days.map((day) => (
          <DaySummary
            key={day.date}
            day={day}
            largest={largest}
            selected={day.date === openDate}
            onSelect={() => setOpenDate(day.date === openDate ? null : day.date)}
          />
        ))}
      </div>

      {open ? (
        <>
          <div className="call-detail" role="note" aria-label={`Why ${dayLabel(open.date)}`}>
            <p>
              <strong>{CALL_LABELS[open.call.status]}</strong> — {CALL_MEANINGS[open.call.status]}
              {open.call.status !== 'none' && <> Issued {open.call.lead_time_days} days ahead.</>}
            </p>
            <ul>
              {open.call.reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
            <p className="provenance">
              Predicted significant wave height{' '}
              <strong>
                {formatValue(open.call.predicted_significant_wave_height.value)}
                {open.call.predicted_significant_wave_height.unit}
              </strong>
              . That is the instrument's measure of the sea, not the height of the wave face a
              surfer rides — the canyon makes the face far larger, and this system does not yet
              predict it.
            </p>
          </div>
          <HourTable day={open} />
        </>
      ) : (
        <p className="hint">Select a day to see how it develops hour by hour.</p>
      )}

      {!state.forecast.calibrated && (
        <p role="status" className="alert">
          These calls come from the surf community's rule of thumb, not from thresholds fitted to
          days Nazaré is known to have gone giant. Treat them as a starting point rather than a
          forecast.
        </p>
      )}

      <p className="provenance">
        Forecast fetched {formatTimestamp(state.forecast.fetched_at)}. The range ends where the
        provider stops modelling swell, which is sooner than its wind forecast.
      </p>
    </section>
  );
}

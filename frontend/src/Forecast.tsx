import { useEffect, useState } from 'react';

import {
  fetchForecast,
  type CallStatus,
  type DaySpread,
  type Forecast,
  type ForecastDay,
} from './api';
import { compassPoint, formatReading, formatTimestamp, formatValue } from './format';

type LoadState =
  { status: 'loading' } | { status: 'loaded'; forecast: Forecast } | { status: 'failed' };

/** A day the backend has no call for at all, which is not the same as a call of `none`.
 * That one was judged and found not worth travelling for; this one was never judged. */
const UNJUDGED = 'unjudged';

/** What each status says, in the fewest words that are still honest. */
const CALL_LABELS: Record<CallStatus | typeof UNJUDGED, string> = {
  confirmed: 'Confirmed',
  go: 'Go',
  watch: 'Watch',
  none: 'No call',
  [UNJUDGED]: 'Not judged',
};

const CALL_MEANINGS: Record<CallStatus | typeof UNJUDGED, string> = {
  confirmed: 'It is happening. For anyone already travelling.',
  // "Every condition holds" without qualification overstated it: a day is judged on its
  // best matching hour, so that can be one hour in twenty-four. The reasons below carry
  // the count, and this sentence now points at it rather than talking past it.
  go: "Worth booking. Every condition of the rule holds at this day's best hour.",
  watch: 'Something may be forming. Start watching flights, do not book yet.',
  none: 'Not a day to travel for.',
  [UNJUDGED]: 'No pipeline run has assessed this day. Its hours below are still real.',
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

/** The day, as a weekday and date a reader can place without doing arithmetic.
 *
 * Built from the date's own parts as a *local* calendar day, not from an instant. Anchoring
 * at `T12:00:00Z` and converting was correct for most of the world and wrong past UTC+12: a
 * reader in Auckland saw noon UTC land at 01:00 the following day, so the card, its
 * `aria-label` and the hourly table caption named three-quarters of a different date than
 * the one the backend had grouped (#25).
 *
 * The forecast's days are the provider's UTC days — see `days.py` — so the label must
 * render the date it was given, in every zone, rather than an instant inside it. */
function dayLabel(date: string): string {
  const [year, month, day] = date.split('-').map(Number);
  if (!year || !month || !day) {
    return date;
  }

  const parsed = new Date(year, month - 1, day);
  // Checking for an Invalid Date is not enough, and checking only that would be worse
  // than the bug it replaced: the numeric constructor never returns Invalid, it *rolls
  // over*. `new Date(2026, 12, 45)` is 14 February 2027, and `new Date(26, 0, 1)` is
  // 1926. So a malformed date would render as a confident, plausible, wrong day rather
  // than falling back to the raw string — this project's characteristic failure.
  //
  // Reading the parts back off the result is what actually proves nothing rolled over.
  if (
    parsed.getFullYear() !== year ||
    parsed.getMonth() !== month - 1 ||
    parsed.getDate() !== day
  ) {
    return date;
  }

  return parsed.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' });
}

/** What a day card says about the agreement behind it, or null when there is nothing to flag.
 *
 * **A marker, never a measurement.** The panel below carries the range, the contributing
 * organisations and the hour they belong to; none of that can come up here. A width on a card
 * needs a narrow/wide threshold nobody has calibrated, and printing the range itself would put
 * a *median-hour* pair beside the card's *peak-hour* height — two numbers a reader would
 * reasonably expect to match, which never will.
 *
 * What does belong here is the thing a reader who never clicks would otherwise miss: that the
 * agreement behind this call was measured against less than the full roster, or could not be
 * measured at all. That is a fact about how much was checked, not a quantity, so it needs no
 * threshold and cannot be misread as a margin on the height beside it.
 *
 * A day the backend sent no spread for gets nothing rather than "unchecked" — that is a date
 * stored before Model Spread existed, and inventing a caveat for it would claim something
 * about a measurement that was never attempted.
 *
 * A **refused Go Call outranks both**, because it is the only one of these that changed what
 * the card says. Read from `go_call_withheld` rather than from `model_agreement`, which cannot
 * carry it — `DayCall` in `api.ts` says why.
 */
function agreementFlag(day: ForecastDay): string | null {
  if (day.call?.go_call_withheld) {
    // Which of the two withheld it. "The forecasters disagree" said about an endpoint that
    // never answered would be an invented finding, so an unmeasured hour keeps the marker the
    // unreachable case already has.
    return day.call.model_agreement === 'divided' ? 'models divided' : 'unchecked';
  }

  const height = day.model_spread?.swell_height;
  if (!height) return null;
  if (height.spread === null) return 'unchecked';
  return height.degraded ? 'partly checked' : null;
}

/** The same fact spelled out, for the label a screen reader hears instead of the card.
 *
 * `aria-label` overrides the card's content, so a marker that lived only in the markup would
 * be silently dropped for exactly the readers least able to go looking for the panel (#25). */
const FLAG_MEANINGS: Record<string, string> = {
  unchecked: 'no second opinion — nothing was available to check this day against',
  'partly checked': 'checked against fewer forecasters than usual',
  'models divided': 'the forecasters have not settled on this day, so no Go Call was issued',
};

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
  const flag = agreementFlag(day);

  return (
    <button
      type="button"
      className={`day rank-${prominence(day.peak_swell_height.value, largest)}${selected ? ' selected' : ''}`}
      aria-pressed={selected}
      // The label carries every summarised figure. An earlier version named only the
      // height, which overrode the card's content for screen readers and lost the
      // period and direction entirely — the two values that separate a groundswell
      // worth travelling for from a big messy sea.
      //
      // Every figure goes through `formatReading`, the same function the visible card uses.
      // Reading the raw values here meant a source carrying more than two decimals was
      // announced as "4.23456m" while the card showed "4.23" — and because aria-label
      // overrides the content, that reader had no way to reach the shorter one (#25).
      // Sharing the function is what stops the two drifting again.
      aria-label={
        `${day.date} — peak swell ${formatReading(day.peak_swell_height)}, ` +
        `period ${formatReading(day.swell_period_at_peak)}, ` +
        `from ${compassPoint(day.swell_direction_at_peak.value)}, ` +
        `longest period ${formatReading(day.longest_swell_period)}` +
        (flag ? `, ${FLAG_MEANINGS[flag]}` : '')
      }
      onClick={onSelect}
    >
      <span className="day-date" data-testid={`day-label-${day.date}`}>
        {dayLabel(day.date)}
      </span>
      <span
        className={`call call-${day.call?.status ?? UNJUDGED}`}
        data-testid={`call-${day.date}`}
      >
        {CALL_LABELS[day.call?.status ?? UNJUDGED]}
      </span>
      <span className="day-swell" data-testid={`day-peak-${day.date}`}>
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
      {flag && (
        <span className="day-agreement" data-testid={`day-agreement-${day.date}`}>
          {flag}
        </span>
      )}
    </button>
  );
}

/** The model name the backend reports when a learned fit produced the call (#13). */
const LEARNED_MODEL = 'learned-amplification';

/** The model name the backend reports for ADR 0006's rule of thumb, kept runnable forever. */
const BASELINE_MODEL = 'heuristic-baseline';

/** Why a day got the call it did, and what the predicted number does and does not mean. */
function CallDetail({ day, model }: { day: ForecastDay; model: string | null }) {
  const status = day.call?.status ?? UNJUDGED;
  const learned = model === LEARNED_MODEL;
  const baseline = model === BASELINE_MODEL;

  return (
    <div className="call-detail" role="note" aria-label={`Why ${dayLabel(day.date)}`}>
      <p>
        <strong>{CALL_LABELS[status]}</strong> — {CALL_MEANINGS[status]}
        {day.call && status !== 'none' && <> Issued {day.call.lead_time_days} days ahead.</>}
      </p>
      {day.call && (
        <>
          <ul>
            {day.call.reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
          <p className="provenance">
            Predicted significant wave height{' '}
            <strong>
              {formatValue(day.call.predicted_significant_wave_height.value)}
              {day.call.predicted_significant_wave_height.unit}
            </strong>
            . That is the instrument's measure of the sea, not the height of the wave face a surfer
            rides — the canyon makes the face far larger, and this system does not yet predict it.
          </p>
          {/* Which sentence is true depends on which model produced the call, so the copy
              is chosen from the model the backend reports rather than fixed here. Ticket
              #13 swapped a learned fit in; ADR 0006 keeps the rule of thumb runnable
              permanently, so both sentences stay reachable and both have to be honest.

              The learned wording is careful about one thing in particular: what was fitted
              is the difference between the reanalysis and a buoy near the canyon head, and
              CONTEXT.md defines Amplification as the transformation onto the beach. Saying
              "the canyon has been modelled" would overclaim exactly the quantity this
              project holds apart.

              Both sentences are matched against a known name rather than one being the
              else-branch, because the else-branch was a claim too: an unrecognised model —
              or none reported at all — rendered "carried through unchanged", which is a
              specific factual assertion about arithmetic nobody here has seen. A model this
              build does not know about gets no provenance sentence, which is the only
              honest thing left to say about it. */}
          {learned && (
            <p className="provenance">
              That figure is a fitted correction, not the offshore forecast carried through: it is
              adjusted toward what the buoy near the canyon head has historically measured when the
              open ocean looked like this. It is still a measure of the sea offshore of the beach,
              and the transformation onto Praia do Norte itself is not modelled.
            </p>
          )}
          {baseline && (
            <p className="provenance">
              The rule of thumb does not scale that height: it is the offshore forecast's own
              figure, carried through unchanged. Nothing here models what the canyon does to it yet.
            </p>
          )}
        </>
      )}
    </div>
  );
}

/** A spread rendered in the reading's own terms.
 *
 * Swell direction is a compass arc, not an interval: it runs clockwise from `lowest` to
 * `highest`, and across north the second number is the smaller one. Printing "5 to 355"
 * would name the wrong three-quarters of the compass on precisely the swells the canyon
 * focuses best, so direction gets its own sentence rather than the shared one.
 *
 * Which readings are arcs is the backend's `bearing` flag, not a test on the unit string.
 * The backend names its bearings for exactly this reason — the unit is the provider's own
 * text, and it decides arithmetic here rather than only presentation. */
function spreadRange(spread: DaySpread): string {
  if (spread.lowest === null || spread.highest === null) return '';
  if (spread.bearing) {
    return (
      `${compassPoint(spread.lowest)} to ${compassPoint(spread.highest)} ` +
      `(${formatValue(spread.lowest)}° to ${formatValue(spread.highest)}°)`
    );
  }
  return `${formatValue(spread.lowest)}${spread.unit} to ${formatValue(spread.highest)}${spread.unit}`;
}

/** What the independent wave models make of this day, and how much to lean on it.
 *
 * Deliberately worded as *models disagreeing*, never as a margin on the forecast. The
 * backend's own docstrings are explicit that this is an upper bound on disagreement rather
 * than a calibrated uncertainty — the members' run ages cannot be read from the provider, so
 * some of the gap is our sampling of their publication schedules rather than genuine doubt.
 * Rendering it as "8.1m ± 0.3m" would turn a bound into a confidence interval in one
 * typographic stroke, which is the overclaim this project keeps having to undo.
 *
 * The numbers are the day's *middle* hour, and the copy says so. They are not the peak hour
 * the card above summarises, so presenting them without that word would leave two swell
 * heights on screen that a reader would reasonably expect to match and which never will. */
function Agreement({ day }: { day: ForecastDay }) {
  const height = day.model_spread?.swell_height;
  const period = day.model_spread?.swell_period;
  const direction = day.model_spread?.swell_direction;

  if (!height) {
    return null;
  }

  return (
    /* A region rather than a note, so it does not compete with the call detail above it
       for the note role. The two say different kinds of thing — that one explains the call,
       this one says how much to lean on it — and a reader landing on "note" wants the call. */
    <section
      className="agreement"
      aria-label={`How much the forecasters agree about ${dayLabel(day.date)}`}
    >
      <h4>How much the forecasters agree</h4>
      {height.spread === null ? (
        <p data-testid={`spread-${day.date}`}>
          Fewer than two independent forecasters covered this day, so there is no agreement to
          report. That is missing information, not a settled forecast — the day below is a single
          model's opinion with nothing to check it against.
        </p>
      ) : (
        <>
          <p data-testid={`spread-${day.date}`}>
            {height.providers.length} independent forecasters, and at this day's middle hour they
            are{' '}
            <strong>
              {formatValue(height.spread)}
              {height.unit}
            </strong>{' '}
            apart on the swell — {spreadRange(height)}.
            {period?.spread !== null && period !== undefined && (
              <>
                {' '}
                They differ by {formatValue(period.spread)}
                {period.unit} on the period.
              </>
            )}
            {direction?.spread !== null && direction !== undefined && (
              <> On the direction they span {spreadRange(direction)}.</>
            )}
          </p>
          <p className="provenance">
            {height.providers.join(', ')} at that hour. A spread could be measured for{' '}
            {height.hours_measured} of this day's {height.hours_total} hours. A narrow gap means
            they are describing the same weather; a wide one means the forecast has not settled and
            the day could still change. It is an upper bound on how far apart they are, not a margin
            on the height above: the models publish on different schedules, which widens the gap
            rather than narrowing it.
          </p>
        </>
      )}
      {height.degraded && (
        <p role="status" className="alert" data-testid={`spread-degraded-${day.date}`}>
          Only {height.providers.length} of {height.providers_expected} independent forecasters
          answered for this day, so this rests on less than a full read.
        </p>
      )}
    </section>
  );
}

function HourTable({ day }: { day: ForecastDay }) {
  return (
    <div className="hours-scroll">
      <table>
        {/* Times are Nazaré's own, and labelled as such. Rendering them in the viewer's
            zone would shift hours across the day boundary and quietly disagree with the
            date above — and the viewer's zone is not the one they would be standing in.
            A day here is a day at Praia do Norte (ADR 0008). */}
        <caption>Hour by hour on {dayLabel(day.date)}, times in Nazaré</caption>
        <thead>
          <tr>
            <th scope="col">Time (Nazaré)</th>
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
          <CallDetail day={open} model={state.forecast.amplification_model} />
          <Agreement day={open} />
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

      {state.forecast.calibrated && state.forecast.calibration && (
        <p role="status" className="alert">
          These thresholds were fitted to {state.forecast.calibration.gold_days_total} days Nazaré
          is known to have gone giant — {state.forecast.calibration.gold_days_fitted} to choose them
          and {state.forecast.calibration.gold_days_validated} held back to check them. That is a
          very small number of days: far more giant days are on record, but the swell measurements
          these calls are written in do not reach back that far. Expect the calls to be roughly
          right and individually uncertain.
        </p>
      )}

      <p className="provenance">
        Forecast fetched {formatTimestamp(state.forecast.fetched_at)}. The range ends where the
        provider stops modelling swell, which is sooner than its wind forecast.
      </p>
    </section>
  );
}

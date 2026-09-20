import { useEffect, useState, type ReactNode } from 'react';

import {
  fetchForecast,
  type CallStatus,
  type DayCall,
  type DaySpread,
  type Forecast,
  type ForecastDay,
  type HeightRange,
  type ModelAgreement,
  type Reading,
} from './api';
import { Figure } from './Figure';
import { ADDRESS } from './router';
import { compassPoint, formatRange, formatReading, formatTimestamp, formatValue } from './format';

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

/**
 * A direction as its own number and the sector that number falls in.
 *
 * **The name alone hides movement, which is what #106 was about.** `compassPoint` rounds to 16
 * sectors 22.5° wide, so a column of names changes about once every four hours on a swell backing
 * five degrees an hour, and looks frozen in between. Story 6 of #1 — "how conditions change hour
 * by hour, so that I know when during the day to be at the beach" — is at Praia do Norte largely a
 * question about direction, and a reader watching for the swell to come round into the canyon's
 * window could not see it happening.
 *
 * `format.ts` has said since it was written that the name is "shown alongside the number rather
 * than instead of it: a reader should not need to know that 298° is west-north-west, and a surfer
 * checking the swell direction should not have to trust our rounding." The current panel and the
 * Model Spread arcs did that; the day row and both direction columns of this table rendered the
 * name *instead of* the number, so one module stated a principle its main consumer declined.
 *
 * One component rather than the same three lines in three places, so the rule stays uniform — a
 * bearing rendered one way here and another way there is how the docstring came apart the first
 * time.
 */
function Bearing({ reading }: { reading: Reading }) {
  return (
    <span className="bearing">
      {formatValue(reading.value)}
      {reading.unit} {compassPoint(reading.value)}
    </span>
  );
}

/** How much of a day row's comparison bar is filled, as a percentage.
 *
 * Measured against the largest day on screen rather than an absolute scale. The absolute
 * version of this was three buckets with thresholds lifted from the surf community's rule of
 * thumb — which reimplemented ADR 0006's Heuristic Baseline in the presentation layer, on swell
 * height rather than the Significant Wave Height the baseline is actually defined on, in a layer
 * ADR 0005 says only reads. It also did nothing useful: every day of a real summer week landed in
 * the same bucket, so every row looked the same.
 *
 * Comparing each day with the largest day shown needs no domain knowledge and always
 * distinguishes the standout day, whether the week peaks at 1.2m or at 12m. The bar carries that
 * comparison continuously, so it says which of two ordinary days is the bigger one — which the
 * buckets it replaced could not.
 *
 * Rounded to a tenth of a percent: the difference between two days is what this shows, and no
 * bar is wide enough for the digits past that to be a difference anyone can see.
 */
function percentOfLargest(value: number, largest: number): number {
  if (largest <= 0) return 0;
  return Number(((value / largest) * 100).toFixed(1));
}

/** The day, as a weekday and date a reader can place without doing arithmetic.
 *
 * Built from the date's own parts as a *local* calendar day, not from an instant. Anchoring
 * at `T12:00:00Z` and converting was correct for most of the world and wrong past UTC+12: a
 * reader in Auckland saw noon UTC land at 01:00 the following day, so the row, its
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

/** What a day row says about the agreement behind it, or null when there is nothing to flag.
 *
 * **A marker, never a measurement.** The panel below carries the range, the contributing
 * organisations and the hour they belong to; none of that can come up here. A width on a row
 * needs a narrow/wide threshold nobody has calibrated, and printing the range itself would put
 * a *median-hour* pair beside the row's *peak-hour* height — two numbers a reader would
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
 * the row says. Read from `go_call_withheld` rather than from `model_agreement`, which cannot
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

/** The same fact spelled out, for the label a screen reader hears instead of the row.
 *
 * `aria-label` overrides the row's content, so a marker that lived only in the markup would
 * be silently dropped for exactly the readers least able to go looking for the panel (#25). */
const FLAG_MEANINGS: Record<string, string> = {
  unchecked: 'no second opinion — nothing was available to check this day against',
  'partly checked': 'checked against fewer forecasters than usual',
  'models divided': 'the forecasters have not settled on this day, so no Go Call was issued',
};

/**
 * One day of the range, as a row (#117).
 *
 * **Four things, in one line, at any count.** The date, the height, how the height compares with
 * the rest of the range, and the call. A grid cell fitted two of them and wrapped the rest, which
 * is what made a week take three rows of cards; a row fits all four and stays one line, so the
 * column's height is the number of days times a constant rather than something that has to be
 * measured after the response arrives.
 *
 * Period and direction ride along in the middle, small. They are not among the four, and the
 * design's row does without them — but an 8m short-period sea and an 8m groundswell are entirely
 * different days, and the difference is the whole reason someone would get on a plane. They cost
 * no height here, because the row is as tall as its tallest cell and they are not it.
 */
function DayRow({
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
  const status = day.call?.status ?? UNJUDGED;

  return (
    <button
      type="button"
      className={`day day-${status}${selected ? ' selected' : ''}`}
      aria-pressed={selected}
      // The label carries every summarised figure. An earlier version named only the
      // height, which overrode the row's content for screen readers and lost the
      // period and direction entirely — the two values that separate a groundswell
      // worth travelling for from a big messy sea.
      //
      // Every figure goes through `formatReading`, the same function the visible row uses.
      // Reading the raw values here meant a source carrying more than two decimals was
      // announced as "4.23456m" while the row showed "4.23" — and because aria-label
      // overrides the content, that reader had no way to reach the shorter one (#25).
      // Sharing the function is what stops the two drifting again.
      aria-label={
        `${day.date} — peak swell ${formatReading(day.peak_swell_height)}, ` +
        `period ${formatReading(day.swell_period_at_peak)}, ` +
        `from ${formatReading(day.swell_direction_at_peak)} ` +
        `${compassPoint(day.swell_direction_at_peak.value)}, ` +
        `longest period ${formatReading(day.longest_swell_period)}` +
        (flag ? `, ${FLAG_MEANINGS[flag]}` : '')
      }
      onClick={onSelect}
    >
      <span className="day-date" data-testid={`day-label-${day.date}`}>
        {dayLabel(day.date)}
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
        <Bearing reading={day.swell_direction_at_peak} />
      </span>
      {/* How this day compares with the largest day on screen, which is the one thing a list
          of sixteen numbers does not give a reader at a glance. Relative to the range shown
          rather than to a fixed scale, so it distinguishes the standout day whether the week
          peaks at 1.2m or at 12m.

          **In the neutrals.** A bar drawn in the status colours would make "biggest day this
          week" and "book a flight" the same signal, on a page whose entire purpose is the
          difference between them — the rule `ink.test.ts` holds the sheet to.

          Hidden from the accessible tree because it states nothing the label does not: the
          heights are all in it, and a screen reader comparing two of them does not need a
          picture of the comparison. */}
      <span className="track" aria-hidden="true">
        <span
          className="fill"
          data-testid={`day-bar-${day.date}`}
          style={{ width: `${percentOfLargest(day.peak_swell_height.value, largest)}%` }}
        />
      </span>
      {flag && (
        <span className="day-agreement" data-testid={`day-agreement-${day.date}`}>
          {flag}
        </span>
      )}
      <span className={`call call-${status}`} data-testid={`call-${day.date}`}>
        {CALL_LABELS[status]}
      </span>
    </button>
  );
}

/**
 * Where the measured forecast-error archive stops covering this forecast, as an index into its
 * days — or null when it covers every day the forecast has.
 *
 * **Read off each day's own flag, never by counting to seven.** The archive is seven days deep
 * today and grows every season, so a page holding a copy of that number goes on drawing the
 * boundary in last season's place, and nothing fails when it does.
 *
 * A *boundary* rather than a per-day filter, because the days arrive in date order and the
 * archive covers a prefix of them: the first day the backend marks extrapolated is where its
 * record ran out, and every later day is further out still.
 *
 * **So a day's own flag is not the last word on which side it lands** — its position is, and that
 * is deliberate. Two days say nothing about the archive: one carrying no call at all, and one
 * whose call was issued before the flag existed. Filtering on the flag alone would lift either of
 * them back above a divider they sit below by date, claiming a measurement reaches a lead time
 * the day before it has just said it does not. A prefix cannot do that. What it costs is that
 * such a day below the line is described by a heading nobody measured it against — the quieter
 * of the two errors, because it is the cautious one.
 */
function archiveBoundary(days: ForecastDay[]): number | null {
  const first = days.findIndex((day) => day.call?.uncertainty_measured === false);
  return first === -1 ? null : first;
}

/**
 * Every day the forecast covers, one per row, split where the measured archive ends.
 *
 * The split is drawn rather than hidden. Trimming the list back to the days the archive covers
 * was the alternative, and it would have dropped a day somebody could still book a flight for
 * in order to make the arithmetic neat.
 */
function DayList({
  days,
  largest,
  openDate,
  onSelect,
}: {
  days: ForecastDay[];
  largest: number;
  openDate: string | null;
  onSelect: (date: string) => void;
}) {
  const boundary = archiveBoundary(days);
  const measured = boundary === null ? days : days.slice(0, boundary);
  const beyond = boundary === null ? [] : days.slice(boundary);

  const row = (day: ForecastDay) => (
    <DayRow
      key={day.date}
      day={day}
      largest={largest}
      selected={day.date === openDate}
      onSelect={() => onSelect(day.date)}
    />
  );

  return (
    <>
      <div className="days">{measured.map(row)}</div>
      {beyond.length > 0 && (
        <>
          {/* The heading and the reason in one element, so the group below cannot end up
              labelled by a boundary it no longer describes. What it says is the whole of why
              these days are dimmer: out here the plausible range is a line continued past
              everything that was ever measured about it. */}
          <p className="days-divider" id="beyond-the-archive">
            Beyond the measured archive — the plausible range out here is extrapolated, not measured
          </p>
          <div className="days beyond" role="group" aria-labelledby="beyond-the-archive">
            {beyond.map(row)}
          </div>
        </>
      )}
    </>
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
              <Figure>
                {formatValue(day.call.predicted_significant_wave_height.value)}
                {day.call.predicted_significant_wave_height.unit}
              </Figure>
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
          <PlausibleRange day={day} />
          {/* The last step, then the shape of it. In that order because a reader who takes
              one line from this panel should take "what changed since I last looked", and
              the series is what they read when that line is not enough (#99). */}
          <Shift day={day} />
          <History day={day} />
        </>
      )}
    </div>
  );
}

/** How sure the forecast is, as a range in metres rather than a percentage on the height.
 *
 * **Named for the range it renders, not for how sure the system is (#76, ADR 0014).** It shows
 * the plausible range, the share of it above the height bar, and the caveats scoping both — and
 * calling it `Confidence` put that word on a block whose own scope paragraph exists to say the
 * figure is *not* the chance of a giant day. The identifier contradicted the caveat it wrapped.
 * "Confidence" also belongs to Model Spread in the glossary, which this block does not render.
 *
 * The point of ticket #15. "6.1 metres, 78% confident" gives a reader nothing to act on: it
 * asks them to convert a confidence into a size themselves, which is the arithmetic the
 * backend has already done. The two heights the day plausibly lands between say the same
 * thing in terms somebody booking a flight can use.
 *
 * **The percentage is rounded here and nowhere else.** The backend sends a share between 0
 * and 1 on purpose, so the figure a reader sees is stated in one place — a percentage
 * computed on both sides is two copies of a number that can drift apart.
 *
 * **It is a chance of clearing one condition, not a chance of a giant day (#66).** A giant day
 * needs height, swell period, swell direction and wind; this prices height. The rest cannot be
 * priced: the Swell partition is not archived at any Lead Time, so there is no measured
 * forecast error to put a distribution around swell period — which is the condition that
 * actually binds. Saying "likely to be a giant day" here would be the system's largest
 * overclaim, on its most load-bearing number, so the copy names the condition it prices and
 * lists the ones it does not.
 *
 * **It says "significant wave height", not "size".** CONTEXT.md's Face Height entry puts "wave
 * size" on its Avoid list, and this bar is on the Combined Sea 15km offshore, not on the wave
 * a person would see break. "The minimum size for a giant day" sitting beside the words "giant
 * day" invites exactly the Face Height reading the glossary exists to prevent, and
 * `TrackRecord` already spells the quantity out for the same reason.
 *
 * A call decided without a distribution renders nothing rather than an empty band. Those are
 * calls issued before the pipeline built them, and drawing a range of zero width for one
 * would read as total certainty about the oldest predictions in the record.
 */
function PlausibleRange({ day }: { day: ForecastDay }) {
  const call = day.call;
  const range = call?.plausible_range;
  if (!call || !range) return null;

  // Read once and tested twice below, so the figure and the caveat scoping it cannot come
  // apart. They sit in different paragraphs and cannot share a single conditional.
  const probability = call.height_bar_probability;

  return (
    <div className="plausible-range" data-testid={`plausible-range-${day.date}`}>
      <p>
        Plausibly{' '}
        <strong>
          <Figure>{formatRange(range)}</Figure>
        </strong>
        {probability !== null && (
          <>
            {' '}
            — about <strong>{Math.round(probability * 100)}%</strong> likely to clear the minimum
            significant wave height a giant day needs.
          </>
        )}
      </p>
      {/* Height is one condition of several, and the only one this figure prices. Left unsaid,
          a reader would reasonably take the percentage for the chance of a giant day. Rendered
          from the same guard as the figure above, so the caveat cannot outlive what it caveats. */}
      {probability !== null && (
        <p className="plausible-range-scope">
          Height only. The swell period, swell direction and wind a giant day also needs are not
          part of that figure.
        </p>
      )}
      {/* Which of the two refusals produced this Watch. Both end in the same badge, and a
          reader told only "Watch" cannot tell a swell the forecasters have not settled on
          from one the forecast is simply too uncertain about to book on. */}
      {call.go_call_withheld_for_uncertainty && (
        <p>
          The forecast is too uncertain at this range to book on, so this is a Watch rather than a
          Go Call. The forecasters agree about it; the forecast itself has not settled.
        </p>
      )}
      {/* Beyond the archive the width is an extrapolation, and an extrapolation rendered
          identically to a measurement is the failure the flag exists to prevent. Announced
          rather than merely printed, so it reaches a reader who never opens the panel. */}
      {call.uncertainty_measured === false && (
        <p role="status" className="alert">
          Nothing has been measured about how wrong a forecast this far out tends to be — the record
          only reaches seven days. The range keeps widening at the rate it did measure, but treat it
          as the shape of the doubt rather than its size.
        </p>
      )}
    </div>
  );
}

/** How the prediction has moved since the runs before it.
 *
 * A swell building between runs is the signal a traveller is waiting for, and a number that
 * silently replaces the previous one shows none of it. Both directions are stated: a fading
 * swell is as much a reason to act — by not booking — as a building one.
 *
 * Compared against the run immediately before, not against the oldest in the series. What a
 * reader is asking is "what changed since I last looked", and the most recent run is the
 * closest this page can get to that without knowing when they last looked.
 *
 * Nothing renders on the first run that mentions a date. The backend sends an empty list
 * rather than a series of one, because a date compared against itself draws a shift of
 * exactly zero and reads as settled.
 */
function Shift({ day }: { day: ForecastDay }) {
  const call = day.call;
  const previous = call?.previous_runs.at(-1);
  if (!call || !previous) return null;

  const now = call.predicted_significant_wave_height;
  const before = previous.predicted_significant_wave_height;
  const change = now.value - before.value;
  // A run that moved the height by less than the rounding the page displays at has not
  // moved it as far as a reader can see, and "0m larger" is a sentence about nothing.
  const moved = Math.abs(change) >= 0.05;

  return (
    <>
      <p className="shift" data-testid={`shift-${day.date}`}>
        {moved ? (
          <>
            <strong>
              <Figure>
                {formatValue(Math.abs(change))}
                {now.unit}
              </Figure>{' '}
              {change > 0 ? 'larger' : 'smaller'}
            </strong>{' '}
            than the run before, which put this day at{' '}
            <Figure>
              {formatValue(before.value)}
              {before.unit}
            </Figure>
          </>
        ) : (
          <>
            Unchanged since the run before, which also put this day at{' '}
            <Figure>
              {formatValue(before.value)}
              {before.unit}
            </Figure>
          </>
        )}
        {/* The lead time the earlier run spoke at, because a range narrowing as a date
            approaches is the forecast doing its job and the same narrowing at a fixed lead
            time would be something else entirely. */}
        {` from ${previous.lead_time_days} days out.`}
      </p>
      <TierChange date={day.date} before={previous.status} now={call.status} />
    </>
  );
}

/** That the *verdict* moved, and not only the number under it.
 *
 * Story 21 of #1, and the case it names is the one that was invisible: a day carrying a Watch
 * last run and nothing this run rendered exactly like a day that had never been called at all.
 * The reader it is written for — somebody who has spent a week watching flights — was told
 * nothing. `EarlierCall` has always carried `status` for this; nothing read it.
 *
 * **The firming direction is not a bonus.** The same silence hid a Watch becoming a Go Call,
 * which is the transition a Traveller most needs to catch, so it is stated too.
 *
 * **No ranking of the tiers.** `Confirmed` is not a stronger `Go` — ADR 0003 and `CONTEXT.md`
 * make it a short-range statement to somebody already travelling, carrying no booking
 * recommendation — so a day moving from Go to Confirmed as it approaches has not weakened.
 * Ordering the four statuses would invent a scale the domain does not have and would print a
 * judgement word on an ordinary progression. The branches below turn only on whether a call
 * exists on each side, plus the one status that means *book*.
 *
 * **Withdrawn, not withheld.** The page already says "withheld" of the Model Spread gate
 * refusing a Go Call within a single run. This is a different event — the system changing its
 * mind between runs — and the two must not be able to read as one. #76 is the same problem
 * elsewhere.
 *
 * **It says the tier changed, never why.** `EarlierCall` deliberately drops the reasons and
 * the withholding flags of a superseded call, because rendering a stale explanation beside a
 * current one is worse than rendering none.
 */
function TierChange({ date, before, now }: { date: string; before: CallStatus; now: CallStatus }) {
  if (before === now) return null;

  const label = (status: CallStatus) => CALL_LABELS[status];

  return (
    <p className="tier-change" data-testid={`tier-change-${date}`}>
      {now === 'none' ? (
        <>
          <strong>The {label(before)} on this day has been withdrawn.</strong> The run before called
          it {label(before)}; this one makes no call. Stop watching flights for it.
        </>
      ) : before === 'none' ? (
        <>
          <strong>Newly raised to {label(now)}.</strong> The run before made no call for this day.
        </>
      ) : now === 'go' ? (
        <>
          <strong>Now a Go Call</strong>, where the run before said {label(before)}.
        </>
      ) : (
        <>
          Changed from <strong>{label(before)}</strong> to <strong>{label(now)}</strong> since the
          run before.
        </>
      )}
    </p>
  );
}

/** One run's opinion about a date, reduced to what a series of them is read for. */
interface HistoryPoint {
  /** When the run that said this spoke, or null for the run being read now.
   *
   * One field rather than a flag beside a `'current'` key sentinel. Two fields restating one
   * fact can disagree, and this one answers both questions the row asks — which point is the
   * present, and when the superseded ones spoke.
   *
   * The current call carries no `issued_at` of its own: `DayCall` does not have one, and the
   * run that produced it is dated once at the foot of the range. */
  issuedAt: string | null;
  leadTimeDays: number;
  height: Reading;
  range: HeightRange | null;
  status: CallStatus;
}

/** Every run the page was sent about a date, oldest first, ending with the current one.
 *
 * The current call is built into the same shape rather than rendered separately, because a
 * series that stopped one run short of the present would say nothing about where the forecast
 * has actually arrived — and two shapes for one kind of thing is how the last point ends up
 * formatted differently from the ones before it.
 */
function historyPoints(call: DayCall): HistoryPoint[] {
  return [
    ...call.previous_runs.map((run) => ({
      issuedAt: run.issued_at,
      leadTimeDays: run.lead_time_days,
      height: run.predicted_significant_wave_height,
      range: run.plausible_range,
      status: run.status,
    })),
    {
      issuedAt: null,
      leadTimeDays: call.lead_time_days,
      height: call.predicted_significant_wave_height,
      range: call.plausible_range,
      status: call.status,
    },
  ];
}

/**
 * The shape of a prediction across runs, rather than its last step.
 *
 * Story 22 of #1, whose second clause is the whole of it: *"so that I can tell a firming
 * forecast from a wavering one"*. `Shift` above compares against the run immediately before,
 * which answers "what changed since I last looked" and cannot answer this one — a single step
 * has a direction and no shape. A date the runs took 4.1 → 5.2 → 6.1 → 6.4 m and a date they
 * took 7.9 → 3.4 → 6.1 → 6.4 m drew the identical sentence — both end 0.3 m above the run
 * before — and the first is a swell to book on while the second is a forecast to wait another
 * cycle on. (The two series have to share their *last* value for that to be true, which is
 * what `Shift` compares against and what the fixtures behind this are built to.)
 *
 * The data was already here. The store keeps every call ever made (ADR 0005), `recent_calls`
 * windows the last five per date, and `previous_runs` sends the superseded ones oldest first
 * — and `Shift` read `at(-1)` and dropped the rest.
 *
 * **Every row is dated, and that is not decoration.** Pipeline Runs are three-hourly
 * (`cycle.py`) while `lead_time_days` is a whole number of days, so consecutive runs about one
 * date routinely share a Lead Time: a ladder labelled only by Lead Time prints "6 days out"
 * four times with nothing to order it by. The Lead Time stays because a range narrowing from
 * ten days out to three is the forecast doing its job and the same narrowing at a fixed Lead
 * Time is something else entirely — the two answer different questions and both are needed.
 *
 * **The bar is the shape, the number is the truth.** The story asks a reader to tell firming
 * from wavering *at a glance*, and a column of figures makes them do the comparison the page
 * was supposed to make for them. The bar is scaled against the largest point in this series —
 * the same relative treatment `prominence` uses above, needing no domain knowledge and no
 * calibrated threshold — and is `aria-hidden`, because the heights beside it are what a
 * reader acts on and a screen reader must get those rather than a width.
 *
 * **No verdict is derived.** Naming a series "wavering" would be this layer judging a record
 * it does not own, on a bound nobody has calibrated — how much reversal is wavering? The page
 * derives directional claims only where the numbers visibly support one, as `TrackRecord`'s
 * `verdictAcross` does over a table whose every row is on screen.
 *
 * **Nothing here explains a superseded call.** `EarlierCall` drops the reasons and both
 * withholding flags on purpose — a stale explanation beside a current one is worse than no
 * history — so the series carries heights, ranges and tiers and nothing else.
 *
 * **Two points are not a series.** One previous run is a comparison and `Shift` already makes
 * it in a sentence. The cost is real and worth naming: that one earlier run's plausible range
 * is then rendered nowhere. It is accepted because two points cannot answer the question this
 * section exists for — firming and wavering are indistinguishable across a single step.
 */
function History({ day }: { day: ForecastDay }) {
  const call = day.call;
  if (!call || call.previous_runs.length < 2) return null;

  const points = historyPoints(call);
  const largest = Math.max(...points.map((point) => point.height.value));

  return (
    <section className="history" data-testid={`history-${day.date}`}>
      <h4>How this day has moved across runs</h4>
      <ol>
        {points.map((point, index) => (
          // The index is in the key because `issued_at` is not unique by construction:
          // `store.py` notes that two runs landing inside one second tie on it, and tied keys
          // drop a row. The stamp stays in the key so a re-render that reorders nothing keeps
          // its rows, and the index makes the pair total.
          <li
            key={`${point.issuedAt ?? 'current'}-${index}`}
            className={point.issuedAt === null ? 'current' : undefined}
          >
            <span className="run">
              {point.issuedAt === null ? (
                'this run'
              ) : (
                <time dateTime={point.issuedAt} data-testid="run-issued">
                  {formatTimestamp(point.issuedAt)}
                </time>
              )}
            </span>
            <span className="lead">{point.leadTimeDays} days out</span>
            <span className="track" aria-hidden="true">
              <span
                className="fill"
                style={{ width: `${largest > 0 ? (point.height.value / largest) * 100 : 0}%` }}
              />
            </span>
            <strong>
              <Figure>{formatReading(point.height)}</Figure>
            </strong>
            {/* Not a band of zero width where a call recorded none, which would read as total
                certainty about the oldest and least informed point in the series. Those are
                calls issued before the pipeline built distributions at all. */}
            <span className="range">
              {point.range ? formatRange(point.range) : 'no range recorded'}
            </span>
            <span className={`call call-${point.status}`}>{CALL_LABELS[point.status]}</span>
          </li>
        ))}
      </ol>
      {/* The bound is stated because it is arbitrary, and stated as a bound on the *response*
          rather than on the record. ADR 0005 keeps every call ever made; five per date is
          `recent_calls`' default, and at a three-hourly cadence these rows can span half a day
          of a fortnight-long approach. */}
      <p className="aside">
        The runs this page was sent, oldest first. Every call this system has ever made is kept, so
        this is a recent window on a date that was spoken about far more often than these rows show.
      </p>
      {/* Named here rather than inherited from the panel above, exactly as `Delivered` and the
          range calibration do on the track record. A reader who takes these metres for a wave
          face reads a 6 m series as routine; one who takes it the other way reads it as
          impossible. */}
      <p className="aside">
        Every height here is significant wave height 15km offshore — not the height of a wave face,
        and not convertible to one by any fixed ratio.
      </p>
    </section>
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
 * the row above summarises, so presenting them without that word would leave two swell
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
              <Figure>
                {formatValue(height.spread)}
                {height.unit}
              </Figure>
            </strong>{' '}
            apart on the swell — <Figure>{spreadRange(height)}</Figure>.
            {period?.spread !== null && period !== undefined && (
              <>
                {' '}
                They differ by{' '}
                <Figure>
                  {formatValue(period.spread)}
                  {period.unit}
                </Figure>{' '}
                on the period.
              </>
            )}
            {direction?.spread !== null && direction !== undefined && (
              <>
                {' '}
                On the direction they span <Figure>{spreadRange(direction)}</Figure>.
              </>
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

/** The day's Offshore Conditions, hour by hour — all five of them.
 *
 * **Wind direction is a column because the glossary says it is one (#98).** CONTEXT.md
 * defines Offshore Conditions as swell height, swell period, swell direction, wind speed
 * *and* wind direction, and this table rendered four of the five: the value arrived in every
 * `ForecastHour`, survived the backend under its own test, and was read by nothing. Story 6
 * is what the omission cost — "so that I know when during the day to be at the beach" is,
 * at Praia do Norte, mostly a question about which way the wind is blowing, and a table
 * answering it with a flat column of speeds answers a different question.
 *
 * **It sits inside the wind cell rather than in a sixth column.** The two are one fact: a
 * bearing means something different at 40 km/h than at 4, so separating them across the
 * table would invite reading either alone. It also keeps the table at five columns, which
 * is what makes it usable inside `.hours-scroll` on a phone.
 *
 * **No hour is marked light here, and that is deliberate.** ADR 0009's exemption speed is a
 * fitted threshold in `thresholds.json`; applying it in this layer would reimplement the
 * Heuristic Baseline in the presentation layer — the exact mistake `prominence` above
 * documents having made once — and would put a copy of a calibrated number on a page that
 * ADR 0005 makes a reader. The note under the table says the rule exists without naming its
 * value, so nothing here can drift from the fit.
 */
function HourTable({ day }: { day: ForecastDay }) {
  return (
    <>
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
              {/* "Dir" was unambiguous only while one direction was on the row. With the
                  wind carrying a bearing too, a reader scanning for the wind's has to be
                  able to tell which column is which without counting. */}
              <th scope="col">Swell dir</th>
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
                <td>
                  <Bearing reading={hour.swell_direction} />
                </td>
                <td>
                  {formatValue(hour.wind_speed.value)}
                  <span className="unit">{hour.wind_speed.unit}</span>
                  <Bearing reading={hour.wind_direction} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {/* Outside the scroll container, so a phone cannot scroll the qualification off the
          side of the thing it qualifies. */}
      <p className="aside" data-testid="wind-direction-note">
        A wind light enough not to matter is treated as having no direction at all, so a bearing
        here is a reading rather than a verdict on the hour.
      </p>
    </>
  );
}

/** A run of consecutive days all carrying a call, and the largest day inside it. */
interface SwellWindow {
  days: ForecastDay[];
  peak: ForecastDay;
  goCallDays: number;
}

/** A calendar date as a whole number of days, or null if it is not one.
 *
 * `Date.UTC` is used for the arithmetic and not `new Date(y, m, d)`, because the question is
 * whether two **Nazaré-local days** are adjacent (ADR 0008) and local-time construction makes
 * that depend on the reader's own zone and its daylight saving. Two dates a clock-change apart
 * are 23 or 25 hours apart locally and exactly one day apart on this scale, which is the one
 * the backend grouped them on.
 *
 * The round-trip is not ceremony. `Date.UTC` **rolls over** rather than failing —
 * `Date.UTC(2026, 12, 45)` is a real instant in February 2027 — so a malformed date would
 * otherwise be silently adjacent to something, which is this project's characteristic failure
 * and the same trap `dayLabel` documents.
 */
function dayNumber(date: string): number | null {
  const [year, month, day] = date.split('-').map(Number);
  if (!year || !month || !day) return null;

  const stamp = Date.UTC(year, month - 1, day);
  const back = new Date(stamp);
  if (
    back.getUTCFullYear() !== year ||
    back.getUTCMonth() !== month - 1 ||
    back.getUTCDate() !== day
  ) {
    return null;
  }
  return stamp / 86_400_000;
}

/** Whether a day is one the system has called, as opposed to judged and dismissed.
 *
 * `none` is a verdict and does not belong in a window; `null` is the absence of one. Story 12
 * requires both to keep appearing as themselves in the range below, and neither is a day
 * somebody would fly for. */
function isCalled(day: ForecastDay): boolean {
  return day.call != null && day.call.status !== 'none';
}

/**
 * Consecutive called days, grouped into the thing a person actually books.
 *
 * Story 25 of #1. Nobody flies to Portugal for an afternoon, and #1's solution statement is
 * about committing money to a trip — but the range renders a swell spanning three days as
 * three independent verdicts that happen to sit next to each other.
 *
 * **A quiet day ends a window, and that is the rule that under-claims.** Two Go Calls either
 * side of a day judged `none` may be one swell with a lull or two swells; nothing here can
 * tell them apart, and the page states the rule rather than leaving a reader to infer it. The
 * failure this guards against is somebody booking five nights against a three-night event, so
 * where the two readings differ this takes the shorter one.
 *
 * **A window of one is not a window.** A single called day is already a row in the range, and
 * announcing it as a swell spanning one day is a sentence about nothing.
 *
 * **It invents no status.** The days inside keep their own calls, which is why this returns the
 * days themselves rather than a verdict about them — a window that promoted its members would
 * break story 12 in the one place a reader is most likely to act.
 */
function swellWindows(days: ForecastDay[]): SwellWindow[] {
  const windows: SwellWindow[] = [];
  let run: ForecastDay[] = [];

  const close = () => {
    if (run.length > 1) {
      windows.push({
        // Ties go to the earlier day, which `reduce` gives by keeping the accumulator on
        // equality. Two identical peaks are one swell with a flat top, and naming its first
        // day is the reading that leaves a traveller more room either side.
        peak: run.reduce((best, day) =>
          day.peak_swell_height.value > best.peak_swell_height.value ? day : best,
        ),
        goCallDays: run.filter((day) => day.call?.status === 'go').length,
        days: run,
      });
    }
    run = [];
  };

  for (const day of days) {
    // A quiet day is skipped and does not close the run, because it does not have to: the
    // adjacency test below is what enforces the gap rule. Dropping 14 February leaves the
    // 15th sitting beside the 13th, which are two days apart, so the window ends there anyway.
    //
    // Closing here as well was the first version and it was **unobservable** — no fixture
    // could distinguish the two, which #75's method surfaced immediately. One mechanism that
    // every test can reach beats two where only one is live. It does rest on the range
    // arriving in date order, which is what `/api/conditions/forecast` returns.
    if (!isCalled(day)) continue;

    const previous = run.at(-1);
    const here = dayNumber(day.date);
    const before = previous ? dayNumber(previous.date) : null;
    // A date this cannot place is not adjacent to anything. It still renders as its own row
    // below; it simply cannot be grouped, which is the safe direction.
    if (here === null) {
      close();
      continue;
    }
    if (previous && (before === null || here - before !== 1)) close();
    run.push(day);
  }
  close();

  return windows;
}

/** The two ends of a window — the days a sentence about it names.
 *
 * Both sentences that describe a window take their endpoints from here rather than each
 * indexing the array itself, so "which day does this swell start on" has one answer. */
function spanOf(window: SwellWindow): [ForecastDay, ForecastDay] {
  return [window.days[0]!, window.days[window.days.length - 1]!];
}

/** The windows, above the range, because the answer should not need navigating to (story 28). */
function SwellWindows({ days }: { days: ForecastDay[] }) {
  const windows = swellWindows(days);

  return (
    <section className="windows" aria-labelledby="windows-heading" data-testid="swell-windows">
      <h3 id="windows-heading">Swells spanning more than a day</h3>

      {windows.length === 0 ? (
        // Stated rather than left blank, for story 12's reason one level up: an absent section
        // reads as a page that failed, and "nothing spans more than a day" is a real answer to
        // somebody deciding whether there is a trip here at all.
        <p data-testid="no-windows">
          Nothing in this range runs for more than a single day. There is no multi-day window to
          plan a trip around.
        </p>
      ) : (
        <ul>
          {windows.map((window) => {
            const [first, last] = spanOf(window);
            return (
              <li key={first.date} data-testid={`window-${first.date}`}>
                {/* Each date is a `time` carrying the day it means, so the sentence is
                    machine-readable and its three roles are distinguishable from one another
                    — a locale that renders "13 Feb" and one that renders "Feb 13" must not be
                    the difference between a start date and a peak. */}
                <strong>{window.days.length} days</strong>,{' '}
                <time dateTime={first.date} data-testid="window-start">
                  {dayLabel(first.date)}
                </time>{' '}
                to{' '}
                <time dateTime={last.date} data-testid="window-end">
                  {dayLabel(last.date)}
                </time>
                . The largest swell falls on{' '}
                <strong>
                  <time dateTime={window.peak.date} data-testid="window-peak">
                    {dayLabel(window.peak.date)}
                  </time>
                </strong>
                .{' '}
                {window.goCallDays === 0 ? (
                  <>None of those days carries a Go Call.</>
                ) : (
                  <>
                    {window.goCallDays} of those days{' '}
                    {window.goCallDays === 1 ? 'carries' : 'carry'} a Go Call.
                  </>
                )}
              </li>
            );
          })}
        </ul>
      )}

      <p className="aside">
        A window is an unbroken run of days the system called. A quiet day ends one, so a swell
        either side of a lull is counted as two windows and not one — the reading that risks booking
        too few nights rather than too many. Each day keeps its own verdict in the range below.
      </p>
    </section>
  );
}

/** The span of a window, as the two `time` elements a sentence can be built around.
 *
 * Shared by the statement above and nothing else yet. It exists so the window a Go Call falls
 * inside is rendered from `swellWindows` rather than re-derived — two answers to "which days
 * is this swell" is exactly the drift #85 was written to prevent. */
function WindowSpan({ window }: { window: SwellWindow }) {
  const [first, last] = spanOf(window);

  return (
    <>
      {' '}
      It falls inside a <strong>{window.days.length}-day swell</strong>,{' '}
      <time dateTime={first.date} data-testid="earliest-window-start">
        {dayLabel(first.date)}
      </time>{' '}
      to{' '}
      <time dateTime={last.date} data-testid="earliest-window-end">
        {dayLabel(last.date)}
      </time>
      .
    </>
  );
}

/** What the wave models said, in a clause a reader can act on.
 *
 * Not derivable from anything else on the page, which is why the backend sends it. A day whose
 * own swell period sits below the Go Call bar has every forecaster below it too, so it reports
 * `divided` while the models decided nothing — and two Watch days that look identical from
 * status alone are a swell the forecasters have not settled on and a swell that was never big
 * enough. The verdict is where a reader decides to spend money, so it is said here rather than
 * only inside a panel they have to open.
 *
 * `null` is said rather than skipped. A call issued before the backend consulted the models at
 * all is not a call the models agreed with, and silence reads as agreement.
 */
function ModelVerdict({ agreement }: { agreement: ModelAgreement | null }) {
  // No leading space in these fragments, and the separator is emitted at the call site as an
  // explicit `{' '}` instead. A space that is only there because the string happens to fit on
  // one line is a space Prettier can reflow away, and nothing would catch it: `toHaveTextContent`
  // normalises whitespace, so "models agree.The independent" reads as a pass. `WindowSpan` below
  // already does it this way.
  if (agreement === 'agreed') return <>The independent wave models agree.</>;
  if (agreement === 'divided') return <>The independent wave models are divided about this day.</>;
  if (agreement === 'unmeasured') {
    return <>Whether the wave models are divided could not be measured for this day.</>;
  }
  return <>This call was issued before the wave models were consulted.</>;
}

/**
 * The verdict: the one thing on this page a Traveller came for.
 *
 * Story 23 of #1, rebuilt by #116 as the panel at the top of the left column. It replaces
 * `EarliestWorthActingOn`, which said the date and the Lead Time and stopped there — most of
 * what this says, which is why #116 rather than #119 removed it: shipping both would have left
 * the page telling a reader to book the same day twice, in two voices. Everything below that
 * is not marked as new came with it, because it was right.
 *
 * **Five parts, and the last three are #116's.** The date worth booking, the Lead Time the call
 * was issued at, the predicted Significant Wave Height, the plausible range around it, and
 * whether the wave models agreed.
 *
 * **Significant Wave Height, named in full.** *New.* CONTEXT.md lists "wave height" as
 * ambiguous and "swell height" as a different variable, and this figure sits in the panel a
 * reader reads first. Face Height — the number a reader has seen in news coverage — is several
 * times this for the same sea and is not convertible to it by any fixed ratio, so a verdict
 * that said "7.6m waves" would be the exact overclaim this project exists to avoid. (It is not
 * the largest figure on the page: that is the Significant Wave Height on the tile below, at
 * `--text-figure`. This one sits in a sentence at `--text-small`.)
 *
 * **The range travels with the prediction, and the caveat travels with the range.** *New.* A
 * point estimate alone throws away the Predictive Distribution that is the point of the whole
 * system, and a range presented without saying it prices the height condition alone invites a
 * reader to take it for the chance of a giant day. The spec's rule is that limits qualifying a
 * number stay beside that number; here they stay inside the same panel, at the same weight.
 *
 * **Confirmed is not on this ladder.** It is a short-range statement to somebody already
 * travelling and carries no booking recommendation, so it is not something to act on — and
 * #84 settled that the four statuses have no ordering that could promote it. That is why the
 * quiet sentence says *no Go Call and no Watch* rather than "the range is quiet": a Confirmed
 * day in range would make the second one false, and this sits above the range that would
 * contradict it.
 *
 * **The date leads and the window follows, which is the arguable half of #86.** The ticket says
 * the earliest thing worth acting on is a window rather than a date, and a window is indeed
 * what somebody books — but only the Go Call day is a recommendation to spend money. A
 * sentence opening "book the three-day swell" would be recommending nights against days that
 * carry a Watch, which is the over-claim #85 took the shorter reading to avoid. So the Go Call
 * is the commitment, the window is the shape around it, and the two compose in that order
 * rather than competing.
 *
 * **The Lead Time is `lead_time_days` and is not a countdown.** `DayCall` fixes it when the
 * call is issued rather than recomputing it against the clock, so it is stated as *issued three
 * days ahead* and never as "in three days" — which would be a claim about today that this
 * number does not make.
 *
 * **It does not restate staleness.** If the store is old the top of the page already says so
 * (story 10), and this renders below that banner. Nothing but document order holds that; the
 * App suite is what reads it.
 *
 * **Earliest means first in the range**, which arrives in date order from
 * `/api/conditions/forecast` — the same assumption `swellWindows` rests on.
 */
function Verdict({ days }: { days: ForecastDay[] }) {
  const first = (status: CallStatus) => days.find((day) => day.call?.status === status) ?? null;

  const go = first('go');
  const watch = go ? null : first('watch');
  const day = go ?? watch;
  // Named for what it is rather than `window`, which would shadow the browser global in a
  // component whose other reads are all of the DOM's.
  const containing = day ? (swellWindows(days).find((w) => w.days.includes(day)) ?? null) : null;
  const call = day?.call ?? null;

  return (
    <section
      className={`verdict verdict-${call?.status ?? 'none'}`}
      data-testid="verdict"
      aria-labelledby="verdict-heading"
    >
      {day === null || call === null ? (
        <>
          <h2 id="verdict-heading" className="verdict-headline">
            Nothing to book yet.
          </h2>
          {/* An answer, not a warning. Given `role="alert"` it would read as the system failing
              to forecast rather than the ocean being ordinary, and this is the truthful answer
              most weeks of the year. */}
          <p className="verdict-detail">
            No day in the next {days.length} days carries a Go Call or a Watch. That is the ordinary
            state of this coast rather than a gap in the forecast — most weeks of the year say
            exactly this.
          </p>
        </>
      ) : (
        <>
          {/* Not `{CALL_LABELS[status]} Call`, which renders the Watch branch as "Watch Call".
              CONTEXT.md keeps Watch and Go Call as separate entries on purpose — one says start
              paying attention, the other says spend money — and "Watch Call" is a coined term
              that appears nowhere else in the repo. It reads as a weaker Go Call, which is the
              one thing a Watch must never be mistaken for. */}
          <p className="verdict-status">
            {go ? 'Go Call' : 'Watch'} · issued {call.lead_time_days}{' '}
            {call.lead_time_days === 1 ? 'day' : 'days'} ahead
          </p>

          <h2 id="verdict-heading" className="verdict-headline">
            {go ? (
              <>
                Book for{' '}
                <time dateTime={go.date} data-testid="earliest-date">
                  {dayLabel(go.date)}
                </time>
                .
              </>
            ) : (
              <>
                Nothing to book yet — the earliest day worth attention is{' '}
                <time dateTime={day.date} data-testid="earliest-date">
                  {dayLabel(day.date)}
                </time>
                .
              </>
            )}
          </h2>

          <p className="verdict-detail">
            Predicted{' '}
            <strong>
              <Figure>{formatReading(call.predicted_significant_wave_height)}</Figure>
            </strong>{' '}
            significant wave height
            {call.plausible_range && (
              <>
                , plausibly{' '}
                <strong>
                  <Figure>{formatRange(call.plausible_range)}</Figure>
                </strong>
              </>
            )}
            {call.height_bar_probability !== null && (
              <>
                {' '}
                — about{' '}
                <strong>
                  <Figure>{Math.round(call.height_bar_probability * 100)}%</Figure>
                </strong>{' '}
                likely to clear the minimum significant wave height a giant day needs
              </>
            )}
            . <ModelVerdict agreement={call.model_agreement} />
            {watch && ' Start watching flights; do not book on it.'}
            {containing && <WindowSpan window={containing} />}
          </p>

          {/* #66 and ADR 0004. A giant day needs four quantities to hold — height, swell
              period, swell direction and wind — and the distribution prices one; the other
              three have no archived forecast error to build a distribution from.

              **It names both figures, because both price height alone.** #116 asks for "the
              height-only caveat on the probability" and the first draft attached it to the
              plausible range, which is true of the range and quietly silent about the
              percentage — the figure a reader is most likely to read as the chance of a giant
              day. Rendered from the same guard as the figures above, so the caveat cannot
              outlive what it caveats, and in the same panel at the same size rather than below
              the fold: a redesign is exactly the change that turns a disclaimer into elegant
              grey fine print. */}
          {(call.plausible_range || call.height_bar_probability !== null) && (
            <p className="verdict-scope">
              Height only — the swell period, swell direction and wind a giant day also needs are
              priced in{' '}
              {call.plausible_range && call.height_bar_probability !== null
                ? 'neither that range nor that figure'
                : call.plausible_range
                  ? 'no part of that range'
                  : 'no part of that figure'}
              .
            </p>
          )}

          {/* Past the archive's seven days the width is an extrapolation, and an extrapolation
              rendered identically to a measurement is the failure the flag exists to prevent.
              It arrives as a flag rather than being inferred from the Lead Time, because
              inferring it means keeping a copy here of how deep the archive currently is. */}
          {call.uncertainty_measured === false && (
            <p className="verdict-scope">
              Nothing has been measured about how wrong a forecast this far ahead tends to be, so
              that range is extrapolated rather than observed.
            </p>
          )}
        </>
      )}
    </section>
  );
}

/**
 * The forecast section: the verdict, the windows, the days, and what a selected day opens into.
 *
 * **`belowVerdict` is a slot, and it exists because the page interleaves three fetches.** The spec's
 * order down the left column is verdict, then the four condition tiles, then the day list — and
 * the verdict and the day list come from `/api/conditions/forecast` while the tiles come from
 * `/api/conditions/current` and the range admission beside the verdict comes from
 * `/api/track-record`. Something has to sit between two things this component owns.
 *
 * It was called `tiles` while the tiles were the only thing in it. #119 put the range-runs-wide
 * admission in there too — a limit that has to sit beside the range the verdict prints — so the
 * name now says where the slot is rather than what happens to be in it.
 *
 * A slot rather than lifting the fetch into `Home`: this component is rendered bare, as
 * `<ForecastRange />`, at 74 places across two suites (72 in `Forecast.test.tsx`, 2 in
 * `every-field-is-read.test.tsx`), with msw at the network boundary. That is the seam this repo tests at, and turning it into a presentational component
 * fed fixtures directly would trade a tested boundary for a prop. The slot is optional, so every
 * one of those call sites still renders what it always did.
 */
/**
 * The swell windows, on the reading page (#119).
 *
 * **Why it is not on the forecast page any more.** Spec §2 lists five things down the home
 * column — the verdict, the four tiles, the days, the hours, and one line of track record — and
 * this was a sixth. Its actionable half is already in the verdict, which names the window a Go
 * Call falls inside; what is left is the enumeration of every window in range and the paragraph
 * explaining what a window is, and the second of those is teaching material by #119's own rule.
 * Ruled 2026-09-19 to move the panel whole rather than split it, so the list and the sentence
 * that explains the list stay together.
 *
 * **It fetches the forecast itself**, which is the one cost of the move: this page otherwise
 * reads only `/api/track-record`. Passing the days down from the forecast page is not available
 * — they are different routes — and deriving windows from the track record would be a second
 * answer to "which days is this swell", which is exactly the drift #85 was written to prevent.
 */
export function SwellWindowsSection() {
  const [state, setState] = useState<LoadState>({ status: 'loading' });

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

  // An alert rather than nothing. This page is reachable when the forecast service is down, and
  // a section that silently disappears reads as a page that failed to load rather than as one
  // part of it being unavailable.
  if (state.status === 'failed') {
    return (
      <p role="alert" className="alert">
        Could not load the forecast, so there is nothing to say about swell windows right now.
      </p>
    );
  }

  return <SwellWindows days={state.forecast.days} />;
}

export function ForecastRange({ belowVerdict }: { belowVerdict?: ReactNode }) {
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

  // The slot renders in every state, including the two where this component has no forecast.
  // The tiles are current conditions and come from a different request: a forecast that is slow,
  // or a forecast endpoint that is down, must not take the sea's present state off the page with
  // it. ADR 0005's promise is that the site stays up and honest when a provider is unreachable,
  // and a page that answered "could not load the forecast" while silently also dropping ten
  // readings it *had* would be neither.
  const forecast = state.status === 'loaded' ? state.forecast : null;
  const open = forecast?.days.find((day) => day.date === openDate) ?? null;
  const largest = forecast
    ? Math.max(...forecast.days.map((day) => day.peak_swell_height.value))
    : 0;

  /*
   * One tree in every state, rather than an early return per state.
   *
   * **`tiles` has to keep the same position in the tree across all three.** It is the four
   * condition tiles, which come from a different request than everything else here, and when it
   * was rendered from three separate `return`s React tore the subtree down and rebuilt it the
   * moment the forecast landed. Nothing looked wrong in a screenshot; what it cost was that the
   * tiles a reader was already looking at were replaced by identical new ones, and any handle on
   * them — a test's, a screen reader's cursor — pointed at detached nodes.
   *
   * **It renders even when this component has no forecast at all.** ADR 0005's promise is that
   * the site stays up and honest when a provider is unreachable. A forecast endpoint that is
   * slow or down must not take the sea's present state off the page with it, and a page saying
   * "could not load the forecast" while silently also dropping ten readings it *had* would be
   * neither up nor honest.
   */
  return (
    <section
      className="forecast"
      aria-labelledby={forecast ? 'forecast-heading' : undefined}
      aria-label={forecast ? undefined : 'Forecast'}
    >
      {state.status === 'loading' && <p>Loading forecast...</p>}

      {state.status === 'failed' && (
        <p role="alert" className="alert">
          Could not load the forecast. The service may be unavailable, or no pipeline run has stored
          one yet.
        </p>
      )}

      {forecast && (
        /* First on the page, above everything including the heading that used to sit over it: a
           reader who takes one sentence from here should take this one. "The next 16 days" was
           rendered above the verdict while it labelled the section as a whole, which put a
           heading about a list over the answer the list exists to produce. It now sits with the
           list it names, which is also the order the spec sets out — verdict, tiles, days. */
        <Verdict days={forecast.days} />
      )}

      {belowVerdict}

      {forecast && (
        <>
          <h2 id="forecast-heading">The next {forecast.days.length} days</h2>

          <DayList
            days={forecast.days}
            largest={largest}
            openDate={openDate}
            onSelect={(date) => setOpenDate(date === openDate ? null : date)}
          />

          {open ? (
            <>
              <CallDetail day={open} model={forecast.amplification_model} />
              <Agreement day={open} />
              <HourTable day={open} />
            </>
          ) : (
            <p className="hint">Select a day to see how it develops hour by hour.</p>
          )}

          {/* **The limit stays; the explanation moved (#119).**

              What these two sentences do is tell a reader what the calls above them rest on and
              how far to trust them, which is a limit qualifying every call on the page. What
              they used to also do is explain why the number of days is so small — that far more
              giant days are on record than the swell measurements these calls are written in
              reach back to cover. That is how it was computed rather than what it means, so it
              is on the reading page now, under the same numbers.

              All three counts stay here. They are what "how thin the basis is" is made of, and
              a limit that said "fitted to a small number of days" without saying how small would
              be the vaguer, more comfortable version of the same sentence. */}
          {!forecast.calibrated && (
            <p role="status" className="alert">
              These calls come from the surf community's rule of thumb, not from thresholds fitted
              to days Nazaré is known to have gone giant. Treat them as a starting point rather than
              a forecast. <a href={ADDRESS['how-it-works']}>How the calls are made</a>.
            </p>
          )}

          {forecast.calibrated && forecast.calibration && (
            <p role="status" className="alert">
              These thresholds were fitted to {forecast.calibration.gold_days_total} days Nazaré is
              known to have gone giant — {forecast.calibration.gold_days_fitted} to choose them and{' '}
              {forecast.calibration.gold_days_validated} held back to check them. Expect the calls
              to be roughly right and individually uncertain.{' '}
              <a href={ADDRESS['how-it-works']}>How the thresholds were fitted</a>.
            </p>
          )}

          <p className="provenance">
            Forecast fetched {formatTimestamp(forecast.fetched_at)}. The range ends where the
            provider stops modelling swell, which is sooner than its wind forecast.
          </p>
        </>
      )}
    </section>
  );
}

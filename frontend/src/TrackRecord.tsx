import { useEffect, useState } from 'react';

import {
  fetchTrackRecord,
  type AccuracyBand,
  type CallStatus,
  type PanelRecord,
  type RangeCalibration,
  type RangeCoverage,
  type TierRecord,
  type TrackRecord,
} from './api';

type LoadState =
  { status: 'loading' } | { status: 'loaded'; record: TrackRecord } | { status: 'failed' };

const CALL_LABELS: Record<CallStatus, string> = {
  confirmed: 'Confirmed',
  go: 'Go',
  watch: 'Watch',
  none: 'No call',
};

/** A share as a whole percentage.
 *
 * Whole numbers deliberately. A precision quoted as 20.93% claims a resolution that
 * nine days out of forty-three cannot support, and the extra digits read as confidence.
 */
function percent(share: number): string {
  return `${Math.round(share * 100)}%`;
}

/** A count to one decimal, for figures that are averages over seasons rather than counts. */
function perSeason(value: number): string {
  return value.toFixed(1);
}

function metres(value: number): string {
  return `${value.toFixed(2)}m`;
}

/** A signed metre difference, where the sign is the point.
 *
 * Always explicitly signed. "0.32m better" and "0.32m worse" differ by one word in prose
 * and by a character here, and this column is scanned rather than read.
 */
function signedMetres(value: number): string {
  return `${value >= 0 ? '+' : '−'}${Math.abs(value).toFixed(3)}m`;
}

/**
 * One tier's row: how many of the days that mattered it caught, and what it cost.
 *
 * Recall and cost are shown together and never apart. A tier catching 12 of 13 confirmed
 * giant days sounds excellent until you learn it flagged 193 days to do it, and a reader
 * shown only the first number has been told the flattering half of a two-part fact.
 */
function TierRow({ label, meaning, tier }: { label: string; meaning: string; tier: TierRecord }) {
  return (
    <div className="tier" role="group" aria-label={label}>
      <h4>{label}</h4>
      <p className="tier-meaning">{meaning}</p>
      <dl>
        <div>
          <dt>Giant days it caught</dt>
          <dd>
            <strong>
              {tier.gold_days_called} of {tier.gold_days_in_panel}
            </strong>{' '}
            <span className="aside">({percent(tier.recall)})</span>
          </dd>
        </div>
        <div>
          <dt>Days it flagged to do it</dt>
          <dd>
            <strong>{tier.days_flagged}</strong>{' '}
            <span className="aside">
              about {perSeason(tier.flags_per_big_wave_season)} per Big-Wave Season
            </span>
          </dd>
        </div>
        <div>
          <dt>Flagged days that were wasted</dt>
          <dd>
            <strong>
              at most {tier.days_wasted_upper_bound} of {tier.days_flagged}
            </strong>{' '}
            <span className="aside">({percent(tier.wasted_upper_bound)})</span>
          </dd>
        </div>
        {/* Directly under the waste figure, which is the only place it belongs. That figure
            is scored against ratified giant days — a bar high enough that this tier reads as
            94% wasted while never having flagged a day the sea stayed below 2.72m. A reader
            scanning the panel meets the harsh number and the measured one together, or the
            harsh one alone. Absent for a tier the record publishes no delivery for. */}
        {tier.delivered && (
          <div>
            <dt>Lowest sea any of them reached</dt>
            <dd>
              <strong>{metres(tier.delivered.minimum_m)}</strong>{' '}
              <span className="aside">
                median {metres(tier.delivered.median_m)}, Significant Wave Height
              </span>
            </dd>
          </div>
        )}
      </dl>
    </div>
  );
}

/** What the sea did on the days a tier flagged — the counterweight to the waste statement.
 *
 * **This must never be rendered without the waste statement above it, and vice versa.** The two
 * answer different questions about one set of days and each misleads alone, in opposite
 * directions. Waste is scored against ratified giant days, a bar so high that a rule flagging
 * nothing but excellent days still reads as 79% wasted; this says what the ocean actually did,
 * and on its own it would read as a system that never misses.
 *
 * **The minimum is the headline and the ladder is the detail.** "No Go Call landed on a day the
 * sea peaked below 2.82m" is one number, checkable, and the strongest true sentence available
 * here. A percentage in its place would invite a reader to wonder about the other tail; there
 * isn't one.
 *
 * **Every metre here is Significant Wave Height.** The page says elsewhere, at length, that it
 * does not predict the height of a wave face — so this section names the quantity in its own
 * heading rather than relying on a reader having arrived from there. The failure mode is
 * specific: a reader who takes "above 4m" as a wave face reads a 4m sea as a small day, and one
 * who takes it the other way books a flight on a number that means something else.
 *
 * Renders nothing when the record publishes no delivery for this tier, which is the Watch tier
 * today. Nothing rather than an empty section: a heading with no figures under it reads as a
 * page that broke, and the absence has a reason the backend records.
 */
function Delivered({ tier }: { tier: TierRecord }) {
  const delivered = tier.delivered;
  if (!delivered) return null;

  return (
    <section data-testid="delivered">
      <h3>And what did the sea actually do on those days?</h3>
      <p data-testid="delivered-statement">
        The figure above asks whether a day was <em>recorded</em> as giant. This asks whether the
        ocean showed up. Across the same <strong>{tier.days_flagged}</strong> Go Calls, the lowest
        peak any of them landed on was <strong>{metres(delivered.minimum_m)}</strong> of Significant
        Wave Height — not one landed on a flat day — and the median was{' '}
        <strong>{metres(delivered.median_m)}</strong>.
      </p>
      <ul data-testid="delivered-ladder">
        {delivered.above.map((step) => (
          <li key={step.metres} data-testid={`delivered-above-${step.metres}`}>
            <strong>
              {step.days} of {step.of_days}
            </strong>{' '}
            peaked above {metres(step.metres)}{' '}
            <span className="aside">({percent(step.share)})</span>
          </li>
        ))}
      </ul>
      <p className="aside">
        Significant Wave Height at the buoy, not the height of a wave face — the distinction below
        applies to every number in this section. And a record of what past calls landed on, scored
        against a reconstruction of conditions as they turned out. It is not a promise about the
        next one.
      </p>
    </section>
  );
}

/** One span, with both tiers. Never one tier, and never the two averaged together. */
function Panel({
  panel,
  caption,
  testId,
}: {
  panel: PanelRecord;
  caption: string;
  testId: string;
}) {
  return (
    <div className="panel" data-testid={testId}>
      <p className="panel-caption">
        {caption} — <strong>{panel.span}</strong>, containing {panel.gold_days} independently
        confirmed giant days across {panel.big_wave_seasons} Big-Wave Seasons.
      </p>
      <div className="tiers">
        <TierRow
          label="Watch"
          meaning="Start paying attention. Deliberately set wide: missing a swell that is forming is worse than watching one that fades."
          tier={panel.watch_or_better}
        />
        <TierRow
          label="Go Call"
          meaning="Book the flight. Set narrow on purpose, because a wrong one costs real money."
          tier={panel.go_call}
        />
      </div>
    </div>
  );
}

/**
 * Both models' error, band by band.
 *
 * The component takes the whole band and renders both columns from it, so there is no
 * arrangement of props that shows one model without the other. ADR 0006 requires the
 * Heuristic Baseline beside every accuracy figure this project reports, and a rule kept by
 * the shape of the data needs nobody to remember it.
 */
function AccuracyTable({
  bands,
  caption,
  testId,
}: {
  bands: AccuracyBand[];
  caption: string;
  testId: string;
}) {
  return (
    <div className="record-table" data-testid={testId}>
      <table>
        <caption>{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Sea size</th>
            <th scope="col">Hours</th>
            <th scope="col">Rule of thumb</th>
            <th scope="col">Learned model</th>
            <th scope="col">Difference</th>
          </tr>
        </thead>
        <tbody>
          {bands.map((band) => (
            <tr key={band.name}>
              <th scope="row">{band.name}</th>
              <td>{band.hours.toLocaleString('en-GB')}</td>
              <td>{metres(band.baseline_mae_m)}</td>
              <td>{metres(band.learned_mae_m)}</td>
              <td className={band.gain_m >= 0 ? 'better' : 'worse'}>{signedMetres(band.gain_m)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {/* Rendered under the table it qualifies, in full, not as a marker a reader has to
          chase. The whole point of these two is that the figure above reads as stronger than
          it is, so a footnote they have to go and find is a footnote that has failed. */}
      {bands.some((band) => band.caveat) && (
        <ul className="band-caveats">
          {bands
            .filter((band) => band.caveat)
            .map((band) => (
              <li key={band.name}>
                <strong>{band.name}:</strong> {band.caveat}
              </li>
            ))}
        </ul>
      )}
    </div>
  );
}

/** Which side of its own claim one measurement falls on.
 *
 * The tolerance is a whole percentage point, because the figures are rendered as whole
 * percentages. A range measured at 90.4% against a claim of 90% is not a finding, and calling
 * it one would put a verdict on the page that the numbers under it do not visibly support.
 */
function side(claimed: number, covered: number): 'wide' | 'narrow' | 'calibrated' {
  if (Math.abs(covered - claimed) < 0.01) return 'calibrated';
  return covered > claimed ? 'wide' : 'narrow';
}

/**
 * Which way the range misses across the whole table, worked out here rather than read off a
 * field.
 *
 * The backend sends the claim and the measurement and no verdict, because the verdict is the
 * thing most likely to stop being true: narrowing the distribution is open work, and a "too
 * wide" flag baked into the record would survive the change that falsified it.
 *
 * **Every lead time is read, not the first one.** A sentence above a seven-row table speaks
 * for all seven, and the repair this measurement invites is expected to be uneven — the
 * excess is 0.82 of the required half-width at one day and 0.53 at seven, so a refit that
 * corrects the far rows and leaves the near ones would produce exactly the table where one
 * row's verdict is a lie about the others. `mixed` is that case, said plainly.
 */
function verdictAcross(
  claimed: number,
  leads: RangeCalibration['leads'],
): ReturnType<typeof side> | 'mixed' {
  const sides = new Set(leads.map((lead) => side(claimed, lead.all_hours.covered)));
  if (sides.size > 1) return 'mixed';
  return sides.values().next().value ?? 'calibrated';
}

/**
 * Whether the gap between the range and the outcomes grows as the forecast reaches further.
 *
 * The second directional claim on this page, and it needs deriving for a sharper reason than
 * the first: the growth *rate* is what the open repair is aimed at. A page asserting "and
 * increasingly so the further ahead it looks" in its own copy would be asserting precisely
 * the clause a refit is most likely to falsify, above a table that had stopped supporting it.
 *
 * Read off the widening factor rather than the widths, because the widths grow with lead time
 * whether or not the *excess* does. A tenth of the half-width is the smallest gap worth a
 * sentence.
 */
function excessGrowsWithLeadTime(leads: RangeCalibration['leads']): boolean {
  const first = leads[0];
  const last = leads[leads.length - 1];
  if (!first || !last || leads.length < 2) return false;
  return first.all_hours.widening_factor - last.all_hours.widening_factor > 0.1;
}

/** One subset's rows: how often the range held, and the width that would have sufficed. */
function RangeTable({
  leads,
  caption,
  subset,
  testId,
}: {
  leads: RangeCalibration['leads'];
  caption: string;
  subset: 'all_hours' | 'big_swell';
  testId: string;
}) {
  return (
    <div className="record-table" data-testid={testId}>
      <table>
        <caption>{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Days ahead</th>
            <th scope="col">Hours</th>
            <th scope="col">How often it held</th>
            <th scope="col">Range it prints</th>
            <th scope="col">Range that would have sufficed</th>
          </tr>
        </thead>
        <tbody>
          {leads.map((lead) => {
            const measured: RangeCoverage = lead[subset];
            return (
              <tr key={lead.lead_days}>
                <th scope="row">{lead.lead_days}</th>
                <td>{measured.hours.toLocaleString('en-GB')}</td>
                <td>{percent(measured.covered)}</td>
                <td>{metres(measured.median_width_m)}</td>
                <td>{metres(measured.justified_width_m)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Whether the range this site prints means what it says.
 *
 * **The one figure on this page scored against the sea rather than against the confirmed
 * giant days.** Everything else here is measured against a hand-assembled list of thirteen
 * days. This is measured against 1,593 hours of what the ocean actually did, which makes it
 * the broadest evidence on the page — and the two qualifications underneath are why that is
 * not the licence it sounds like.
 *
 * **Both subsets are rendered from one component, and there is no arrangement of props that
 * shows one without the other.** The big-swell rows cover the bigger seas and read kinder than
 * the whole, so a page able to show them alone is a page able to show the flattering half of a
 * two-part fact — the rule `TierRow` and `Delivered` already keep.
 *
 * **Both directional sentences are derived from the numbers they sit above** — which way the
 * range misses, and whether the miss grows with lead time. Narrowing the distribution is open
 * work, and the growth rate is the part of it most likely to move, so a page asserting either
 * in its own copy would survive the refit that made it false and be wrong in the direction of
 * confidence.
 */
function RangeCalibrationSection({ calibration }: { calibration: RangeCalibration }) {
  const shortest = calibration.leads[0];
  const longest = calibration.leads[calibration.leads.length - 1];

  // The backend refuses a record with no lead times, so this is unreachable through the
  // running system — but it is reachable through the type, and the honest answer to "we have
  // no measurement" is not to drop the heading. A section that quietly disappears leaves a
  // page printing a range with nothing said about it, which is the state this whole section
  // exists to end.
  if (!shortest || !longest) {
    return (
      <section data-testid="range-calibration">
        <h3>Does the range it prints mean what it says?</h3>
        <p role="alert" className="alert">
          The measurement of the range could not be read. Do not take this as the range being
          calibrated — it has been measured against outcomes, and this page failed to load the
          result.
        </p>
      </section>
    );
  }

  const verdict = verdictAcross(calibration.claimed, calibration.leads);
  const grows = excessGrowsWithLeadTime(calibration.leads);

  return (
    <section data-testid="range-calibration">
      <h3>Does the range it prints mean what it says?</h3>
      <p data-testid="range-statement">
        Every forecast on this site states a range in metres of Significant Wave Height, and that
        range claims to contain the real sea <strong>{percent(calibration.claimed)}</strong> of the
        time. Measured against <strong>{shortest.all_hours.hours.toLocaleString('en-GB')}</strong>{' '}
        hours of what the ocean then did, it held the outcome{' '}
        <strong>{percent(shortest.all_hours.covered)}</strong> of the time {shortest.lead_days} day
        ahead and <strong>{percent(longest.all_hours.covered)}</strong> of the time{' '}
        {longest.lead_days} days ahead.
      </p>
      {verdict === 'calibrated' ? (
        <p data-testid="range-verdict">
          That is the share it claims, at every lead time, so the range means what it says — on this
          evidence, and subject to the two limits below.
        </p>
      ) : verdict === 'mixed' ? (
        // The table disagrees with itself, so no single sentence is true of it. Said rather
        // than resolved: picking the worst row would overstate and picking the best would
        // flatter, and a reader owed one number is better owed the table.
        <p data-testid="range-verdict">
          <strong>The answer differs by how far ahead the forecast looks</strong>, so there is no
          single figure for it — the range holds more often than it claims at some lead times and
          less often at others. The tables below are the answer, row by row.
        </p>
      ) : verdict === 'wide' ? (
        <p data-testid="range-verdict">
          <strong>So the range is wider than the outcomes justify</strong>
          {grows ? ', and increasingly so the further ahead it looks' : ''}: a {longest.lead_days}
          -day range spanning {metres(longest.all_hours.median_width_m)} would have held the same
          share of outcomes at {metres(longest.all_hours.justified_width_m)}. That is the error
          running in the forgiving direction — the system claims less certainty than it turns out to
          have, so it stays quiet on days it could have called rather than calling days it should
          not. It is still a statement that is not true, which is why it is on this page.
        </p>
      ) : (
        <p data-testid="range-verdict">
          <strong>So the range is narrower than the outcomes justify.</strong> The sea fell outside
          it more often than the {percent(calibration.claimed)} it claims, which means the range
          states more certainty than the record supports — the expensive direction for a page that
          is asking you to book a flight on it.
        </p>
      )}

      <RangeTable
        leads={calibration.leads}
        subset="all_hours"
        testId="range-all-hours"
        caption="Every hour measured"
      />
      {/* The bar is read off the record, never typed. It is the sea the report drew this
          subset at — deliberately not described as the bar a Go Call rests on, which is
          2.75m and a different number. Calling it that would put a false statement about
          the Go Call on the page this section exists to make honest. */}
      <RangeTable
        leads={calibration.leads}
        subset="big_swell"
        testId="range-big-swell"
        caption={`Only the hours the buoy measured at ${metres(
          calibration.big_swell_from_m,
        )} or more — the bigger seas, and the kinder of the two`}
      />

      {/* Rendered under the tables, in full. Both say the figures above are narrower evidence
          than "1,593 hours" sounds, and a reader who meets that after forming an impression
          has met it too late. Same reason the basis caveat sits above the panels. */}
      <ul className="band-caveats" data-testid="range-caveats">
        <li>{calibration.understates_because}</li>
        <li>{calibration.rests_on}</li>
      </ul>
      {/* Named in this section rather than inherited from the one above it, exactly as
          `Delivered` does. A reader who takes these metres for a wave face reads a 2m range
          as trivial; one who takes it the other way reads it as enormous. */}
      <p className="aside" data-testid="range-quantity">
        Every metre in this section is Significant Wave Height at the buoy — the whole sea, 15km
        offshore — not the height of a wave face, and not convertible to one by any fixed ratio.
      </p>
    </section>
  );
}

export function TrackRecordPage() {
  const [state, setState] = useState<LoadState>({ status: 'loading' });

  useEffect(() => {
    let active = true;
    fetchTrackRecord()
      .then((record) => active && setState({ status: 'loaded', record }))
      .catch(() => active && setState({ status: 'failed' }));
    return () => {
      active = false;
    };
  }, []);

  if (state.status === 'loading') {
    return (
      <section aria-labelledby="track-record-heading">
        <h2 id="track-record-heading">Track record</h2>
        <p>Loading the track record...</p>
      </section>
    );
  }

  if (state.status === 'failed') {
    return (
      <section aria-labelledby="track-record-heading">
        <h2 id="track-record-heading">Track record</h2>
        {/* Never a blank section. A track record that renders with nothing on it is
            indistinguishable from a system with nothing to show for itself, and the
            silent version is the flattering one. */}
        <p role="alert" className="alert">
          Could not load the track record. Nothing here should be read as an absence of failures —
          the record exists and this page could not fetch it.
        </p>
      </section>
    );
  }

  const { record } = state;
  const goCall = record.held_out.go_call;

  return (
    <section aria-labelledby="track-record-heading" className="track-record">
      <h2 id="track-record-heading">Track record</h2>

      {/* The span and the season count are read off the record rather than written here.
          A literal "fifteen years" is the same defect as the "at least six hours" that was
          once typed into the footer: it survives the data changing underneath it, and a page
          asserting a span the figures no longer cover is wrong in the direction of
          confidence. */}
      <p className="lead">
        Before trusting any of this with a flight, here is what the system would have said over{' '}
        {record.full_record.span} — {record.full_record.big_wave_seasons} Big-Wave Seasons of
        reconstructed conditions — and what actually happened on those days.
      </p>

      {/* Stated once, at the top, before any number. Every figure below is the rule applied
          to a reconstruction of conditions as they turned out to be — which no forecast can
          give you in advance. A reader who meets that caveat at the bottom of the page has
          already formed an impression from figures that are better than the system's real
          ones. */}
      <p className="caveat" data-testid="basis-caveat">
        <strong>These are reconstructed calls, not a live record.</strong> They come from the{' '}
        {record.held_out.basis} — the conditions as they actually turned out, assembled afterwards.
        A real forecast is less certain than that, so treat every figure here as the system at its
        best rather than as what it will do next winter.
      </p>
      {/* The specific form that "at its best" takes, rather than leaving it as a feeling.
          A live Go Call must clear two conditions beyond the rule — the forecasters agreeing,
          and enough of the predicted range sitting above the height bar — and neither can exist
          in a reconstruction of a day that has already happened. So every Go Call counted below
          skipped both.

          Neither is described as the system being "confident". ADR 0014 renamed this gate off
          that word precisely because the glossary assigns it to the models' agreement — which is
          the other gate in this very sentence — so using it here would collapse the two the
          sentence exists to hold apart.

          Stated qualitatively and without figures on purpose: both costs are measured, but over
          different and shorter spans than these panels cover, and printing them here would
          invite a reader to subtract one from the other. */}
      <p className="caveat" data-testid="gates-caveat">
        <strong>Two conditions a real Go Call must clear are missing from these.</strong> The
        running system also asks the independent forecasters to agree about the day, and asks that
        enough of its own predicted range sits above the height bar. Neither question exists for a
        day that has already happened, so no call below was ever asked them. Both have been measured
        separately, and both withhold a small number of days — but on shorter spans than this page
        covers, which is why no figure for them appears beside these.
      </p>

      <h3>Did it see the days that mattered?</h3>
      <p>
        The comparison is against days independently confirmed as genuinely giant — contests that
        ran, records that were ratified. There are only{' '}
        <strong data-testid="gold-day-total">{record.gold_days_total}</strong> of them in the whole
        record, and {record.gold_days_fitted} were used to choose the thresholds, which leaves{' '}
        <strong>{record.gold_days_validated}</strong> the system had never seen. That is a small
        number, and it is the entire basis of everything on this page.
      </p>

      <Panel
        panel={record.held_out}
        testId="panel-held-out"
        caption="Days the thresholds were never fitted on — the figure to judge it by"
      />
      <Panel
        panel={record.full_record}
        testId="panel-full-record"
        caption="The whole record, which includes the days the thresholds were chosen against"
      />

      <h3>How often would a Go Call have been wasted?</h3>
      <p data-testid="waste-statement">
        On the days it had never seen, the system issued <strong>{goCall.days_flagged}</strong> Go
        Calls and <strong>{goCall.gold_days_called}</strong> of them landed on a day independently
        confirmed as giant. So{' '}
        <strong>
          at most {goCall.days_wasted_upper_bound} of {goCall.days_flagged} trips —{' '}
          {percent(goCall.wasted_upper_bound)} — would have been wasted
        </strong>
        . At most, because the confirmed list is hand-assembled from contests and records rather
        than a census: some of those {goCall.days_wasted_upper_bound} days may have been genuinely
        giant with nobody there to write it down. The true figure can only be kinder, and it is
        quoted the unkind way round because this number is asking you to spend money.
      </p>

      <Delivered tier={goCall} />

      <h3>How close was the predicted size?</h3>
      <p>
        Two models, always shown together. The <strong>rule of thumb</strong> is the surf
        community&apos;s, with no learning in it; the <strong>learned model</strong> is fitted on
        buoy readings from the seasons above. The rule of thumb is kept permanently as the thing any
        learned model has to beat, so no accuracy figure here appears without it.
      </p>
      <p>
        The numbers are average error in metres against the buoy, so <em>lower is better</em> and
        the last column is the learned model&apos;s margin over the rule of thumb.
      </p>

      <AccuracyTable
        bands={record.scored}
        testId="scored-accuracy"
        caption="Both models reading the reconstruction directly — what the fit is worth"
      />
      <AccuracyTable
        bands={record.served}
        testId="served-accuracy"
        caption="The same comparison along the path the running system actually takes"
      />

      <p>
        The two tables disagree, and the disagreement is the honest finding rather than something to
        tidy away. Along the path the running system takes, the learned model must first restate a
        forecast into the units it was fitted in, and that step costs it real ground on ordinary
        days. It keeps almost all of its margin on the big ones — which is the only place this
        system ever makes a call.
      </p>

      <RangeCalibrationSection calibration={record.range_calibration} />

      <h3>Day by day</h3>
      <p>
        Every independently confirmed giant day, and every day the system issued a Go Call for. Days
        it stayed quiet about that turned out ordinary are the overwhelming majority and are counted
        above rather than listed.
      </p>
      {/* The height column is the call's own input restated, not a measurement of how the
          day turned out — the reconstruction the rule was applied to. Saying so here rather
          than letting a column headed "peak height" beside a column headed "what it called"
          imply the second was checked against the first. The independently verified column
          is the last one. */}
      <p className="caveat" data-testid="day-record-caveat">
        <strong>The height column is not an outcome.</strong> It is the largest significant wave
        height that day in the same reconstruction the call was made from, so it says what the
        system was looking at rather than what was later measured. The independently verified column
        is the last one: whether the day was confirmed giant by a contest, a ratified record, or
        documented coverage.
      </p>
      <div className="record-table days" data-testid="day-record">
        <table>
          <caption>
            {record.days.length} days, most recent first. Heights are significant wave height, 15km
            offshore — not the height of a wave face.
          </caption>
          <thead>
            <tr>
              <th scope="col">Date</th>
              <th scope="col">Big-Wave Season</th>
              <th scope="col">What it called</th>
              <th scope="col">Peak significant wave height</th>
              <th scope="col">Confirmed giant?</th>
            </tr>
          </thead>
          <tbody>
            {[...record.days].reverse().map((day) => (
              <tr key={day.date} className={day.gold_day ? 'gold' : undefined}>
                <th scope="row">{day.date}</th>
                <td>{day.season}</td>
                <td>{CALL_LABELS[day.call]}</td>
                <td>{metres(day.peak_significant_wave_height_m)}</td>
                <td>{day.gold_day ? `Yes (${day.gold_tier})` : 'Not on record'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3>What this system has issued for real</h3>
      <p data-testid="issued-record">
        {record.issued === null ? (
          // Distinct from "nothing yet", which is a fact about this installation. This is
          // an absence of knowledge, and reporting it as zero would be inventing the more
          // flattering of the two — a clean record rather than an unreadable one.
          <>
            <strong>Not known.</strong> The retained-call record could not be read, so this page
            cannot say what this installation has issued. Everything above is unaffected: it is
            published with the release rather than kept in that record.
          </>
        ) : record.issued.calls_issued === 0 ? (
          <>
            <strong>Nothing yet.</strong> This installation has issued no calls at all, so
            everything above is reconstruction and none of it is an operating history.
          </>
        ) : (
          <>
            <strong>{record.issued.calls_issued}</strong> calls across {record.issued.dates_covered}{' '}
            dates, {record.issued.go_calls_issued} of them Go Calls, first issued{' '}
            {record.issued.first_issued_at} and most recently {record.issued.last_issued_at}.{' '}
            <strong>None of them are scored here.</strong> No buoy reading reaches the running
            system, so there is nothing to compare a stored call against — the record is kept, and
            scoring it needs an observation this system does not receive.
          </>
        )}
      </p>

      <h3>What this record does not tell you</h3>
      <ul className="limitations" data-testid="limitations">
        <li>
          <strong>It does not predict the height of a wave face.</strong> Every height on this page
          is significant wave height — an instrument&apos;s measure of the whole sea, and the number
          a buoy reports. The height a surfer rides and the news quotes is a wave <em>face</em>,
          which is much larger and <em>cannot be converted from this by any fixed ratio</em> — no
          multiplier turns one into the other, and applying one would produce a confident,
          plausible, wrong number. Nothing here has ever been fitted against a wave face, because no
          reliable historical record of them exists.
        </li>
        <li>
          <strong>The buoy it was fitted against is not the beach.</strong> The target is a mooring
          15km offshore near the head of the canyon, adopted because it measures hourly and has done
          since 2010. The canyon&apos;s effect between there and Praia do Norte is exactly what this
          project set out to model and is still not modelled.
        </li>
        <li>
          <strong>The whole calibration rests on {record.gold_days_total} confirmed days.</strong>{' '}
          {record.gold_days_validated} of them were held back to check the result. Everything on
          this page inherits that.
        </li>
        <li>
          <strong>A wasted trip is counted more carefully than a good one.</strong> A flagged day
          absent from the confirmed list may still have been giant, so the waste figure is a worst
          case and the hit rate is a floor.
        </li>
      </ul>

      <p className="provenance" data-testid="record-provenance">
        Published {record.published_at} from <code>{record.source}</code>, which regenerates every
        figure above from the reports in this repository.
      </p>
    </section>
  );
}

import { useEffect, useState } from 'react';

import {
  fetchTrackRecord,
  type AccuracyBand,
  type CallStatus,
  type PanelRecord,
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

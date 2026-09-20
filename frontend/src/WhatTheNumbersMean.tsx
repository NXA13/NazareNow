/**
 * What the numbers on this site are, and what they are not (#119).
 *
 * **This is not material that moved off the forecast page.** #119's list describes the Face
 * Height versus Significant Wave Height distinction, the Proxy Target, the six-gate chain and
 * ADR 0012 as moving, and none of them was ever rendered anywhere: they existed only in code
 * comments, or in the backend. So this is written rather than relocated, and it is the part of
 * the split with the least precedent to follow.
 *
 * **Why it opens the page.** Every height below it — the track record's figures, the day table,
 * the range calibration — is a Significant Wave Height, and a reader who arrives carrying the
 * number they have seen in news coverage will read all of them as several times too small. The
 * distinction has to come before the numbers it governs rather than as a footnote under them.
 *
 * All wording here goes through `CONTEXT.md` rather than being phrased for readability, and the
 * `_Avoid_` lists are the point. Three of them bind hardest: `Proxy Target` must not become
 * "ground truth", which would claim exactly the authority it does not have; `Amplification`
 * forbids "focusing" and "the canyon effect", so what the canyon does is described rather than
 * named; and `Significant Wave Height` forbids "swell height", which is a different variable
 * this site also renders.
 */
export function WhatTheNumbersMean() {
  return (
    <section aria-labelledby="what-the-numbers-mean" className="explainer">
      <h2 id="what-the-numbers-mean">What these numbers are</h2>

      {/* The load-bearing one. CLAUDE.md marks conflating these two as silently invalidating the
          model's evaluation, and a reader conflating them misjudges every figure on the site by
          a factor nobody can state, because there is no fixed one. */}
      <p data-testid="height-distinction">
        <strong>
          When this site gives you a height for a day, it is a significant wave height.
        </strong>{' '}
        That is the standard measure of a combined sea — the whole wave field arriving at a point,
        both the swell travelled from distant storms and the shorter waves raised by local wind —
        taken as the mean height of the highest third of waves over a sampling period, by
        instruments. It is <strong>not the height of a wave face</strong>: not the number in the
        news coverage and the world records, which is estimated from imagery by expert panels and
        describes a single breaking wave at the beach. A face is much larger than the significant
        wave height of the same sea, and <strong>the two do not convert by any fixed ratio</strong>,
        so this site cannot offer you one.
      </p>

      {/* Swell height is rendered on the forecast page beside the combined figure, so a sentence
          claiming every height on the site is a significant wave height would collapse the two
          quantities CONTEXT.md is most careful to keep apart — and `_Avoid_` lists "swell height
          (a different variable)" under Significant Wave Height for exactly this reason. */}
      <p data-testid="swell-height-aside">
        The swell height shown beside today&apos;s conditions is a third quantity again: the
        travelled component on its own, without the locally raised wind waves the combined figure
        includes. It is the part the canyon has most to work with, which is why it is shown, and it
        is not what a call is decided on.
      </p>

      <p>
        This is why a call here never promises a face height, and why the figures may look small
        beside the ones Nazaré is famous for. They are measuring different things.
      </p>

      <h3>What the system was trained to predict</h3>

      {/* The Proxy Target, named. Page 2 already described the mooring; what it never said is
          that this is a stand-in, chosen because the quantity anyone actually cares about has no
          archive to learn from. That admission is the whole reason the concept has a name. */}
      <p data-testid="proxy-target">
        Face height has no reliable historical archive — there is nothing to learn it from. So the
        system is trained against a <strong>proxy target</strong>: the significant wave height
        recorded by Monican02, an inshore mooring near the head of the Nazaré Canyon. That
        measurement is abundant and objective, which is what makes it usable, and it is{' '}
        <strong>15km offshore rather than at the beach</strong>, which is what makes it a proxy
        rather than the answer.
      </p>

      {/* The first draft of this said the transformation was "exactly what this system does not
          model", which tells a reader the product does nothing — and contradicts CONTEXT.md,
          where that transformation is "the relationship this system exists to learn". The truth
          is narrower and worth the extra clause: the system learns the stretch it can measure,
          and stops where the archive stops. */}
      <p data-testid="amplification-gap">
        What the canyon does to the open ocean on its way to Praia do Norte is the relationship this
        system exists to learn, and it can only learn the stretch it can measure. The record ends at
        that mooring, so <strong>that is where the prediction ends too</strong>. The last stretch —
        from the mooring to the beach — is not modelled at all, and it is the stretch the place is
        famous for. A figure here is a starting point, not a promise about the wave you will stand
        in front of.
      </p>

      <h3>What a Go Call has to clear</h3>

      <p data-testid="gate-chain-intro">
        A Go Call is not one judgement. Six conditions have to hold, and any one of them failing
        leaves the day a Watch or no call at all:
      </p>

      {/* The four quantities are #116's tile row — the tiles are what the call is gated on, at
          the size of a headline — and the last two are the pair `gates-caveat` below names as
          absent from the reconstruction. Four plus two is the six-gate chain #119 asks for, and
          it was nowhere on either page: it lived in the backend's decision module. */}
      <ol data-testid="gate-chain">
        <li>The predicted significant wave height clears the height bar.</li>
        <li>The swell period is long enough — the groundswell signal a giant day is built on.</li>
        <li>The swell direction falls in the window the canyon works with.</li>
        <li>The wind is offshore and light enough not to wreck the face.</li>
        <li>The independent wave models agree about the day.</li>
        <li>Enough of the predicted range sits above the height bar, not just its middle.</li>
      </ol>

      <p data-testid="gate-chain-watch">
        A Watch is judged on the swell alone and does not ask the wind question: wind direction a
        week out carries little information, and requiring it would withhold the early warning a
        Watch exists to give.
      </p>

      <h3>Where a threshold is quoted</h3>

      {/* Softened after review, because the first draft was false. The check is real and it covers
          a named list of 21 files — the ADRs and the analysis notes — and not one of them is a
          frontend file. Claiming the site's own prose was checked would have been the exact
          failure ADR 0012 was written about, stated on the page that describes it. */}
      <p data-testid="current-numbers-rule">
        The bars a call turns on get moved as the calibration improves, and a number written into
        prose does not move with them. So this project marks every one it writes down as either the
        value now or the value at some past decision, and the first kind is checked against the
        shipped configuration on every test run. That check covers the project&apos;s decision
        records and analysis notes. <strong>It does not yet cover these pages</strong>, which is a
        real hole and is recorded as one rather than left to be discovered.
      </p>
    </section>
  );
}

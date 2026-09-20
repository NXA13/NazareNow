/**
 * What the numbers on this site are, and what they are not (#119).
 *
 * **This is not material that moved off the forecast page.** #119's list describes the Face
 * Height versus Significant Wave Height distinction, the Proxy Target and ADR 0012 as moving,
 * and none of the three was ever rendered anywhere: they existed only in code comments. So this
 * is written rather than relocated, and it is the part of the split with the least precedent to
 * follow.
 *
 * **Why it opens the page.** Every figure below it — the track record's heights, the day table,
 * the range calibration — is a Significant Wave Height, and a reader who arrives carrying the
 * number they have seen in news coverage will read all of them as several times too small. The
 * distinction has to come before the numbers it governs rather than as a footnote under them.
 *
 * All wording here goes through `CONTEXT.md` rather than being phrased for readability. The
 * glossary's `_Avoid_` lists are the point: "wave height" is ambiguous between the two
 * quantities this section exists to separate, "wave size" is worse, and `Proxy Target` must not
 * be softened into "ground truth", which would claim exactly the authority it does not have.
 */
export function WhatTheNumbersMean() {
  return (
    <section aria-labelledby="what-the-numbers-mean" className="explainer">
      <h2 id="what-the-numbers-mean">What these numbers are</h2>

      {/* The load-bearing one. CONTEXT.md marks conflating these two as invalidating the
          model's evaluation, and a reader conflating them misjudges every figure on the site by
          a factor nobody can state, because there is no fixed one. */}
      <p data-testid="height-distinction">
        <strong>Every height on this site is a significant wave height.</strong> That is the
        standard oceanographic measure of the sea at a point — the mean height of the highest third
        of waves over a sampling period, measured by instruments. It is{' '}
        <strong>not the height of a wave face</strong>: not the number in the news coverage and the
        world records, which is estimated from imagery by expert panels and describes a single
        breaking wave at the beach. A face is much larger than the significant wave height of the
        same sea, and <strong>the two do not convert by any fixed ratio</strong>, so this site
        cannot offer you one.
      </p>

      <p>
        This is why a Go Call here never promises a face height, and why the figures may look small
        beside the ones Nazaré is famous for. They are measuring different things.
      </p>

      <h3>What the system was trained to predict</h3>

      {/* The Proxy Target, named. Page 2 already described the mooring; what it never said is
          that this is a stand-in, chosen because the quantity anyone actually cares about has no
          archive to learn from. That admission is the whole reason the concept has a name. */}
      <p data-testid="proxy-target">
        Face height cannot be looked up historically — there is no archive of it to learn from. So
        the system is trained against a <strong>proxy target</strong>: the significant wave height
        recorded by Monican02, an inshore mooring near the head of the Nazaré Canyon. That
        measurement is abundant and objective, which is what makes it usable, and it is{' '}
        <strong>15km offshore rather than at the beach</strong>, which is what makes it a proxy
        rather than the answer.
      </p>

      <p data-testid="amplification-gap">
        The canyon focuses swell between that mooring and Praia do Norte, and{' '}
        <strong>that transformation is exactly what this system does not model</strong>. It predicts
        the sea arriving offshore. What the canyon then does to it is the reason the place is famous
        and the reason a prediction here is a starting point rather than a promise about the wave
        you will see.
      </p>

      <h3>Where a threshold is quoted</h3>

      <p data-testid="current-numbers-rule">
        The bars a call turns on get moved as the calibration improves. Wherever this project writes
        one of them down in prose, the sentence records whether it means the value now or the value
        at some past decision, and the first kind is checked against the shipped configuration on
        every test run. A bar that moves cannot quietly leave a stale number behind it in a sentence
        nobody re-read.
      </p>
    </section>
  );
}

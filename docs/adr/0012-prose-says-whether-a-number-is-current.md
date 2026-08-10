# Prose says whether a number is current

A shipped bar's value is asserted in about ten places. Three are executable — `WATCH_PERIOD_S`
in `test_calls.py` and two assertions in `test_baseline_is_fixed.py` — and they work: #60 moved
the Watch bar by 0.1 s, the smallest step the calibration's resolution allows, and all three
failed loudly and were updated.

The other seven are prose, and nothing checked them. The review after #60 found **five claims
falsified by that one move, in five files, three of which #60 never touched**. CI was green
throughout.

**Every mention of a shipped bar's current value now says whether it means *now*.**

    the Watch bar is 11.4 s <!--now:watch_minimum_swell_period_s-->
    #43 set it at 11.4 s <!--fixed:#43-->

`now:` is verified against `thresholds.json` on every test run. `fixed:` is never verified.
`backend/tests/test_prose_marks_the_shipped_bars.py` enforces it over a named list of files,
and Python comments write the same markers as `[now:key]` and `[fixed:ref]`.

## Why not simply derive the numbers

Because most of this prose is *deliberately* historical, and the project keeps superseded
records rather than deleting them. "574 → 530 Watch" is #58's figure and must stay #58's figure;
`analysis/backtest/README.md` carries a block that says in as many words "that row was 'now'
when #43 shipped and is no longer". A rule that rewrote every occurrence from the artifact would
destroy the record this repository exists to keep.

So the hard part was never the checking. It was telling a **stale current-state claim** from a
**correct historical one**, and no transform can do that — the difference is in what the sentence
is trying to say.

## The observation that makes it cheap

A superseded value is, by definition, not the current one. So the checker never reasons about
history at all: it polices numbers equal to what ships *today*, and everything else is invisible
to it. When a bar moves, yesterday's value stops matching and the sentences recording the move
go quiet on their own — correctly, because they were true when written and still are.

Two markers are needed rather than one, and the second covers two different things. One is
history. The other is a measured result that happens to coincide: the candidate table in
`analysis/amplification_model/README.md` records what each fitting choice *would* have produced,
and several produce today's bars. Updating those when a bar moves would falsify an experiment
rather than refresh a claim. A rule offering only `now:` would have invited exactly that.

## What it costs, stated plainly

Sixty sites needed marking, across fifteen files. That is the real price of this ADR and it is
paid once.

Two further limits are deliberate and recorded rather than discovered later:

- **The arcs are not covered.** `swell_arc` and `offshore_wind_arc` are 255, 330, 20 and 180 —
  bare integers that collide with ordinary prose far too often for a value-match rule to mean
  anything. They have also never moved, where the period bars have moved three times. If an arc
  is ever recalibrated, this rule does not cover it.
- **Coverage is a named list, not a glob.** A new file asserting a bar is unprotected until it
  is added. A glob over `**/*.md` would pull in `CONTEXT.md`, every ticket write-up and the
  checker's own docstring, and a rule that noisy gets relaxed rather than extended.

Blockquotes are the one place a marker scopes beyond its own line: this repository writes
superseded records as blockquotes, and one `fixed:` covers the contiguous block. Thirty markers
saying one thing thirty times is a rule nobody keeps.

## The check had to be tried against a moved bar before it could be believed

The first version verified `now:` markers only on lines that still held some current value.
Simulating a one-step move of the Watch bar surfaced three sites and silently passed two — ADR
0010's "the shipped Watch bar reads 11.4 s" and `calibrate.py`'s translation comment — because
those lines name that bar *and nothing else*, so once it moved they held no current value and
were never scanned. **The two that slipped were the two whose entire sentence is the claim.**

Verifying marked claims independently of any value match fixes it, and the simulated move now
surfaces all four while flagging none of the historical mentions. That experiment is the
evidence for this ADR, and a rule of this kind is worth nothing until it has been run against
the change it exists to catch.

## Consequences

- Moving a bar produces a failing test naming every prose site that asserts it, in every file,
  before the change can merge.
- The executable tripwires in `test_calls.py` and `test_baseline_is_fixed.py` are unchanged.
  They cover the code; this covers the prose; neither replaces the other.
- Writing a new current-state claim without a marker fails the suite, so the convention is
  self-enforcing for anything inside the covered files.
- No shipped bar moves as part of this decision.

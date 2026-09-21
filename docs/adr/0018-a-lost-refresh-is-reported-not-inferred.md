# A lost refresh is reported, not inferred, and the six-hour rule does not move

`/api/conditions/grid` dates its grid by the grid's own fetch and calls it stale after
`STALE_AFTER_SECONDS` — two whole cycles, six hours. A grid that stops refreshing therefore
presents as **current** for its first two missed runs, and nothing tells anybody sooner (#139).

The six-hour threshold is right, and it stays exactly as it is. `cycle.py` says why: *"One
missed run is a blip — a provider hiccup, a restart — and calling that stale would train users
to ignore the warning."* A warning that fires on blips is a warning nobody reads, and that is a
worse failure than the one being fixed.

**What changes is that the silence ends.** `ConditionsGrid` now carries `refresh_failed`, and it
is answered from different evidence than `stale` is.

## The two questions are not the same question

| | `stale` | `refresh_failed` |
|---|---|---|
| asks | how old is this? | did the last attempt fail? |
| answered from | arithmetic on `fetched_at` | a record the run already wrote |
| kind of claim | an inference from a clock | a reported fact |
| when it can fire | after six hours | within one cycle |

The run knew at the moment it happened. `refresh_conditions_grid` catches the failure, records
the endpoint, the failure kind and the detail under its own `raw_response` source, and returns
without touching the stored grid — which is how the previous grid survives, and is not in
question here. **Nothing served had ever read that row back.** The information existed, was
stored, and never reached a human.

## Why a shorter threshold for the grid was rejected

It was the obvious alternative: the grid is decoration over a forecast rather than the forecast,
so a stricter clock for it is defensible. It loses on both halves of the rubric this decision was
delegated under.

**On accuracy:** a shorter fuse is still an inference from elapsed time, so it still cannot tell
*refreshed cleanly four hours ago* from *failed ten minutes ago* — the exact distinction this
ticket exists to draw. It buys a smaller blind spot, not fewer blind spots.

**On the interface:** it puts two definitions of *out of date* into one response. `ConditionsGrid`
already warns about precisely this shape of confusion — its stamps are the grid's own *"and not
the latest run's"*, because mixing the two *"would present last night's wind as this morning's"*.
A second age rule beside the first is the same mistake in a new place.

Doing nothing and defending the six hours in writing was the third option. It is half of what is
done here: the threshold is defended, and the fact the system already had is surfaced beside it.

## The cost, measured against the alternative rather than in the abstract

One extra read per grid request, of a table the store already holds, on an endpoint that is
already a read from that same store — a `COUNT(*)` against `raw_response` filtered by source and
stamp. If it ever shows up, the fact can be denormalised onto the run row when the run writes it,
which is cheaper still and invents no new data.

`Store.responses_since` compares the stored strings lexicographically. That is sound **only**
because both sides are written by `store.now()` — `datetime.now(UTC).isoformat()` — so they share
a format and a zone. A stamp from anywhere else must not be passed to it.

## What is not reported

**A failure older than the grid in hand is a recovery, not a degradation.** A run that lost the
grid followed by a run that fetched one leaves a row in the table forever; reporting it would
make the endpoint call the wind doubtful for the life of the installation. The comparison is
strictly after the grid's own `fetched_at`, which also stops the run that *stored* the grid from
reporting itself.

**The moment of the failure is not carried**, though the decision comment on #139 said it would
be. The grid's own `fetched_at` already dates the picture, and a second timestamp beside it is
the crowding ADR 0012 warns about — the reader's sentence is *"this wind is from 09:04, and a
refresh since then failed"*, which needs one stamp and one flag.

## Consequences

- **`stale`, `STALE_AFTER_SECONDS` and `is_stale()` are untouched.** So is the rule that a lost
  grid never costs the forecast: nothing about the wrapped fetch or `pipeline_run.outcome`
  changes.
- **`raw_response` gains its first production reader.** Its docstring says no HTTP surface
  exposes these rows and that a test drives the method directly; that is now true of
  `raw_responses()` alone, not of the table.
- **The map has to say it.** The endpoint telling the truth and the page not repeating it is the
  same silence one layer up. That half depends on the frontend grid types, which arrive with
  #123, and is not in the commit that carries this ADR.
- The wording a reader sees is an ADR 0012 question — prose says whether a number is current —
  and belongs beside the figure it qualifies, not here.

# The Watch tier has a price

ADR 0003 gives the Go Call tier a stated cost — eight calls per Big-Wave Season — and gives the
Watch tier nothing. `analysis/calibration/` filled the gap with the only constraint available
to it, and took the **highest swell period that still catches every Gold Day in the fitting
split**. Full recall is a hard constraint, so the bar lands wherever the least impressive Gold
Day in the fitting split happens to sit, and nothing in the rule notices what that costs.

We give the Watch tier a budget too. The Watch bar becomes the **lowest swell period whose
Watch rate stays within 40 Watch days per Big-Wave Season** — the same shape as the Go Call
bar, differing only in the number. Recall stops being a constraint on it.

This is still the recall tier ADR 0003 describes. Both rules take the *lowest* bar they can
afford, and recall rises as the bar falls, so each tier catches the most Gold Days its budget
will pay for. What changes is that the recall tier now has a budget to spend.

## Why this is an ADR and not another amendment to ADR 0006

Ticket #12 fitted the baseline's numbers as an amendment to ADR 0006: moving 14 s to 13 s
changes how strict the benchmark is, not what it is. ADR 0009 then changed the predictor's
*shape* — a wind condition with a light-wind exemption is a different rule, not a retuned one
— and took its own ADR for it.

This is a third thing, and it takes its own ADR for the ADR 0009 reason rather than the #12
one. The predictor's shape is untouched: the Heuristic Baseline has the same five conditions
it had yesterday. What changes shape is the **criterion that selects one of its numbers**, and
that criterion is a policy decision about what a Watch is allowed to cost a reader, not an
arithmetic consequence of the record. It introduces a constraint ADR 0003 does not contain and
a product judgement that needs arguing in the open. Folding it into a calibration is exactly
how the previous rule got in.

## What forced it

On #12's 6 fitting Gold Days the rule was invisible. #39 took the fitting split to 25, and the
bar fell from 12.5 s to 10.1 s while the Watch tier went from 106 days issued to 1050 — about
73 a season. #40's review filed this as **#43** rather than retuning it in place.

Two things in that fit's own output say the constraint was doing more than ADR 0003 asks.

**The marginal Gold Day was very expensive.** Walking down the sweep on the fitting split,
each step's price in Watch days per season per additional Gold Day:

| Bar | Gold Days caught | Watch days per season | Price of this step |
|---|---|---|---|
| 12.5 s | 16/25 | 24.0 | 2.2 |
| **12.0 s** | **21/25** | **35.1** | **2.2** |
| 11.5 s | 23/25 | 46.3 | 5.6 |
| 11.0 s | 24/25 | 59.0 | 12.7 |
| 10.5 s *(previously chosen)* | 25/25 | 72.9 | 13.9 |
| 10.0 s | 25/25 | 86.1 | — buys nothing |

The last two Gold Days cost about thirteen Watch days a season each, roughly six times what
every day above them cost. The rule paid those prices without being asked, because 24/25 was
simply disqualified.

**And the guarantee did not survive the split.** Held-out recall is **12/13 at every bar from
12.0 s down to 10.0 s**. The four extra Gold Days that full in-sample recall bought are worth
exactly nothing on days the fit never saw — which is the ordinary way an in-sample constraint
fails, and the reason to stop treating 100% as categorically different from 96%.

**A Watch on a third of the season is not a warning.** A Big-Wave Season is about 182 days. At
10.1 s the Watch tier covered **35%** of them; at the bottom of the sweep, 41%. The tier that
exists to say "start paying attention" was saying it more than one day in three.

## Why a budget rather than a weaker recall constraint

The obvious smaller change is a recall floor below 1.0 — catch 90% of fitting Gold Days rather
than all of them. We rejected it because it answers a different complaint than the one that was
made. The evidence above is not that 100% is too high a floor; it is that **in-sample recall is
the wrong quantity to constrain at all**. It is measured on 25 Gold Days, it does not transfer,
and a floor of 0.9 would be measured just as badly as a floor of 1.0. Cost is measured on
thousands of days and is the thing the reader actually experiences.

So: constrain the well-measured quantity, and maximise the noisy one subject to it. That is
what `choose_go_bar` has always done, and there was never a reason for the Watch tier to be the
exception.

We also rejected a **marginal-price cap** — keep stepping down while each additional Gold Day
costs under *K* Watch days a season — despite it matching the shape of the complaint most
directly. It is not stable. The sweep has one awkward step high up, 14.5 s to 14.0 s, which
buys one Gold Day for 3.2 Watch days a season where the step below it buys four for 1.1. A cap
of 3.0 stops dead there and yields 14.5 s and 5/25; a cap of 3.5 walks past it to 12.0 s and
21/25. A rule whose answer moves 2.5 seconds and sixteen Gold Days on a 15% change in its one
free parameter is not a rule, and shipping it would reintroduce in a new place the fragility
this ADR removes. A budget degrades one step of the sweep at a time instead.

And we rejected **leaving it alone**. ADR 0003 does make Watch the recall tier — "missing a
forming swell is worse than raising a Watch that fades" — and that sentence is not in dispute.
But it is an argument for the Watch bar sitting below the Go Call bar, which it does under
either rule. It is not an argument for an unbounded price, and the held-out figures show the
price bought nothing.

## The number, and how much it matters

**40 Watch days per Big-Wave Season.** About one day in five of a 182-day season: often enough
that somebody checking weekly usually finds a swell forming, rare enough that four days in five
make no claim on their attention.

This is the second hand-chosen number in the calibration, and like
`GO_CALLS_PER_SEASON_BUDGET` it is a product judgement written down as one. The calibration
previously said the Go budget was "the only hand-chosen number left"; that sentence is now
wrong and has been corrected rather than quietly outgrown.

What makes it defensible rather than arbitrary is that it is **not near a boundary**. Every
budget from 36 to 46 days a season selects the same bar on this record, and budgets outside
that range move the bar one half-second step at a time — 47 gives 11.5 s, 35 gives 12.5 s.
Nothing about the outcome hangs on 40 rather than 42.

The rate counts flagged days over the whole record while dividing by seasons, so a Watch raised
in July is in the numerator when the denominator counts only Big-Wave Seasons. That makes the
budget **conservative** — the chosen bar flags 18% of Big-Wave Season days against a budget
nominally allowing 22% — and it keeps the Watch rate in the same unit as the Go Call rate,
which is worth more than the small overcount. Measuring both tiers against Big-Wave Season days
alone would be the better unit and is not attempted here, because it would move the Go Call bar
in a ticket about the Watch bar.

## Consequences

The shipped Watch bar moves from **10.1 s to 11.5 s**, and it is the only threshold that moves.
The Go Call bar stays at 12.9 s, the height bar at 2.75 m, both arcs and the speed cap
unchanged, and ADR 0009's exemption at 16.5 km/h. The Go Call tier's figures are identical
either side of this change.

**The Watch tier halves in cost and loses nothing held out.** On the held-out split it flags
32.2 days a season instead of 61.2, and catches the same 12 of 13 Gold Days. On the fitting
split recall falls from 25/25 to 21/25, which is the in-sample number this ADR argues should
not have been driving the choice.

ADR 0006 keeps the Heuristic Baseline as the permanent benchmark, so figures measured either
side of this are not directly comparable — the same care ADR 0009 required, and for a weaker
reason: this changes which numbers the rule carries rather than what the rule is, so it is the
#12 kind of incomparability rather than the ADR 0009 kind.

`choose_watch_bar` can now fail in a way it could not before: if no bar in the sweep is
affordable it raises, rather than returning the strictest bar available. A Watch tier that
cannot be afforded at any period this record can express is a finding about the sweep or the
budget, not a threshold to ship.

The calibration reports **which** constraint set the Watch bar, as it already does for the Go
Call bar, and carries the price of the step the budget refused. A report naming the constraint
while hiding what it turned down would repeat #43's omission in a smaller way.

## What this does not settle

**The budget is a judgement, not a measurement.** Nothing in the record says a Watch should
cost 40 days a season rather than 25 or 55. What the record says is what each bar costs and
what it catches; the choice between them is ours. That is the same standing this project gives
the Go Call budget, and it is the honest description of both.

**Days are not episodes.** A Watch tier flagging 35 days a season is not warning 35 separate
times — swells run for several days, and on this record the flagged days at the chosen bar fall
into about 15 runs a season. The Go budget's own rationale ("roughly one every three weeks") is
stated in episodes while the constraint is enforced in days, so both budgets are slightly the
wrong shape in the same direction. Measuring the tiers in episodes would be a better statement
of what a reader receives, and needs a definition of when two swells are one — worth its own
ticket rather than a parameter smuggled in here.

**Whether the Watch tier should speak outside the Big-Wave Season at all** is untouched.
CONTEXT.md makes XXL Days possible only from October to March, and on the fitting split about
7% of the Watch days this rule issues fall outside that window, against 12% under the rule it
replaces. They are being budgeted for rather than questioned.

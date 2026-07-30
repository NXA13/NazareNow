# Gold Day research

Ticket [#10](https://github.com/NXA13/NazareNow/issues/10).

ADR 0002 trains on Monican02's Significant Wave Height as a Proxy Target and calibrates the
alerting threshold against a small set of hand-verified Gold Days. This document is that
research: the days on which Praia do Norte is externally confirmed to have been genuinely
giant, from the 2010/11 Big-Wave Season onward, each traceable to a source that was fetched
and read while writing this.

**What this is for.** Calibration and validation of the Go Call threshold in #12 — never
training data, and never a Face Height regression target. There are thirty-eight days here
against roughly 2,900 Big-Wave Season days in the same span; that is a calibration set, not
a dataset.

**What this is not.** This is not the machine-readable Gold Day file. That is the
implementation of #10 and is built from this document.

## Method

Every date below was checked against a page retrieved during this research. Nothing rests on
recollection of surfing history, and where a claim is widely repeated but could not be
retrieved from a source, it is in **Unverified leads** rather than in the table.

**Confidence tiers**, defined by evidence rather than impression:

| Tier | Admitted on |
|---|---|
| **Ratified** | A world record ratified by an authority (Guinness World Records, WSL/Red Bull Big Wave Awards), or an official WSL contest that ran and was scored on that date |
| **Documented** | Two or more independent reputable sources describing exceptional conditions at Praia do Norte on that date |
| **Reported** | A single credible source, or dated imagery from an identifiable origin |

Anything weaker is not recorded.

**Rules applied:**

1. Every entry carries a source URL, that source's publication date, and a verbatim quote.
2. No entry rests on a single source unless that source is a ratified record or an official
   contest result.
3. **Silence is never evidence.** No day is recorded as "not giant" because nothing was
   found. This list has positives and unknowns, and no negatives.
4. Dates are the local date of the session at Nazaré (Europe/Lisbon). Sources frequently
   publish a day late or say only "Monday". Where the date is not pinned by the source, the
   ambiguity is recorded and the entry flagged — never guessed into precision.
5. Reported wave sizes are **Face Height estimates** with their source, explicitly *not* the
   Proxy Target. ADR 0002 measured the Hs-to-Face-Height coupling as weak. No figure in this
   document is a Significant Wave Height unless it says so.
6. Official WSL contest days are strong evidence because they only run when a commissioner
   calls them on inside a waiting period. The WSL event results page is a primary source and
   gives the exact day.

**On the Big Wave Awards as an authority.** The protocol names the WSL Big Wave Awards as a
ratifying authority. A ride that *won* a Big Wave Award category has been adjudicated and
dated by that authority, so those days are recorded as **Ratified**. A ride that was
*nominated or placed but did not win* is recorded as **Reported**: the WSL nominee and
winner announcements are two pages but one origin, so they are not two independent sources.
This distinction is the single largest driver of the tier split below, and a reviewer who
disagrees with it can re-tier seventeen entries without re-doing any sourcing.

## Counts

**Total: 38 Gold Days**, spanning 14 Big-Wave Seasons.

| Tier | Days |
|---|---|
| Ratified | 19 |
| Documented | 2 |
| Reported | 17 |

| Season | Days | Of which Ratified |
|---|---|---|
| 2010/11 | 0 | 0 |
| 2011/12 | 1 | 1 |
| 2012/13 | 1 | 0 |
| 2013/14 | 1 | 0 |
| 2014/15 | 1 | 1 |
| 2015/16 | 3 | 0 |
| 2016/17 | 6 | 2 |
| 2017/18 | 4 | 4 |
| 2018/19 | 5 | 2 |
| 2019/20 | 3 | 1 |
| 2020/21 | 1 | 1 |
| 2021/22 | 9 | 4 |
| 2022/23 | 0 | 0 |
| 2023/24 | 1 | 1 |
| 2024/25 | 1 | 1 |
| 2025/26 | 1 | 1 |

Two seasons carry no entries: **2010/11** and **2022/23**. Neither is evidence that those
winters were small — see *Known limitations*.

The distribution is badly uneven, and the unevenness is about media and contest coverage
rather than about the ocean. Nine days in 2021/22 and none in 2022/23 reflects the Big Wave
Awards running an edition covering 2021/22 and then stopping, plus two contests landing in
the same season. Any calibration weighted by season count will inherit this bias.

## Verified Gold Days

Entries are grouped by Big-Wave Season. Face Height figures are **sourced observer estimates
of the breaking wave, not Significant Wave Height, and not the Proxy Target.**

### 2011/12

**2011-11-01 — Garrett McNamara, 78 ft, Guinness World Record** · Ratified
- Face Height: 78 ft / 23.77 m (Guinness-ratified, since superseded)
- Source: https://www.guinnessworldrecords.com/news/2018/5/a-timeline-of-the-biggest-waves-surfed-as-rodrigo-koxa-sets-new-record-523752 — published 2018-05-01
- Quote: McNamara "set the previous record at this same location" on "1 November 2011"
- Corroboration (does not pin the day): https://www.guinnessworldrecords.com/news/2012/5/video-78-foot-wave-surfed-by-garrett-mcnamara-confirmed-as-largest-ever-ridden-41598 — published 2012-05-09 — "surf a mammoth 78-foot wave last November at Nazaré, Portugal"
- **Flag:** the day-level precision rests on the single Guinness timeline page. The 2012
  ratification article says only "last November". The live Guinness record page now names
  Steudtner, so McNamara's entry is only retrievable from the timeline article.

### 2012/13

**2013-01-28 — Garrett McNamara, ~100 ft claim (never ratified)** · Documented
- Face Height: reported at "around 100ft" by media; never ratified. Treat as an upper-bound
  claim, not a measurement.
- Source 1: https://time.com/3796323/surfs-way-up-garrett-mcnamara-claims-to-ride-record-wave-in-portugal/ — published 2013-01-30 — "On Monday, January 28, he surfed what's thought to be a 100-foot wave, the largest swell ever ridden by a surfer."
- Source 2: https://laist.com/shows/take-two/surfer-garrett-mcnamara-conquers-massive-wave-in-portugal-photos — published 2013-01-30 — "he caught a wave reported to be around 100ft off the coast of Nazaré on Monday"
- Note: 2013-01-28 was a Monday, consistent with both sources.

### 2013/14

**2013-10-28 — Carlos Burle's ride and Maya Gabeira's near-drowning** · Documented
- Face Height: observers estimated up to 100 ft; never ratified.
- Source 1: https://abcnews.com/blogs/headlines/2013/10/surfer-carlos-burle-might-have-set-new-big-wave-record — published 2013-10-29 — "Burle, 46, took on a monster wave off the coast of Nazaré, Portugal, Monday that appears to have been higher than the 100-foot wave U.S. surfer Garrett McNamara was credited with conquering in January."
- Source 2: https://www.csmonitor.com/World/Global-News/2013/1029/Did-a-Brazilian-surfer-just-catch-the-biggest-wave-ever-and-save-a-life-too — updated 2013-10-30 — "it turned out to be a briny jackpot, a superwave that observers believe may have reached 100 feet into the stormy air", and Burle "managed this feat just hours after rescuing close friend and award-winning Brazilian surfer Maya Gabeira from drowning"
- Source 3: https://www.nationalgeographic.com/adventure/article/big-wave-surfer-carlos-burle-on-last-weeks-dramatic-rescue-and-ride-at-nazare — published 2013-11-07 — "Last Monday Brazilian Carlos Burle almost lost his tow partner, Maya Gabeira, then rode what many are calling the biggest wave in the history of surfing in Nazaré, Portugal."
- **This is the date the provisional CSV mislabels.** See *Corrections*.

### 2014/15

**2014-12-11 — Sebastian Steudtner wins the 2014/15 XXL Biggest Wave Award** · Ratified
- Face Height: not stated on the source page.
- Source: https://www.worldsurfleague.com/posts/107115/big-wave-award-nominees-2014-2015 — published 2015-05-01 — XXL Biggest Wave winner Sebastian Steudtner at Nazaré, "December 11, 2014"; Benjamin Sanchis won the Wipeout Award for the same date; Ross Clarke-Jones and Hugo Vau were also nominated at Nazaré on "December 11, 2014"
- Four separately adjudicated Nazaré rides on one date, one of them an award winner.

### 2015/16

All three are Big Wave Award nominations reported through a single origin, so all are
**Reported**.

**2015-10-27 — Pedro Scooby, XXL Biggest Wave nominee** · Reported
- Source: https://www.carvemag.com/2016/03/wsl-big-wave-award-nominees-announced/ — published 2016-03-23 — "at Nazaré, Portugal on October 27, 2015"

**2015-11-01 — Garrett McNamara, XXL Biggest Wave nominee** · Reported
- Source: https://www.carvemag.com/2016/03/wsl-big-wave-award-nominees-announced/ — published 2016-03-23 — "at Nazaré, Portugal on November 1, 2015"

**2016-02-19 — Mick Corbett, XXL Biggest Wave nominee** · Reported
- Source: https://www.carvemag.com/2016/03/wsl-big-wave-award-nominees-announced/ — published 2016-03-23 — "at Nazaré, Portugal on February 19, 2016"

### 2016/17

**2016-10-24 — four XXL Biggest Wave nominations in one session** · Reported
- Source: https://www.worldsurfleague.com/posts/243767/2017-wsl-big-wave-award-nominees-announced — published 2017-03-28 — Sebastian Steudtner, Hugo Vau, Tom Lowe and Rafael Tapia each "at Nazaré, Portugal on October 24, 2016"
- Four separate nominated rides makes this the strongest **Reported** entry in the list, but
  it still rests on one origin.

**2016-12-17 — Trevor Sven Carlson, XXL Biggest Wave nominee** · Reported
- Source: https://www.worldsurfleague.com/posts/243767/2017-wsl-big-wave-award-nominees-announced — published 2017-03-28 — "at Nazaré, Portugal on December 17, 2016"

**2016-12-20 — Nazaré Challenge, first WSL contest ever run at Praia do Norte** · Ratified
- Face Height: "30-to-40-foot surf" (WSL)
- Source 1: https://www.worldsurfleague.com/posts/235582/jamie-mitchell-makes-history-at-nazare-challenge — published 2016-12-20 — "Australian Jamie Mitchell made history Tuesday by winning the inaugural Nazaré Challenge at Praia do Norte in 30-to-40-foot surf."
- Source 2: https://www.worldsurfleague.com/events/2016/mbwt/1660/nazar-challenge/results — event window "Oct 15, 2016 - Feb 28, 2017", rounds completed 20 December
- Source 3: https://www.worldsurfleague.com/posts/243767/2017-wsl-big-wave-award-nominees-announced — published 2017-03-28 — Jamie Mitchell "at Nazaré, Portugal on December 20, 2016"

**2016-12-22 — Lucas "Chumbo" Chianca, XXL Biggest Wave nominee** · Reported
- Source: https://www.worldsurfleague.com/posts/243767/2017-wsl-big-wave-award-nominees-announced — published 2017-03-28 — "at Nazaré, Portugal on December 22, 2016"

**2016-12-23 — Trevor Sven Carlson, XXL Biggest Wave nominee** · Reported
- Source: https://www.worldsurfleague.com/posts/243767/2017-wsl-big-wave-award-nominees-announced — published 2017-03-28 — "at Nazaré, Portugal on December 23, 2016"

**2017-02-28 — Francisco Porcella wins the 2017 TAG Heuer XXL Biggest Wave Award** · Ratified
- Face Height: not stated on either WSL page.
- Source 1 (the win): https://www.worldsurfleague.com/posts/251458/world-s-best-big-wave-surfers-honored-at-wsl-big-wave-awards — published 2017-04-29 — TAG Heuer XXL Biggest Wave Award to Francisco Porcella at Nazaré, Portugal; Porcella: "Thank you to Nazaré for that wave."
- Source 2 (the date): https://www.worldsurfleague.com/posts/243767/2017-wsl-big-wave-award-nominees-announced — published 2017-03-28 — Francisco Porcella "at Nazaré, Portugal on February 28, 2017"
- **Flag:** the winners announcement does not restate the ride date. The date is joined across
  two WSL pages on the basis that Porcella has exactly one Nazaré nomination in that year's
  list. See *Date ambiguities and contradictions*.

### 2017/18

**2017-11-08 — Rodrigo Koxa, 80 ft, Guinness World Record** · Ratified
- Face Height: 80 ft / 24.38 m (Guinness-ratified, since superseded)
- Source: https://www.guinnessworldrecords.com/news/2018/5/a-timeline-of-the-biggest-waves-surfed-as-rodrigo-koxa-sets-new-record-523752 — published 2018-05-01 — "24.38 m (80 ft)" surfed at "Nazaré, Portugal, on 8 November 2017"

**2018-01-18 — Maya Gabeira, 68 ft, Guinness World Record (women's)** · Ratified
- Face Height: 68 ft / 20.72 m (Guinness-ratified, since superseded by her own 2020 ride)
- Source: https://www.guinnessworldrecords.com/news/press-release/2018/10/maya-gabeira-sets-new-guinness-world-records-title-for-the-largest-wave-surfed-543347/ — published 2018-10-08 — "The 31-year old from Rio de Janeiro, Brazil successfully surfed a wave measuring 68 feet / 20.72 meters from trough to crest at the infamous big-wave break known as Praia do Norte in Nazaré, Portugal on January 18, 2018."

**2018-02-10 — Nazaré Challenge, opening heats** · Ratified
- Face Height: "wave faces in the 25-to-35-foot category" (WSL Big Wave Tour Commissioner)
- Source 1: https://www.worldsurfleague.com/posts/293855/nazare-challenge-big-wave-contest-could-run-saturday — published 2018-02-06 — the contest could run "Saturday, February 10" local time
- Source 2: https://www.worldsurfleague.com/posts/294424/lucas-chumbo-chianca-wins-wsl-big-wave-tour-nazar-challenge — published 2018-02-11 — "The second-ever BWT event at Nazaré ran over two days after dangerous conditions threatened the competitors following the opening heats on Saturday." and "Big Wave Tour Commissioner Mike Parsons, alongside the judging panel, rated conditions a Bronze coefficient with wave faces in the 25-to-35-foot category."

**2018-02-11 — Nazaré Challenge, completion day** · Ratified · **date inferred**
- Face Height: as above.
- Source: https://www.worldsurfleague.com/posts/294424/lucas-chumbo-chianca-wins-wsl-big-wave-tour-nazar-challenge — published 2018-02-11 — "ran over two days ... following the opening heats on Saturday"
- **Flag:** no fetched source names 11 February explicitly. The date is inferred from "ran
  over two days", "opening heats on Saturday" (10 February) and the article's own
  publication date of Sunday 11 February 2018. The inference is short but it *is* an
  inference, and this is the weakest date in the Ratified tier.

### 2018/19

**2018-11-09 — Justine Dupont and Russell Bierke, Big Wave Award nominees** · Reported
- Source: https://www.worldsurfleague.com/posts/382481/wsl-big-wave-award-nominees-announce — published 2019-04-11, updated 2019-04-15 — Justine Dupont "at Nazaré, Portugal, on November 9 and November 18, 2018"; Russell Bierke "at Nazaré, Portugal, on November 9, 2018"

**2018-11-16 — Nazaré Challenge, contest day** · Ratified
- Face Height: forecast "in the 20-30' range through the day on Friday, with the very largest sets of the morning up to 35'" (WSL, pre-event forecast — a forecast, not an observation)
- Source 1: https://www.worldsurfleague.com/posts/358463/green-alert-nazar-challenge-called-on — published 2018-11-13 — "The WSL Big Wave Tour (BWT) has issued a Green Alert for the Nazaré Challenge in Nazaré, Portugal to run on Friday, November 16, 2018."
- Source 2: https://www.worldsurfleague.com/events/2018/mbwt/2886/nazare-challenge/results — event window "Oct 1 - Nov 18, 2018", all rounds completed 16 November; Grant Baker won
- Source 3: https://www.worldsurfleague.com/posts/382481/wsl-big-wave-award-nominees-announce — published 2019-04-11 — Natxo Gonzalez, Ride of the Year nominee, "at Nazaré, Portugal, on November 16, 2018"

**2018-11-18 — Justine Dupont wins the Women's XXL Biggest Wave Award** · Ratified
- Face Height: not stated on the source page.
- Source 1: https://www.worldsurfleague.com/posts/388844/winners-list-from-the-wsl-big-wave-awards — published 2019-05-02 — "2019 Women's XXL Biggest Wave Winner: Justine Dupont at Nazaré, Portugal on November 18, 2018."
- Source 2: https://www.worldsurfleague.com/posts/382481/wsl-big-wave-award-nominees-announce — published 2019-04-11 — Pedro Calado, Biggest Paddle nominee, "at Nazaré, Portugal, on November 18, 2018"

**2018-12-14 — Tom Butler, XXL Biggest Wave nominee** · Reported
- Source: https://www.worldsurfleague.com/posts/382481/wsl-big-wave-award-nominees-announce — published 2019-04-11 — "at Nazaré, Portugal, on December 14, 2018"

**2019-02-07 — Sebastian Steudtner, XXL Biggest Wave nominee** · Reported
- Source: https://www.worldsurfleague.com/posts/382481/wsl-big-wave-award-nominees-announce — published 2019-04-11 — "at Nazaré, Portugal on February 7, 2019"

### 2019/20

**2019-11-13 — Justine Dupont, XXL Biggest Wave nominee** · Reported
- Source: https://www.worldsurfleague.com/posts/453898/2020-red-bull-big-wave-award-nominees-announced — published 2020-07-20 — "November 13, 2019"

**2020-02-11 — Nazaré Tow Surfing Challenge (inaugural) and Maya Gabeira's 73.5 ft Guinness World Record** · Ratified
- Face Height: 22.4 m / 73.5 ft (Guinness-ratified; current women's record)
- Source 1: https://www.guinnessworldrecords.com/world-records/542139-largest-wave-surfed-unlimited-female — "The largest wave surfed (unlimited) by a female is 22.4 m (73.5 ft), and was achieved by Maya Gabeira (Brazil), in Praia do Norte, Nazaré, Portugal, on 11 February 2020."
- Source 2: https://www.worldsurfleague.com/posts/446736/nazare-winners-announced — published 2020-02-11 — WSL announcing the winners of the Nazaré Tow Surfing Challenge presented by Jogos Santa Casa
- Source 3: https://www.worldsurfleague.com/posts/453898/2020-red-bull-big-wave-award-nominees-announced — published 2020-07-20 — Kai Lenny (two waves), Sebastian Steudtner, Justine Dupont and Maya Gabeira all nominated for rides on "February 11, 2020"
- The strongest-evidenced day in the list: a contest, a ratified world record and five award
  nominations on the same date.

**2020-02-17 — Lucas Chianca, XXL Biggest Wave nominee** · Reported
- Source: https://www.worldsurfleague.com/posts/453898/2020-red-bull-big-wave-award-nominees-announced — published 2020-07-20 — "February 17, 2020"

### 2020/21

**2020-10-29 — Sebastian Steudtner, 86 ft, Guinness World Record** · Ratified
- Face Height: 26.21 m / 86 ft (Guinness-ratified; current men's record)
- Source 1: https://www.guinnessworldrecords.com/world-records/78115-largest-wave-surfed-unlimited — "The largest wave surfed (unlimited) - male is 26.21 m (86 feet), and was achieved by Sebastian Steudtner (Germany), off the coast of Praia do Norte, Nazaré, Portugal, on 29 October 2020."
- Source 2: https://www.worldsurfleague.com/posts/501752/sebastian-steudtner-sets-new-guinness-world-records-title-for-mens-largest-wave-surfed-unlimited-pr — published 2022-05-24 — "The 37-year-old from Nuremberg, Germany, successfully surfed a wave measuring 86 feet (26.21 meters) from trough to crest at the infamous big-wave break known as Praia do Norte in Nazaré, Portugal on October 29, 2020."
- The ratification took roughly 18 months; the *record* date is the session date, 29 October
  2020, and that is what is recorded here.

### 2021/22

Nine days, the densest season in the list. Two contests ran in this single Big-Wave Season,
which is unusual and is itself a sourced finding (see *Date ambiguities and contradictions*).

**2021-11-19 — Justine Dupont, Biggest Paddle placing** · Reported
- Source: https://www.worldsurfleague.com/posts/504185/2022-red-bull-big-wave-awards-winners-announced-justine-dupont-wins-big-with-ride-of-the-year-and-biggest-tow-awards-pr — published 2022-07-07 — "Justine Dupont at Nazaré on November 19, 2021"

**2021-12-11 — Michelle des Bouillons, Biggest Tow placing (2nd, women)** · Reported
- Source: https://www.worldsurfleague.com/posts/504185/... — published 2022-07-07 — "Michelle des Bouillons at Nazaré on December 11, 2021"

**2021-12-13 — TUDOR Nazaré Tow Surfing Challenge, contest day** · Ratified
- Face Height: "clean, offshore 40-to-50 foot bombs"
- Source 1: https://thecitylife.org/2021/12/13/spectacular-surfing-at-tudor-nazare-tow-surfing-challenge-presented-by-jogos-santa-casa/ — published 2021-12-13 — "Competition got underway bright and early this morning at Nazaré's Praia do Norte for the World Surf League (WSL) TUDOR Nazaré Tow Surfing Challenge presented by Jogos Santa Casa." and "A beautiful sunny day and clean, offshore 40-to-50 foot bombs set the scene"; the page also carries "The TUDOR Nazaré Tow Surfing Challenge presented by Jogos Santa Casa on December 13, 2021 in Nazare, Portugal."
- Source 2: https://www.worldsurfleague.com/events/2021/mbwt/3813/tudor-nazar-tow-surfing-challenge-presented-by-jogos-santa-casa/results — event window "Nov 15, 2021 - Mar 31, 2022", Round 1 six heats completed "Dec 13"
- Source 3: https://www.worldsurfleague.com/posts/504185/... — published 2022-07-07 — "Michelle des Bouillons at Nazaré on December 13, 2021"
- Winners: Lucas Chianca (men's), Justine Dupont (women's), Chianca & Kai Lenny (team).

**2022-01-08 — Justine Dupont wins the Women's Biggest Tow Award; five further award placings** · Ratified
- Face Height: not stated numerically for the day; the WSL swell report calls it "a massive day of surfing at Nazare".
- Source 1: https://www.worldsurfleague.com/posts/504185/... — published 2022-07-07 — Biggest Tow (women) 1st "Justine Dupont at Nazaré on January 8, 2022", plus her waves two and three; Biggest Tow (men) placings for Pedro Scooby, Nic Von Rupp and Lucas Chumbo Chianca all "at Nazaré on January 8, 2022"
- Source 2: https://www.worldsurfleague.com/posts/495219/nazare-portugal-january-2022-swell-coverage — published 2022-01-08 — "After a turbulent, wind-whipped opening day, the Atlantic sorted itself out overnight as all the elements came together for a massive day of surfing at Nazare."

**2022-01-12 — Lucas Chianca and Pedro Calado, Biggest Paddle placings** · Reported
- Source: https://www.worldsurfleague.com/posts/504185/... — published 2022-07-07 — Chianca and Calado at Nazaré on January 12, 2022

**2022-02-09 — Jamie Mitchell, Biggest Paddle placing** · Reported
- Source: https://www.worldsurfleague.com/posts/504185/... — published 2022-07-07 — "Jamie Mitchell at Nazaré, Portugal on February 9, 2022"

**2022-02-10 — TUDOR Nazaré Tow Surfing Challenge, contest day** · Ratified
- Face Height: "clean, 40-to-50-foot waves"
- Source 1: https://thecitylife.org/2022/02/10/chianca-and-gabeira-take-top-honors-at-tudor-nazare-tow-surfing-challenge-presented-by-jogos-santa-casa/ — published 2022-02-10 — "The World Surf League (WSL) TUDOR Nazaré Tow Surfing Challenge Presented by Jogos Santa Casa took place today at Praia de Norte, Nazaré, Portugal and the world's best big wave surfers reveled in the clean, 40-to-50-foot waves on offer."
- Source 2: https://www.worldsurfleague.com/events/2022/bwt/20/tudor-nazare-tow-surfing-challenge/results — event window "Feb 1 - Mar 31, 2022", Round 1 six heats on "Feb 10"
- Source 3: https://www.worldsurfleague.com/posts/501756/2022-red-bull-big-wave-award-nominees-announced — published 2022-05-24 — Michelle des Bouillons, Ride of the Year nominee, "at Nazaré, Portugal on February 10, 2022"
- Winners: Lucas Chianca (men's and team), Maya Gabeira (women's) — a different result set from
  the December 2021 event, which is what establishes these as two distinct contests.

**2022-02-25 — João Macedo (Biggest Tow, 2nd) and Lucas Chianca (Ride of the Year nominee)** · Reported
- Source: https://www.worldsurfleague.com/posts/504185/... — published 2022-07-07 — "João Macedo at Nazaré on February 25, 2022"; and https://www.worldsurfleague.com/posts/501756/2022-red-bull-big-wave-award-nominees-announced — published 2022-05-24 — Chianca "at Nazaré, Portugal on February 25, 2022"

**2022-02-26 — Mason Barnes wins the Men's Biggest Tow Award** · Ratified
- Face Height: not stated on the source page.
- Source 1: https://www.worldsurfleague.com/posts/504185/... — published 2022-07-07 — Biggest Tow (men) 1st "Mason Barnes at Nazaré on February 26, 2022"
- Source 2: https://www.worldsurfleague.com/posts/501756/2022-red-bull-big-wave-award-nominees-announced — published 2022-05-24 — "Mason Barnes at Nazaré, Portugal on February 26, 2022"
- **Flag:** a contradicting date circulates for this ride. See *Date ambiguities and contradictions*.

### 2022/23

No entries. **This is an unknown, not a negative.** See *Known limitations*.

### 2023/24

**2024-01-22 — TUDOR Nazaré Big Wave Challenge, contest day** · Ratified
- Face Height: "epic, 30-to-40 foot waves"
- Source 1: https://www.surfnewsnetwork.com/green-alert-countdown-called-on-for-tudor-nazare-big-wave-challenge/ — published 2024-01-22 — "The TUDOR Nazaré Big Wave Challenge unfolded today in epic, 30-to-40 foot waves at the world-famous Praia do Norte in Nazaré, Portugal."
- Source 2: https://www.worldsurfleague.com/events/2023/bwt/193/tudor-nazar-big-wave-challenge/results — the event schedule row reads "Jan 22BWEvent 02"; event marked Completed; winners "Pedro Scooby & Lucas Chianca, and Maya Gabeira"
- **Note on the year label:** WSL files this as the "2023" event because it names an event by
  the year its waiting period opens. It ran in January 2024. The Big-Wave Season is 2023/24
  either way.

### 2024/25

**2025-02-18 — TUDOR Nazaré Big Wave Challenge, contest day** · Ratified
- Face Height: "some exceeding 10 meters" (an observer estimate of the wave face, not a Significant Wave Height)
- Source 1: https://nazarewaves.com/en/news/253 — published 2025-02-18, modified 2025-02-20 — "On February 18, 2025, the annual Tudor Nazaré Big Wave Challenge took place"
- Source 2: https://www.worldsurfleague.com/events/2024/bwt/334/tudor-nazar-big-wave-challenge/results — event window "Nov 1, 2024 - Mar 31, 2025", marked Completed; winners "Nic von Rupp & Clement Roseyro, and Justine Dupont"
- **Flag:** the WSL results page I retrieved shows the waiting period but not the run date, so
  the day itself is carried by nazarewaves.com. A WSL recap page
  (https://www.worldsurfleague.com/posts/539639/tudor-nazare-big-wave-challenge-recap,
  published 2025-02-25) exists and confirms the event but likewise did not yield a run date.

### 2025/26

**2025-12-13 — TUDOR Nazaré Big Wave Challenge, contest day** · Ratified
- Face Height: "45-60 foot waves"
- Source 1: https://www.surfnewsnetwork.com/tudor-yellow-alert-called-for-tudor-nazare-big-wave-challenge/ — published 2025-12-13 — "45-60 foot waves at the iconic Praia do Norte in Nazaré, Portugal"
- Source 2: https://nazarewaves.com/en/news/271 — published 2025-12-13, modified 2025-12-18 — "The 2025/26 edition of the Tudor Nazaré Big Wave Challenge once again placed Praia do Norte – Nazaré at the centre of the global surfing scene this Saturday, 13 December 2025"
- Source 3: https://www.worldsurfleague.com/events/2025/bwt/472/tudor-nazar-big-wave-challenge/main — event window "Nov 1, 2025 - Mar 31, 2026", competition ran "Saturday, December 13, 2025"

## Date ambiguities and contradictions

**1. Two Nazaré contests ran in the 2021/22 season.** This looked like a duplicate record in
WSL's system and was checked before being accepted. It is real: the December 2021 event
(women's winner Justine Dupont) and the February 2022 event (women's winner Maya Gabeira)
have different result sets, sit on different WSL event pages with different waiting periods
("Nov 15, 2021 - Mar 31, 2022" and "Feb 1 - Mar 31, 2022"), and were reported by separate
same-day articles. Both are recorded.

**2. 2018-02-11 is inferred, not sourced.** The Nazaré Challenge "ran over two days", the
opening heats were Saturday 10 February, and WSL's win article published Sunday 11 February.
No page retrieved states 11 February as a competition day. The inference is recorded as a
flag on the entry rather than silently resolved.

**3. 2017-02-28 joins two pages.** Francisco Porcella won the 2017 TAG Heuer XXL Biggest
Wave Award for a Nazaré ride, but the winners announcement does not restate the date. The
date comes from the nominees list, where Porcella has exactly one Nazaré entry, dated 28
February 2017. Search-engine summaries encountered during this research asserted the winning
ride was 24 October 2016 instead; that assertion could not be traced to any page that was
actually fetched, and 24 October 2016 is the date of *four other surfers'* nominations. The
2017-02-28 date is what the WSL nominee page says, and the contradiction is recorded here
rather than resolved.

**4. Mason Barnes's Biggest Tow date.** Two WSL pages (nominees, 2022-05-24; winners,
2022-07-07) both say 26 February 2022. A third-party claim of 4 March 2022 surfaced in search
results but was not retrievable from a fetched source. Recorded as 26 February with the
contradiction noted.

**5. Russell Bierke's Nazaré nomination.** A search summary placed it on 26 January 2019; the
WSL nominees page as fetched says 9 November 2018. The fetched page wins, and 2019-01-26 is
therefore **not** recorded. It is listed under *Unverified leads*.

**6. Sources routinely publish a day late or say only "Monday".** Both 2013 entries rest on
"Monday" plus a publication date. In each case the weekday and the published date are mutually
consistent with exactly one calendar day (2013-01-28 and 2013-10-28, both Mondays), so the
resolution is arithmetic rather than judgement. Reviewers should still treat these two as the
least date-certain of the non-flagged entries.

**7. Europe/Lisbon vs. publication timezone.** All contest and award sources describe the
session in local Nazaré terms ("today", "this morning", "this Saturday"), so no timezone
conversion was applied anywhere. Guinness record pages give a bare calendar date and are
assumed to be the local session date. No source examined gave a timestamp precise enough for
a timezone question to arise.

## Unverified leads

Things worth chasing that could **not** be confirmed from a page fetched in this research.
None of these are in the table.

- **2019-01-26** — Russell Bierke wipeout at Nazaré. Appears in search summaries; the WSL
  nominees page gives 9 November 2018 for his Nazaré ride. Needs the WSL wipeout nominee
  video page to settle.
- **2016-10-24 as Porcella's award-winning ride** — see contradiction 3. Settling this needs
  the WSL Big Wave Awards video page for the winning entry.
- **2022-03-04** — alternative date for Mason Barnes's Biggest Tow ride. See contradiction 4.
- **Hugo Vau's "Big Mama" claim (~115 ft), reportedly 2018-01-18.** Widely repeated. 2018-01-18
  is already in the table on Gabeira's ratified record, so the day is not at risk, but the Vau
  claim itself was not verified here and no Face Height for it is recorded.
- **Sebastian Steudtner's post-2020 re-measurement claims (~93.7 ft).** Referenced in secondary
  coverage as a possible new record from a later session. No date and no ratification were
  retrieved. Not recorded.
- **The 2022/23 season.** No Nazaré contest ran and the Big Wave Awards did not run an edition
  covering it, which removes both of this list's main date sources for that winter. Secondary
  coverage describes it as an "atypical season with few giant swells", but that was not
  confirmed from a primary source and, per rule 3, is **not** recorded as evidence of small
  surf. Photographer archives and Portuguese-language press are the obvious next place to look.
- **The 2010/11 season.** Praia do Norte was not internationally covered before McNamara's
  2011 record, and issue #10 admits pre-2011 days only at Ratified tier. No ratified day was
  found. This is an absence of evidence.
- **Red Bull, Surfline, Surfer and SurferToday** all returned HTTP 403 to automated fetching
  during this research. They carry same-day Nazaré swell reporting and would likely add
  Documented-tier days, particularly for 2022/23 and for non-contest swells generally. They
  are the highest-value target for the next pass.

## Known limitations

**This list has no negatives, and cannot be given any.** Every entry here says "this day was
giant". Nothing here says "this day was not". A day is absent from this list when a contest
did not run, an award was not given and a journalist did not publish — which correlates with
wave size only loosely. Nazaré runs giant on midweek days with no cameras present, and Big
Wave Award coverage stops entirely after the 2022 edition.

The consequence for #12 is specific and should be stated in whatever the model reports:

- **Recall is measurable.** Given a threshold, we can ask what fraction of these 38 days the
  system would have called. That number is meaningful.
- **Precision is not measurable.** A day the system calls that is absent from this list may be
  a false positive or may be a genuinely giant day that nobody wrote about. We cannot tell
  which, and no amount of care with this list changes that. Any precision figure computed
  against it is a lower bound at best and should not be published as precision.

**Coverage is driven by media, not by the ocean.** Nine entries in 2021/22 and zero in
2022/23 reflects the Big Wave Awards running a 2022 edition and then stopping. Seasons after
2021/22 are represented by contest days alone — one day per season. A calibration that
weights seasons equally will over-weight 2021/22 and under-weight everything after it.

**Face Height figures here are observer estimates and are not comparable across entries.**
"30-to-40 foot" from a WSL commissioner, "45-60 foot" from a wire report and "26.21 m" from
an 18-month Guinness measurement process are three different kinds of number. Only the
Guinness figures are measurements. None of them are Significant Wave Height and none may be
used as a target or as a scale for one — ADR 0002 already measured the coupling as weak, and
finding 4 of `analysis/buoy_coverage/README.md` shows two record days near 5.3 m Hs while a
swell 50% larger produced no comparable wave.

**Evidence class is not resolved in this document.** Issue #10 requires each entry to record
whether its conditions are buoy-measured or hindcast-only. That is a join against the
Monican02 record and belongs in the machine-readable file, not here. From
`analysis/buoy_coverage/`, Monican02 recorded 2011-11-01, 2017-11-08, 2018-01-18, 2020-10-29,
2024-01-22, 2025-02-18 and 2025-12-13, and recorded nothing on 2013-10-28. Monican02 recorded
nothing at all in 2013/14 or 2016/17, so **the six 2016/17 entries and the 2013/14 entry are
hindcast-only by construction** — seven of 38, about 18%. The remaining entries are untested.

**The tier boundary between Ratified and Reported is a judgement about sources, not about
waves.** Seventeen entries sit at Reported solely because a Big Wave Award nomination is one
origin rather than two. If #12's threshold moves materially depending on whether Reported
days are included, that is a finding to publish, in the same spirit as the buoy-measured
versus full-set split the ticket already requires.

## Corrections to `analysis/buoy_coverage/candidate_xxl_days.csv`

The provisional file says of itself that its dates are "recalled and spot-checked, not
systematically sourced". All eight were re-checked independently. **Seven of the eight dates
are correct. One row carries a wrong event attribution, and two rows are mis-attributed in a
way that matters less but should still be fixed.**

**1. `2013-10-28,McNamara ~100 ft claim (never ratified)` — wrong surfer, and the date belongs
to a different event.** Garrett McNamara's ~100 ft claim was **2013-01-28**, nine months
earlier (TIME and LAist, both published 2013-01-30, both naming "Monday, January 28").
2013-10-28 is a genuinely giant day, but it is **Carlos Burle's ride and Maya Gabeira's
near-drowning** (ABC News 2013-10-29, Christian Science Monitor 2013-10-30, National
Geographic 2013-11-07). Both days are in the table above, correctly attributed.

This matters more than a naming slip. The two dates are in **different Big-Wave Seasons**
(2012/13 and 2013/14), so any seasonal analysis built on the CSV attributes McNamara's
session to the wrong winter. It also means the provisional file was missing 2013-01-28
entirely.

**2. `2020-10-29,Laureano 101 ft claim (never ratified)` — under-stated.** 2020-10-29 is a
**Guinness-ratified world record day**: Sebastian Steudtner's 26.21 m / 86 ft, still the
men's record, ratified after an 18-month measurement process. Recording this day as an
unratified claim puts the strongest single day in the record at the wrong tier. António
Laureano's separate 101 ft claim from the same day was not verified in this research and is
not recorded.

**3. `2024-01-22,2025-02-18,2025-12-13` labelled `TUDOR Nazare Big Wave Challenge` — all three
dates confirmed correct.** Worth noting because WSL's own event pages label these the "2023",
"2024" and "2025" events respectively (WSL names an event by the year its waiting period
opens), which is an easy way to introduce a one-year error. The Big-Wave Seasons are 2023/24,
2024/25 and 2025/26.

**4. `2018-01-18,Gabeira women's world record,ratified` — correct**, and the record was
68 ft / 20.72 m. It has since been superseded by her own 2020-02-11 ride at 73.5 ft. The CSV
does not carry 2020-02-11, which is both a ratified record day *and* a contest day, and is
the best-evidenced day in this entire list.

**5. `2011-11-01` and `2017-11-08` — both correct.**

The CSV should not be edited by this ticket; it is a record of what #2 believed. The
machine-readable Gold Day file built from this document supersedes it, and
`analysis/buoy_coverage/README.md` finding 4 should be read with correction 1 in mind: the
row it labels "2013-10-28 McNamara ~100 ft claim" is the Burle/Gabeira day.

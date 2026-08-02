"""Build the machine-readable Gold Day file from the research document.

`README.md` is the source of truth and stays hand-written: it is where a human records
what a source said, argues about a tier, and flags an ambiguity. This script turns that
document into `gold_days.jsonl` — one JSON object per line, which #12 reads to calibrate
the Go Call threshold.

**Derived, never retyped.** Ticket #10 says the machine-readable file "is built from this
document", and building it is the only way to keep the two from drifting: 38 entries and
around fifty sources transcribed by hand is precisely where a wrong date enters a file
whose entire purpose is that a stranger can trust it. Correct the README and re-run this.

The script also refuses to emit a file that breaks the ticket's protocol — see `check`.
A Gold Day recorded on weak evidence does not add noise, it silently moves the threshold
that decides whether someone is told to book a flight.

Run:
    .venv/Scripts/python.exe analysis/gold_days/build.py
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
README = HERE / "README.md"
OUTPUT = HERE / "gold_days.jsonl"
BUOY = HERE.parent / "buoy_coverage" / "output"

# ADR 0002 makes Monican02 the Proxy Target, so it alone decides whether a day's
# conditions were measured. Monican01 sits further off and is a cross-check, not the
# target — a day it recorded and Monican02 missed is still hindcast-only for our purposes.
PROXY_TARGET = "Monican02"

TIERS = {"Ratified": "ratified", "Documented": "documented", "Reported": "reported"}

ENTRY = re.compile(
    r"^\*\*(?P<date>\d{4}-\d{2}-\d{2}) — (?P<title>.+?)\*\*"
    r" · (?P<tier>Ratified|Documented|Reported)"
    r"(?P<inferred> · \*\*date inferred\*\*)?\s*$"
)
SEASON = re.compile(r"^### (?P<season>\d{4}/\d{2})\s*$")
BULLET = re.compile(r"^- (?P<body>.*)$")
URL = re.compile(r"https?://[^\s)]+")
PUBLISHED = re.compile(r"(?:published|updated) (\d{4}-\d{2}-\d{2})")
QUOTE = re.compile(r"[\"“]([^\"”]+)[\"”]")


def full_urls(text: str) -> dict[str, str]:
    """Map every abbreviated WSL post URL back to the full one written elsewhere.

    Several entries cite a long WSL post as `.../posts/504185/...` after writing it out in
    full earlier. A truncated URL is not auditable — a stranger cannot open it — so the
    emitted file always carries the full form. Kept as a build step rather than a README
    edit because the abbreviation genuinely helps a human reading the document.
    """
    expansions: dict[str, str] = {}
    for url in URL.findall(text):
        if url.endswith("..."):
            continue
        post = re.match(r"(https://www\.worldsurfleague\.com/posts/\d+)/", url)
        if post:
            expansions.setdefault(post.group(1), url)
    return expansions


def expand(url: str, expansions: dict[str, str]) -> str:
    if not url.endswith("..."):
        return url
    post = re.match(r"(https://www\.worldsurfleague\.com/posts/\d+)/", url)
    if post and post.group(1) in expansions:
        return expansions[post.group(1)]
    return url


def evidence_classes() -> dict[str, str]:
    """Which days' conditions the Proxy Target actually recorded.

    Ticket #10 requires every entry to state this, and it is a join rather than a
    judgement, so it is computed here instead of being asserted in prose.

    Two sources, both from `analysis/buoy_coverage/`:

    - a season Monican02 recorded *nothing* in makes every day in it hindcast-only by
      construction, without needing a per-day reading;
    - `candidate_xxl_day_readings.csv` carries per-day readings for the days #2 checked.

    Everything else is `unknown` — deliberately, and not the same as hindcast-only. It
    means nobody has looked yet, and saying so is the honest answer. Resolving the rest
    needs the full Monican02 series, which is #9's work and needs Copernicus credentials.
    """
    classes: dict[str, str] = {}

    empty_seasons = set()
    with (BUOY / "coverage_by_season.csv").open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["platform"] == PROXY_TARGET and float(row["coverage_pct"]) == 0.0:
                empty_seasons.add(row["season"])

    with (BUOY / "candidate_xxl_day_readings.csv").open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            reading = row.get(PROXY_TARGET, "").strip()
            classes[row["date"]] = "buoy_measured" if reading else "hindcast_only"

    return {"__empty_seasons__": empty_seasons, **classes}  # type: ignore[dict-item]


def classify(date: str, season: str, known: dict[str, Any]) -> str:
    if season in known["__empty_seasons__"]:
        # Stronger than a missing per-day reading: the instrument recorded nothing all
        # season, so no lookup is needed and none could change the answer.
        return "hindcast_only"
    return known.get(date, "unknown")


def parse_source(body: str, expansions: dict[str, str]) -> dict[str, Any] | None:
    urls = URL.findall(body)
    if not urls:
        return None
    published = PUBLISHED.search(body)
    return {
        "url": expand(urls[0], expansions),
        "published": published.group(1) if published else None,
        # Every quoted fragment on the line. The README's convention is that quoted text
        # is verbatim from the page and unquoted text is the document's own summary, so
        # only the quoted parts are carried as evidence.
        "quotes": QUOTE.findall(body),
        "corroboration_only": body.startswith("Corroboration"),
    }


def parse(text: str) -> list[dict[str, Any]]:
    expansions = full_urls(text)
    known = evidence_classes()
    entries: list[dict[str, Any]] = []
    season = None
    current: dict[str, Any] | None = None

    for raw in text.splitlines():
        if match := SEASON.match(raw):
            season = match.group("season")
            continue

        if match := ENTRY.match(raw):
            current = {
                "date": match.group("date"),
                "season": season,
                "title": match.group("title").strip(),
                "tier": TIERS[match.group("tier")],
                "date_certainty": "inferred" if match.group("inferred") else "sourced",
                "evidence_class": classify(match.group("date"), season or "", known),
                "face_height": None,
                "sources": [],
                "flags": [],
                "notes": [],
            }
            entries.append(current)
            continue

        if current is None:
            continue

        bullet = BULLET.match(raw)
        if not bullet:
            # A continuation line of the previous bullet, or prose between entries. Only
            # flags run to a second line, and losing half a flag would be worse than
            # carrying none.
            if raw.startswith("  ") and current["flags"]:
                current["flags"][-1] += " " + raw.strip()
            continue

        body = bullet.group("body")

        if body.startswith("Quote:"):
            # Some entries put the quote on its own bullet under the source rather than on
            # the same line. It is evidence for the source above it either way.
            if current["sources"]:
                current["sources"][-1]["quotes"].extend(QUOTE.findall(body))
            else:
                current["notes"].append(body)
        elif body.startswith("Face Height:"):
            # Kept as the source's own words, not parsed into a number. These are observer
            # estimates of the breaking wave in ranges like "30-to-40-foot"; ADR 0002
            # measured the Face-Height-to-Hs coupling as weak, and reducing them to a
            # float would invite exactly the use CONTEXT.md forbids.
            current["face_height"] = body[len("Face Height:") :].strip()
        elif body.startswith("**Flag:**"):
            current["flags"].append(body[len("**Flag:**") :].strip())
        elif source := parse_source(body, expansions):
            current["sources"].append(source)
        else:
            current["notes"].append(re.sub(r"\*\*", "", body).strip())

    return entries


def check(entries: list[dict[str, Any]]) -> list[str]:
    """Refuse to emit a file that breaks ticket #10's protocol.

    Every rule here is one the ticket states. They are checked on every build because the
    README is hand-edited and will be for years, and the failure mode of a bad entry is
    silent: nothing downstream can tell a well-sourced day from a guess.
    """
    problems: list[str] = []

    for entry in entries:
        where = f"{entry['date']} ({entry['tier']})"

        if not entry["season"]:
            problems.append(f"{where}: no Big-Wave Season heading above it")
        if entry["evidence_class"] not in {"buoy_measured", "hindcast_only", "unknown"}:
            problems.append(f"{where}: unknown evidence class {entry['evidence_class']!r}")

        cited = [s for s in entry["sources"] if not s["corroboration_only"]]
        if not cited:
            problems.append(f"{where}: no source — rule 1, every entry carries a URL")
        if not any(s["quotes"] for s in cited):
            problems.append(f"{where}: no verbatim quote on any source — rule 1")
        if not any(s["published"] for s in cited):
            problems.append(f"{where}: no source publication date — rule 1")

        # Rule 2, as amended after the #24 review: it governs Documented tier and above.
        # Reported tier is *defined* as a single credible source, so requiring two of it
        # would forbid the tier the ticket defines.
        if entry["tier"] == "documented" and len(cited) < 2:
            problems.append(f"{where}: Documented tier needs two independent sources — rule 2")

        # Rule 4: a date that is not pinned by a source must say so rather than pass as
        # precise. Any entry carrying an inference must be marked, and a marked one must
        # explain itself.
        if entry["date_certainty"] == "inferred" and not entry["flags"]:
            problems.append(f"{where}: date is inferred but nothing records the ambiguity — rule 4")

    dates = [entry["date"] for entry in entries]
    duplicates = {date for date in dates if dates.count(date) > 1}
    if duplicates:
        problems.append(f"the same day appears more than once: {sorted(duplicates)}")

    return problems


def render(entries: list[dict[str, Any]]) -> str:
    return "".join(
        json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n" for entry in entries
    )


def main(argv: list[str] | None = None) -> int:
    verify_only = "--check" in (argv if argv is not None else sys.argv[1:])

    entries = parse(README.read_text(encoding="utf-8"))
    entries.sort(key=lambda entry: entry["date"])

    if problems := check(entries):
        print(f"{len(problems)} problem(s); nothing written:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    rendered = render(entries)

    if verify_only:
        # The two must not drift. The README is hand-edited and will be for years, and a
        # correction made there but never rebuilt would leave #12 calibrating against a
        # stale file while the document a reviewer reads says something else.
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != rendered:
            print(
                f"{OUTPUT.name} is out of date with README.md — re-run without --check",
                file=sys.stderr,
            )
            return 1
        print(f"{OUTPUT.name} matches README.md ({len(entries)} Gold Days)")
        return 0

    OUTPUT.write_text(rendered, encoding="utf-8", newline="\n")

    tiers = {tier: sum(1 for e in entries if e["tier"] == tier) for tier in TIERS.values()}
    classes = {
        name: sum(1 for e in entries if e["evidence_class"] == name)
        for name in ("buoy_measured", "hindcast_only", "unknown")
    }
    print(f"{len(entries)} Gold Days -> {OUTPUT.relative_to(HERE.parent.parent)}")
    print(f"  tiers: {tiers}")
    print(f"  evidence: {classes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

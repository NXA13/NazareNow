"""Every prose mention of a shipped bar's current value says whether it means *now*.

Ticket #64. #60 moved the Watch bar by 0.1 s — the smallest step the calibration's resolution
allows — and the review that followed found five prose claims falsified by it, in five files,
three of which #60 never touched. Nothing failed. CI was green throughout.

The three executable assertions did their job: `test_calls.py`'s `WATCH_PERIOD_S`, and the two
in `test_baseline_is_fixed.py`, all failed loudly and were updated. They are the intended
design and this file does not replace them. The gap is that the tripwires only cover code,
and about seven further assertions of the same number live in prose, where nothing checks
anything.

**Why the obvious fix is wrong.** Most of that prose is deliberately historical — "574 → 530
Watch" is #58's figure and must stay #58's figure — so deriving every number from
`thresholds.json` would destroy the record this project keeps on purpose. What is needed is a
way to tell a *stale current-state claim* from a *correct historical one*, and that is a
judgement about writing, not a transform.

**The rule this file enforces, and why it is cheap.** A superseded value is, by definition,
not the current one. So a checker never has to reason about history: it only has to police
numbers that equal what is shipped *today*. Every such number carries a marker saying which:

    the Watch bar is 11.4 s <!--now:watch_minimum_swell_period_s-->
    #43 set it at 11.4 s <!--fixed:#43-->

`now:` says "this is what ships", and is verified against `thresholds.json` on every run.
`fixed:` says "this number is not a claim about what ships, and must not be updated when a bar
moves". It is never verified, because nothing in the repository can settle it.

**Both are needed, and the second covers two different things.** One is history — #43's figure
stays #43's figure. The other is a measured result that happens to coincide: the candidate
table in `analysis/amplification_model/README.md` records what each fitting choice *would*
produce, and several produce today's bars. Update those when a bar moves and the experiment is
falsified; a rule offering only `now:` would invite exactly that, which is worse than the
defect it set out to fix.

Moving a bar then surfaces exactly the sites that need review. Every `now:` marker on the old
value fails, naming its file and line. `fixed:` figures stop matching anything and are ignored,
which is correct — they were true when written and still are. See ADR 0012.

In Python comments the same markers are written `[now:key]` and `[fixed:ref]`, since `<!---->`
means nothing there.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
THRESHOLDS = ROOT / "backend" / "src" / "nazarenow" / "thresholds.json"

COVERED_BARS = {
    "minimum_significant_wave_height_m": "m",
    "watch_minimum_swell_period_s": "s",
    "go_call_minimum_swell_period_s": "s",
    "maximum_wind_speed_kmh": "km/h",
    "light_wind_exemption_kmh": "km/h",
}
"""The bars whose values are policed in prose, and the unit each is written with.

**The unit is half the rule.** Requiring it is what keeps this from flagging every `2.75` in
the repository — a bar is a physical quantity and the prose that states one says so.

`swell_arc` and `offshore_wind_arc` are deliberately absent. Their bounds are 255, 330, 20 and
180: bare integers that collide with ordinary prose (degrees of bearing, counts, other
thresholds' units) far too often for a value-match rule to mean anything. They have also never
moved, where the period bars have moved three times. If an arc is ever recalibrated this rule
does not cover it, and that limit is recorded here rather than discovered later.
"""

COVERED = (
    "analysis/amplification_model/README.md",
    "analysis/backtest/README.md",
    "analysis/calibration/README.md",
    "analysis/calibration/calibrate.py",
    "analysis/distribution_coverage/README.md",
    "analysis/forecast_error/README.md",
    "analysis/model_spread/README.md",
    "analysis/overlap/README.md",
    "analysis/overlap/measure.py",
    "analysis/wind_products/README.md",
    "backend/tests/test_calls.py",
    "docs/adr/0002-proxy-target-with-gold-calibration.md",
    "docs/adr/0003-tiered-calls-driven-by-model-spread.md",
    "docs/adr/0009-light-wind-has-no-direction.md",
    "docs/adr/0010-the-watch-tier-has-a-price.md",
    "docs/adr/0011-copernicus-ibi-is-the-wave-hindcast.md",
    "docs/adr/0012-prose-says-whether-a-number-is-current.md",
    "docs/adr/0013-the-profiles-width-is-called-drift.md",
)
"""The files this rule covers, named rather than globbed.

#64 asks for the six Markdown files and the two comment sites the review found; this is those
plus the ADRs and analysis READMEs that assert the same bars, which is where the same defect
would land next. Naming them makes the coverage reviewable and the omissions deliberate — a
glob over `**/*.md` would pull in `CONTEXT.md`, every ticket write-up and this docstring, and
the rule would be relaxed within a week to keep it quiet.

A new file asserting a bar is not covered until it is added here. That is a real hole, and the
smaller one: a rule nobody can read the boundary of gets disabled instead of extended.

**ADRs 0012 and 0013 were in that hole, and 0012 is this rule's own decision record** (#75).
It states the convention with a live `now:` marker on a real bar value, so a bar move left the
document defining "prose says whether a number is current" teaching the convention with a
number that was not. Covering it needs `without_specimens`, because a document explaining the
notation necessarily writes the notation down.
"""

MARKER = re.compile(r"(?:<!--\s*|\[)(now|fixed):([^\s\]>-]+)\s*(?:-->|\])")

CODE_SPAN = re.compile(r"`[^`]*`")


def without_specimens(line: str) -> str:
    """The line with its inline code spans blanked out.

    A marker or a bar value inside backticks is a **specimen of the notation, not a use of
    it**. ADR 0012 has to be able to write `[now:key]` while explaining what `now:` means,
    and `value_pattern` below illustrates the unit rule with a bar value. Reading those as
    claims makes the convention impossible to document — and a rule that cannot be written
    down without tripping itself is one that gets switched off rather than extended.

    This is what lets `COVERED` include the ADRs that define the rule. Without it the two
    documents most worth policing are the two it cannot read.

    Blanked to the same width rather than deleted, so a column position in the blanked line
    still refers to the same character of the original.
    """
    return CODE_SPAN.sub(lambda span: " " * len(span.group()), line)


RERUN = (
    "mark it <!--now:KEY--> if it states what ships today, or <!--fixed:REF--> if it is a "
    "historical figure that happens to equal the current one (ADR 0012). In a Python comment "
    "write [now:KEY] / [fixed:REF]"
)


def shipped() -> dict[str, float]:
    body = json.loads(THRESHOLDS.read_text(encoding="utf-8"))
    return {key: float(body[key]) for key in COVERED_BARS}


def value_pattern(value: float, unit: str) -> re.Pattern[str]:
    """A number equal to `value`, written with its unit.

    The lookbehind stops `11.4` matching inside `111.4`, and the `\\b` after the unit stops
    `35 km/h` matching `35 km/hr`. Trailing zeros are not written in this repo's prose, so
    `f"{value:g}"` is the spelling to look for — `2.75`, `11.4`, `35`.
    """
    return re.compile(rf"(?<![\d.]){re.escape(f'{value:g}')}\s*{re.escape(unit)}\b")


def superseded_blocks(lines: list[str]) -> set[int]:
    """Line numbers inside a blockquote that a `fixed:` marker has scoped to the whole block.

    This repository keeps superseded records rather than deleting them, and writes them as
    blockquotes — `analysis/backtest/README.md` carries three, one of which says in so many
    words "that row was 'now' when #43 shipped and is no longer". Such a block can hold a dozen
    bar values, none of them a claim about today.

    Marking each line of those separately would put thirty markers in the repository to say one
    thing thirty times, and a rule that verbose gets deleted. So one `fixed:` on any line of a
    blockquote covers the contiguous block it sits in.

    The scoping is deliberately limited to blockquotes. Anywhere else a marker covers its own
    line only, because ordinary prose has no delimiter a reader and a checker would agree on.
    """
    quoted = [number for number, line in enumerate(lines, 1) if line.lstrip().startswith(">")]
    covered: set[int] = set()
    for number in quoted:
        scanned = without_specimens(lines[number - 1])
        if not MARKER.search(scanned):
            continue
        if not any(kind == "fixed" for kind, _ in MARKER.findall(scanned)):
            continue
        block = {number}
        for step in (-1, 1):
            cursor = number + step
            while 1 <= cursor <= len(lines) and lines[cursor - 1].lstrip().startswith(">"):
                block.add(cursor)
                cursor += step
        covered |= block
    return covered


def sites(
    root: Path = ROOT,
    covered: Iterable[str] = COVERED,
    current: dict[str, float] | None = None,
) -> list[tuple[str, int, str, str, set[str]]]:
    """Every covered line holding a current bar value, with the markers that apply to it.

    `root`, `covered` and `current` are parameters so the rule can be run against a tree whose
    right answer is known — see `TestTheRuleCatchesWhatItIsFor`. Defaulted to the repository,
    which is what the four tests below scan. #64's hole survived because this walked only the
    real tree: the sole way to try it was to move a bar by hand and read the output, and a
    check nobody can feed a known-bad input to is a check nobody re-runs.
    """
    current = shipped() if current is None else current
    found = []
    for relative in covered:
        path = root / relative
        if not path.exists():
            raise AssertionError(f"{relative} is listed in COVERED but does not exist")
        lines = path.read_text(encoding="utf-8").splitlines()
        scoped = superseded_blocks(lines)
        for number, line in enumerate(lines, 1):
            scanned = without_specimens(line)
            # Over the bars `current` carries, not over `COVERED_BARS`, so a fixture can name
            # one bar without supplying values for the other four.
            for key, value in current.items():
                if value_pattern(value, COVERED_BARS[key]).search(scanned):
                    markers = {f"{kind}:{ref}" for kind, ref in MARKER.findall(scanned)}
                    if number in scoped:
                        markers.add("fixed:block")
                    found.append((relative, number, key, line.strip(), markers))
    return found


def test_every_current_bar_value_in_prose_is_marked() -> None:
    """A bar's current value, unmarked, is a claim nothing can check.

    Marked *per bar*, not per line. A table row can carry three of these at once — the
    calibration READMEs are full of `| 2.75 m | 11.4 s | 12.9 s |` — and accepting one marker
    for the row would leave the other two unchecked while the line looked handled. A single
    `fixed:` covers a whole line, because a line that is not about today is not about today
    for any of the bars on it.
    """
    unmarked = [
        f"{relative}:{number} ({key}) {line[:90]}"
        for relative, number, key, line, markers in sites()
        if f"now:{key}" not in markers
        and not any(marker.startswith("fixed:") for marker in markers)
    ]

    assert not unmarked, (
        f"{len(unmarked)} prose site(s) state a currently-shipped bar value without saying "
        f"whether they mean it as current or historical. For each, {RERUN}:\n"
        + "\n".join(f"  {site}" for site in unmarked)
    )


def claims(root: Path = ROOT, covered: Iterable[str] = COVERED) -> list[tuple[str, int, str, str]]:
    """Every `now:` marker in a covered file, found without reference to any value.

    **Not derived from `sites()`, and the difference is the whole check.** `sites()` finds
    lines holding a value that is current *today*, which is the right way to discover claims
    nobody has marked. It is exactly the wrong way to verify claims that are marked: the moment
    a bar moves, the line asserting its old value stops holding any current value, drops out of
    `sites()`, and its marker is never looked at again — so the one site guaranteed to be stale
    is the one that goes unchecked.

    That is not hypothetical. It was how this file worked until the rule was tried against a
    simulated one-step move of the Watch bar: three sites failed and two — ADR 0010's "the
    shipped Watch bar reads 11.4 s" and `calibrate.py`'s translation comment — sailed through,
    because they name that bar and nothing else. The two that slipped are the two whose whole
    sentence is the claim.
    """
    found = []
    for relative in covered:
        for number, line in enumerate(
            (root / relative).read_text(encoding="utf-8").splitlines(), 1
        ):
            for kind, reference in MARKER.findall(without_specimens(line)):
                if kind == "now":
                    found.append((relative, number, reference, line.strip()))
    return found


def test_every_now_marker_names_a_covered_bar_and_its_current_value() -> None:
    """`now:` is the half that can go stale, so it is the half that is verified.

    Two ways to fail, and both are the point. A marker naming a bar whose current value is not
    on the line is a claim the artifact contradicts — which is what a moved bar produces, in
    every file at once. A marker naming a key that is not a covered bar is a typo that would
    otherwise sit there being checked against nothing.
    """
    current = shipped()
    wrong = []
    for relative, number, reference, line in claims():
        if reference not in COVERED_BARS:
            wrong.append(f"{relative}:{number} names '{reference}', which is not a covered bar")
        elif not value_pattern(current[reference], COVERED_BARS[reference]).search(line):
            wrong.append(
                f"{relative}:{number} says this states the current {reference}, but the shipped "
                f"value is {current[reference]:g} {COVERED_BARS[reference]} and is not on the "
                f"line: {line[:70]}"
            )

    assert not wrong, (
        f"{len(wrong)} prose claim(s) disagree with thresholds.json — if a bar has just moved, "
        "these are the sites that need rewriting:\n" + "\n".join(f"  {site}" for site in wrong)
    )


def test_the_rule_covers_the_sites_the_review_found() -> None:
    """#64's evidence is five falsified claims in five files. Those files stay covered.

    Without this, the cheapest way to make the two tests above pass is to shorten `COVERED` —
    which would leave the rule green and the defect exactly where it was.
    """
    from_the_review = {
        "analysis/model_spread/README.md",
        "analysis/calibration/README.md",
        "analysis/backtest/README.md",
        "analysis/amplification_model/README.md",
        "docs/adr/0011-copernicus-ibi-is-the-wave-hindcast.md",
        "analysis/calibration/calibrate.py",
        "analysis/overlap/measure.py",
    }

    assert from_the_review <= set(COVERED), (
        f"these files carried #64's evidence and are no longer covered: "
        f"{sorted(from_the_review - set(COVERED))}"
    )


class TestTheRuleCatchesWhatItIsFor:
    """The rule, run against a tree whose right answer is known in advance.

    #64's first version passed the whole suite while missing the one site guaranteed to be
    stale, and it was found by simulating a moved bar by hand and reading the output. #75
    re-ran that simulation and the rule held — but "somebody ran it once" is exactly the state
    the hole was found in, and a checker that can only be pointed at the real repository can
    never be handed an input whose answer is known.

    So these plant the defect instead of hoping it never returns. Each names a bar value in a
    fixture file, sets `current` to something else, and asserts the rule says so.
    """

    BAR = "watch_minimum_swell_period_s"
    MOVED = {"watch_minimum_swell_period_s": 11.3}
    CURRENT = {"watch_minimum_swell_period_s": 11.4}

    def tree(self, tmp_path: Path, body: str) -> tuple[Path, tuple[str, ...]]:
        (tmp_path / "doc.md").write_text(body, encoding="utf-8")
        return tmp_path, ("doc.md",)

    def test_a_now_marker_left_on_a_moved_bar_is_reported(self, tmp_path: Path) -> None:
        """The defect the rule exists for, and the one its first version could not see.

        The line holds 11.4 and claims it is current; the shipped bar is 11.3. Because the
        line no longer holds *any* current value it never appears in `sites()`, which is why
        `claims()` is scanned independently.
        """
        root, covered = self.tree(tmp_path, f"the Watch bar is 11.4 s <!--now:{self.BAR}-->\n")

        stale = [
            (relative, number)
            for relative, number, reference, line in claims(root, covered)
            if not value_pattern(self.MOVED[reference], COVERED_BARS[reference]).search(line)
        ]

        assert stale == [("doc.md", 1)]

    def test_an_unmarked_current_value_is_reported(self, tmp_path: Path) -> None:
        root, covered = self.tree(tmp_path, "the Watch bar is 11.4 s today\n")

        found = sites(root, covered, self.CURRENT)

        assert [(f, n, k) for f, n, k, _, _ in found] == [("doc.md", 1, self.BAR)]
        assert found[0][4] == set(), "an unmarked line must carry no markers"

    def test_a_fixed_marker_exempts_the_line(self, tmp_path: Path) -> None:
        """`fixed:` is never verified, which is the half that must not be tightened."""
        root, covered = self.tree(tmp_path, "#43 set it at 11.4 s <!--fixed:#43-->\n")

        markers = sites(root, covered, self.CURRENT)[0][4]

        assert markers == {"fixed:#43"}

    def test_a_specimen_in_backticks_is_not_a_claim(self, tmp_path: Path) -> None:
        """What lets `COVERED` include the ADRs that define the rule.

        ADR 0012 writes `[now:key]` while explaining the notation. Read as a use rather than a
        mention, that is a marker naming a bar called "key", and the rule cannot be documented
        without tripping itself.
        """
        root, covered = self.tree(
            tmp_path, "markers are written `[now:key]` and the bar is `11.4 s`\n"
        )

        assert sites(root, covered, self.CURRENT) == []
        assert claims(root, covered) == []

    def test_one_fixed_marker_scopes_its_whole_blockquote(self, tmp_path: Path) -> None:
        """The concession that keeps thirty markers out of the superseded blocks."""
        root, covered = self.tree(
            tmp_path,
            "> a superseded block <!--fixed:#43-->\n> the Watch bar was 11.4 s\n\n"
            "the Watch bar is 11.4 s today\n",
        )

        found = {
            (number, tuple(sorted(markers)))
            for _, number, _, _, markers in sites(root, covered, self.CURRENT)
        }

        assert (2, ("fixed:block",)) in found, "the quoted line is covered by the block"
        assert (4, ()) in found, "prose after the block is not"

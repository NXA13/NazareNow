"""No identifier in the shipped source is named "confidence".

Ticket #76, ADR 0014. The glossary assigns "confidence" to Model Spread and puts it on that
entry's _Avoid_ list. ADR 0014 rules on what such a list forbids: **naming that concept by the
word**, as an identifier or as a noun in prose — not the English word itself, which the glossary
uses in three of its own definitions.

The half of that rule a checker can enforce is the identifier half. Prose needs a reader; an
identifier named `confidence` in `backend/src` or `frontend/src` does not, because after #76
there is no quantity in either tree the word could legitimately name.

**Why this exists at all.** #65 and #76 are the same defect twice — a naming collision sitting in
the codebase with CI green throughout, found by a review rather than by anything executable.
Before #76, `decide()` held two independent gates three lines apart: `confident` was the share of
the Predictive Distribution above the height bar, `agreement` was Model Spread, and the glossary
assigns the word to the second. Nothing checked that an editor attached the right gate to the
right word, and the two produce different Watches on purpose.

**Comments and docstrings are deliberately not read.** "Narrow spread means confidence" is the
glossary's own sentence and prose like it is legal everywhere. A rule that flagged it would be a
rule about the word rather than about naming, which is precisely what ADR 0014 declines to adopt.

**`analysis/` is deliberately outside the scope.** A Gold Day record's evidence tier is called its
"confidence" there, which names neither Model Spread nor a forecast quantity and never appears in
the same file as one. ADR 0014 leaves it, so policing that tree would flag a use the same decision
sanctions.

**`backend/tests` is not scanned; the frontend's co-located tests are.** That asymmetry is in the
trees, not in the rule: this file is *itself* named for confidence, as it has to be, so a Python
scan that reached `backend/tests` would flag its own module and its own test function. The
frontend keeps its tests beside the source under `frontend/src`, so they are swept with it — and
that is worth having rather than worth excluding, because `Forecast.test.tsx` held the old
`confidence-${date}` test id, and a guard blind to it would let the DOM contract drift away from
the component asserting it.

The hole this leaves is a Python test helper reintroducing the word. It is the smaller one: the
collision that matters is between a shipped gate and the shipped gate beside it.

**Only names are read, so a name hidden in a string is invisible.** `store.py` declares its
columns inside SQL text, which reaches the tree as one `ast.Constant` this never looks into. A
banned name could live there unpoliced. Reading string contents would mean reading prose, which
is the one thing ADR 0014 rules out.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

BANNED = "confiden"
"""The stem, so `confidence`, `confident` and `_confident_enough` are one rule rather than three.

Matched case-insensitively against identifiers, which is what makes `GO_CALL_CONFIDENCE` and
`Confidence` the same finding as `confident`.
"""

SHIPPED_PYTHON = ROOT / "backend" / "src"
SHIPPED_FRONTEND = ROOT / "frontend" / "src"

RERUN = (
    "name it for the quantity rather than for how sure the system is (ADR 0014). The share of "
    "the Predictive Distribution above the height bar is `height_bar_probability`; Model Spread "
    "is `agreement`"
)


def python_identifiers(tree: ast.AST) -> list[tuple[str, int]]:
    """Every name the source binds or reads, with the line it sits on.

    Comments and docstrings never reach here — comments are not in the tree at all, and a
    docstring is a `Constant` this does not look inside. That is the point: the rule is about
    what things are called, not about which words appear.

    `alias` covers `from nazarenow.decision import GO_CALL_CONFIDENCE`, so importing a banned
    name fails in the importing file too rather than only where it was defined.
    """
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        names: list[str] = []
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                names = [node.name]
            case ast.Name():
                names = [node.id]
            case ast.Attribute():
                names = [node.attr]
            case ast.arg():
                names = [node.arg]
            case ast.keyword() if node.arg is not None:
                names = [node.arg]
            case ast.alias():
                names = [part for part in (node.name, node.asname) if part]
            case ast.ExceptHandler() if node.name is not None:
                names = [node.name]
            case ast.Global() | ast.Nonlocal():
                names = list(node.names)
            case ast.MatchAs() | ast.MatchStar() if node.name is not None:
                names = [node.name]
            case ast.MatchMapping() if node.rest is not None:
                names = [node.rest]
            case _:
                continue
        found += [(name, getattr(node, "lineno", 0)) for name in names]
    return found


TYPESCRIPT_NAMES = (
    re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)"),
    re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)"),
    re.compile(r"\b(?:interface|type|class|enum)\s+([A-Za-z_$][\w$]*)"),
    re.compile(r"^\s*(?:readonly\s+)?([A-Za-z_$][\w$]*)\??:", re.MULTILINE),
    re.compile(r"\bclassName=\"([^\"]*)\""),
    re.compile(r"\bclassName=\{`([^`]*)`\}"),
    re.compile(r"\bdata-testid=\"([^\"]*)\""),
    re.compile(r"\bdata-testid=\{`([^`]*)`\}"),
)
"""What counts as a name in TypeScript: declarations, object and interface fields, and the two
things that reach the DOM.

TypeScript has no `ast` in the standard library and this rule does not justify a parser
dependency, so it reads the shapes a name can take here. The type and field patterns are not
decoration: `api.ts` is where the wire contract is declared, so a `confidence` field on `DayCall`
is exactly the collision this rule exists to stop, and a pattern set that only knew about
`function` would have watched the component while the contract drifted.

A comment mentioning confidence matches none of these, which is the same exemption the Python
side gets for free.
"""

CSS_NAMES = (re.compile(r"^\s*\.([\w-]+)", re.MULTILINE),)
"""The class selector, which is why `App.css` is scanned at all.

`.confidence-scope` is as much an identifier as the component was, and a rename that moved the
component but not its styling would leave the block unstyled with every test still passing.

**Kept away from `.ts` and `.tsx` deliberately.** Applied there it would match every
Prettier-wrapped method chain — a line beginning `.map(` reads as a selector — and, worse, it
would match a line inside a block comment, contradicting the exemption above. Restricting it by
extension is what keeps that promise true rather than nearly true.
"""


def matched_identifiers(
    source: str, patterns: tuple[re.Pattern[str], ...]
) -> list[tuple[str, int]]:
    """Every name the given patterns capture, with the line it sits on."""
    found: list[tuple[str, int]] = []
    for pattern in patterns:
        for match in pattern.finditer(source):
            line = source.count("\n", 0, match.start()) + 1
            found += [(match.group(1), line)]
    return found


def named_in(path: Path) -> list[tuple[str, int]]:
    """Every identifier in one file, read the way that file's language allows."""
    source = path.read_text(encoding="utf-8")
    if path.suffix == ".py":
        return python_identifiers(ast.parse(source, filename=str(path)))
    if path.suffix == ".css":
        return matched_identifiers(source, CSS_NAMES)
    return matched_identifiers(source, TYPESCRIPT_NAMES)


def scanned() -> list[Path]:
    """The two shipped trees, each read for the file kinds it holds."""
    files = list(SHIPPED_PYTHON.rglob("*.py"))
    for extension in ("*.ts", "*.tsx", "*.css"):
        files += SHIPPED_FRONTEND.rglob(extension)
    return sorted(files)


def offenders() -> list[str]:
    return [
        f"{path.relative_to(ROOT).as_posix()}:{line}: {name}"
        for path in scanned()
        for name, line in named_in(path)
        if BANNED in name.lower()
    ]


def test_no_shipped_identifier_is_named_for_confidence() -> None:
    """The rule. Every finding names its file, line and the identifier itself.

    Reported all at once rather than one per run, because a rename that misses three sites
    should surface as three sites rather than as three consecutive red runs.
    """
    failures = offenders()
    listed = "\n  ".join(failures)
    message = f"{len(failures)} identifier(s) named for confidence — {RERUN}:\n  " + listed
    assert not failures, message


def test_the_rule_reads_names_and_not_prose() -> None:
    """The exemption, asserted rather than assumed.

    ADR 0014's whole distinction is that "confidence" is legal in prose and illegal as a name.
    If this checker ever started reading comments it would still pass the test above on a clean
    tree, and would then fail the moment somebody quoted the glossary correctly.
    """
    prose = '# Narrow spread means confidence.\n"""Confidence, in a docstring."""\nx = 1\n'
    assert not [name for name, _ in python_identifiers(ast.parse(prose)) if BANNED in name.lower()]

    # The last line is the one that matters: a block comment whose continuation begins with a
    # dot is a selector to the CSS pattern and prose to a reader. Restricting that pattern by
    # extension is what makes the exemption true here rather than nearly true.
    tsx = (
        "// the confidence block\n"
        "/* confidence */\n"
        "const plausible = [1].map(x => x)\n"
        "  .filter(Boolean);\n"
        "/* a note about\n"
        " .confidence and what it wrapped */\n"
    )
    assert not [name for name, _ in matched_identifiers(tsx, TYPESCRIPT_NAMES) if BANNED in name]


def test_the_rule_reads_the_shapes_a_name_can_take() -> None:
    """The other half: every declaration form this scanner claims to cover, asserted.

    A pattern set is only as honest as the shapes it was tried against. `interface` is here
    because `api.ts` declares the wire contract, and a field on it is the collision this rule
    exists to stop — the case the first version of this scanner could not see.
    """
    declarations = (
        "interface Confidence { x: number }",
        "type Confidence = string",
        "class Confidence {}",
        "enum Confidence { A }",
        "function Confidence() {}",
        "const confidence = 1",
        "  confidence: number;",
        "  readonly confidence?: number;",
        'className="confidence"',
        "data-testid={`confidence-${day.date}`}",
    )
    for source in declarations:
        found = [name for name, _ in matched_identifiers(source, TYPESCRIPT_NAMES)]
        assert [name for name in found if BANNED in name.lower()], f"missed: {source}"

    assert [name for name, _ in matched_identifiers(".confidence-scope {", CSS_NAMES)]

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

**Test trees are not scanned, and that is the known hole.** A test helper could reintroduce the
word without failing anything. It is the smaller hole: the collision that matters is between a
shipped gate and the shipped gate beside it, and a boundary a reader can state in one sentence
survives, where one that flags a test name gets relaxed.
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
            case _:
                continue
        found += [(name, getattr(node, "lineno", 0)) for name in names]
    return found


FRONTEND_NAMES = (
    re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)"),
    re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)"),
    re.compile(r"\bclassName=\"([^\"]*)\""),
    re.compile(r"\bclassName=\{`([^`]*)`\}"),
    re.compile(r"\bdata-testid=\"([^\"]*)\""),
    re.compile(r"\bdata-testid=\{`([^`]*)`\}"),
    re.compile(r"^\s*\.([\w-]+)", re.MULTILINE),
)
"""What counts as a name on the frontend: declarations, and the two things that reach the DOM.

TypeScript has no `ast` in the standard library and this rule does not justify a parser
dependency, so it reads the four shapes the defect actually took — a component declaration, a
`className`, a `data-testid`, and the CSS selector the class is styled by. The last pattern is
why `App.css` is scanned: `.confidence-scope` is as much an identifier as the component was.

A comment mentioning confidence matches none of these, which is the same exemption the Python
side gets for free.
"""


def frontend_identifiers(source: str) -> list[tuple[str, int]]:
    """Every declared name, DOM class and test id, with the line it sits on."""
    found: list[tuple[str, int]] = []
    for pattern in FRONTEND_NAMES:
        for match in pattern.finditer(source):
            line = source.count("\n", 0, match.start()) + 1
            found += [(match.group(1), line)]
    return found


def offenders() -> list[str]:
    failures: list[str] = []
    for path in sorted(SHIPPED_PYTHON.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for name, line in python_identifiers(tree):
            if BANNED in name.lower():
                failures.append(f"{path.relative_to(ROOT).as_posix()}:{line}: {name}")
    frontend = [
        path
        for extension in ("*.ts", "*.tsx", "*.css")
        for path in SHIPPED_FRONTEND.rglob(extension)
    ]
    for path in sorted(frontend):
        for name, line in frontend_identifiers(path.read_text(encoding="utf-8")):
            if BANNED in name.lower():
                failures.append(f"{path.relative_to(ROOT).as_posix()}:{line}: {name}")
    return failures


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

    tsx = "// the confidence block\n/* confidence */\nconst plausible = 1;\n"
    assert not [name for name, _ in frontend_identifiers(tsx) if BANNED in name.lower()]

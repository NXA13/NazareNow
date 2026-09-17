"""Every third-party module the runtime imports must be a runtime dependency.

This guards a defect that reached the repository and would have surfaced only on a
deployed host: `httpx` was declared in the `dev` extra, but imported by `pipeline`,
`schedule`, `sources.open_meteo` and `__main__`. Both suites install the dev extra, so
both stayed green — and `pip install .` on the Pi would have produced an API that starts
normally and a scheduler that dies on its first import, which is the half of the system
that cannot be noticed by loading the page.

The test reads the imports rather than listing them, so a new provider client or a new
runtime library is caught the moment it is imported rather than the first time someone
deploys.
"""

from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "src" / "nazarenow"
PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def _imported_top_level_modules() -> set[str]:
    """Every top-level module name imported anywhere under the runtime package."""
    modules: set[str] = set()
    for source in PACKAGE.rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            # A relative import has no module to resolve against the environment.
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules.add(node.module.split(".")[0])
    return modules


def _declared_runtime_distributions() -> set[str]:
    """The distribution names in `[project] dependencies`, without their version pins."""
    metadata = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    declared = set()
    for requirement in metadata["project"]["dependencies"]:
        name = requirement.split(";")[0].strip()
        for separator in ("[", ">", "<", "=", "!", "~", " "):
            name = name.split(separator)[0]
        declared.add(name.strip().lower())
    return declared


def test_every_third_party_module_the_runtime_imports_is_a_runtime_dependency() -> None:
    third_party = {
        module
        for module in _imported_top_level_modules()
        if module not in sys.stdlib_module_names and module != "nazarenow"
    }
    declared = _declared_runtime_distributions()

    # Module name and distribution name are assumed to match, which holds for every
    # dependency this project has. The day one does not — the import and the thing you pip
    # install spelled differently — this is where the translation goes, and the failure
    # names the module clearly enough to say so.
    undeclared = {module for module in third_party if module.lower() not in declared}

    assert not undeclared, (
        f"imported by the runtime but not declared as a runtime dependency: "
        f"{sorted(undeclared)}. A dev-extra declaration is not enough — the deployed host "
        f"installs the project without it."
    )

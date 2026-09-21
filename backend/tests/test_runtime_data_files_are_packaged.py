"""Every data file the runtime reads from beside its own module must ship in the wheel.

This guards a defect that reached the repository and was found on the host, not by the suite:
`pip install ./backend` produced a package containing **none** of the four calibrated JSONs.
setuptools does not carry a data file that sits inside a package unless it is told to, and
nothing told it to, so the wheel held 25 entries and no `amplification.json`.

That is the worst shape a deployment fault can take. The package imports cleanly, the API
starts, and the scheduler dies on its first Pipeline Run — the half of the system that cannot
be noticed by loading the page. `thresholds`, `forecast_error` and `track_record` each accept
an override environment variable, so a host could in principle be pointed at the checkout;
`models/learned.py` resolves `amplification.json` with no override at all, so there is no
host-side workaround and the fix has to be in the packaging.

Both suites run from the source tree, where these files are present by construction, which is
exactly why nothing caught it — the same blind spot, and the same reasoning, as
`test_runtime_dependencies_are_declared.py`.

**What this proves:** the `package-data` declaration covers every non-Python file in the
package, so adding a fifth data file with a different extension fails here rather than on the
Pi. **What it does not prove:** that setuptools honours the declaration. That is setuptools'
own contract, and checking it for real means building a wheel, which needs a network round
trip for build isolation and does not belong in a unit test.
"""

from __future__ import annotations

import tomllib
from fnmatch import fnmatch
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "src" / "nazarenow"
PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def _data_files() -> set[str]:
    """Every file in the package that the import machinery will not carry on its own.

    Paths are relative to the package root and POSIX-spelled, because that is the form
    `package-data` globs are written in.
    """
    return {
        path.relative_to(PACKAGE).as_posix()
        for path in PACKAGE.rglob("*")
        if path.is_file()
        and path.suffix not in {".py", ".pyc", ".pyi"}
        and "__pycache__" not in path.parts
    }


def _declared_globs() -> list[str]:
    """The `package-data` globs declared for the runtime package."""
    metadata = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    package_data = metadata.get("tool", {}).get("setuptools", {}).get("package-data", {})
    return list(package_data.get("nazarenow", []))


def test_the_calibrated_model_files_are_present_to_be_packaged() -> None:
    """The four files the runtime resolves relative to `__file__`, by name.

    Named rather than discovered, so deleting one is a failure here and not a silently
    smaller set for the declaration test below to agree with.
    """
    expected = {
        "amplification.json",
        "forecast_error.json",
        "thresholds.json",
        "track_record.json",
    }
    missing = {name for name in expected if not (PACKAGE / name).is_file()}

    assert not missing, (
        f"the runtime resolves these beside its own modules and they are not in the source "
        f"tree: {sorted(missing)}"
    )


def test_every_runtime_data_file_is_declared_as_package_data() -> None:
    declared = _declared_globs()
    unpackaged = {
        name for name in _data_files() if not any(fnmatch(name, glob) for glob in declared)
    }

    assert not unpackaged, (
        f"in the runtime package but matched by no [tool.setuptools.package-data] glob, so "
        f"absent from the built wheel: {sorted(unpackaged)}. The source tree is not what the "
        f"host installs — declare it, or the first run that reads it fails on the Pi."
    )

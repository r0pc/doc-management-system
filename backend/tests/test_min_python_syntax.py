"""Every app module must parse on the OLDEST Python this package supports.

The development host runs a newer interpreter than the container does
(`requires-python = ">=3.12"`, `Dockerfile` is `python:3.12-slim`, the dev venv
is 3.14). Syntax added after the floor therefore passes every host gate --
pytest, mypy and ruff all ran clean -- and then SyntaxErrors at *import* inside
the image, taking the worker down before it can register a single task.

That is exactly what happened with PEP 758's unparenthesised
``except ValueError, TypeError:``: valid from 3.14, a hard SyntaxError on 3.12,
invisible to a 3.14 host.

``ast.parse(feature_version=...)`` reproduces the older grammar without needing
the older interpreter installed, so the floor is enforced where the code is
written rather than discovered at deploy time.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = BACKEND_ROOT / "app"


def declared_minimum() -> tuple[int, int]:
    """The (major, minor) floor from ``requires-python``; the single source."""
    pyproject = tomllib.loads((BACKEND_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    spec = pyproject["project"]["requires-python"]
    match = re.search(r">=\s*(\d+)\.(\d+)", spec)
    assert match, f"cannot read a floor out of requires-python={spec!r}"
    return int(match.group(1)), int(match.group(2))


APP_MODULES = sorted(APP_ROOT.rglob("*.py"))


def test_app_modules_were_discovered() -> None:
    """Guard the guard: an empty glob would make every check below vacuous."""
    assert len(APP_MODULES) > 20, f"only found {len(APP_MODULES)} modules under {APP_ROOT}"


@pytest.mark.parametrize("module", APP_MODULES, ids=lambda p: str(p.relative_to(APP_ROOT)))
def test_module_parses_at_the_declared_python_floor(module: Path) -> None:
    floor = declared_minimum()
    source = module.read_text(encoding="utf-8")
    try:
        ast.parse(source, filename=str(module), feature_version=floor)
    except SyntaxError as exc:
        pytest.fail(
            f"{module.relative_to(BACKEND_ROOT)}:{exc.lineno} does not parse on "
            f"Python {floor[0]}.{floor[1]}, the floor declared in "
            f"pyproject.toml requires-python -- it would SyntaxError at import "
            f"inside the container: {exc.msg}"
        )


def test_the_floor_matches_the_docker_base_image() -> None:
    """A newer base image than the floor is fine; an OLDER one is a trap.

    The container is the thing that has to run this code, so if the image ever
    drops below requires-python the check above stops modelling reality.
    """
    dockerfile = (BACKEND_ROOT / "Dockerfile").read_text(encoding="utf-8")
    match = re.search(r"^FROM\s+python:(\d+)\.(\d+)", dockerfile, re.MULTILINE)
    assert match, "could not find a python base image in Dockerfile"
    image = (int(match.group(1)), int(match.group(2)))
    assert image >= declared_minimum(), (
        f"Dockerfile runs Python {image[0]}.{image[1]} but requires-python "
        f"declares {declared_minimum()} -- the image cannot run this package"
    )

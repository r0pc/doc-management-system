"""Purity proof for app/domain: no web/ORM framework leakage in source.

Scans the real source files of every app.domain module after stripping
comments and docstrings, asserting forbidden framework substrings never
appear in code. Also AST-checks the import graph.
"""

import ast
import io
import tokenize
from pathlib import Path

import pytest

import app.domain.models as domain_models
import app.domain.policy as domain_policy
import app.domain.taxonomy as domain_taxonomy

DOMAIN_MODULES = (domain_models, domain_taxonomy, domain_policy)

FORBIDDEN_SUBSTRINGS = ("fastapi", "sqlalchemy", "Session", "request")

ALLOWED_IMPORT_ROOTS = frozenset(
    {
        "__future__",
        "app",  # first-party: intra-domain absolute imports (repo convention)
        "collections",
        "collections.abc",
        "dataclasses",
        "datetime",
        "enum",
        "types",
        "typing",
        "uuid",
    }
)


def _code_without_comments_or_docstrings(path: Path) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    docstring_starts: set[tuple[int, int]] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                docstring_starts.add((first.value.lineno, first.value.col_offset))

    kept: list[str] = []
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type in (tokenize.COMMENT, tokenize.NL):
            continue
        if tok.type == tokenize.STRING and tok.start in docstring_starts:
            continue
        kept.append(tok.string)
    return "\n".join(kept)


@pytest.mark.parametrize(
    "module",
    DOMAIN_MODULES,
    ids=[m.__name__ for m in DOMAIN_MODULES],
)
def test_domain_source_has_no_framework_substrings(module: object) -> None:
    code = _code_without_comments_or_docstrings(Path(str(module.__file__)))
    for needle in FORBIDDEN_SUBSTRINGS:
        assert needle not in code, f"{module.__name__}: {needle!r} outside comments/docstrings"


@pytest.mark.parametrize(
    "module",
    DOMAIN_MODULES,
    ids=[m.__name__ for m in DOMAIN_MODULES],
)
def test_domain_import_graph_is_stdlib_only(module: object) -> None:
    tree = ast.parse(Path(str(module.__file__)).read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    unexpected = roots - ALLOWED_IMPORT_ROOTS
    assert roots <= ALLOWED_IMPORT_ROOTS, f"unexpected imports in {module.__name__}: {unexpected}"

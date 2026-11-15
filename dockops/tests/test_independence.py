"""
dockops is the framework-free core of the project: it must never import Django.

The check reads the source instead of importing it, because pytest-django has already
loaded Django in this process.
"""
import ast
from pathlib import Path

import pytest

DOCKOPS_DIR = Path(__file__).resolve().parent.parent
MODULES = sorted(DOCKOPS_DIR.glob("*.py"))


def imported_names(source: str) -> set[str]:
    """Top-level package of every import statement in a module."""
    names = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def test_every_module_is_checked():
    assert {path.name for path in MODULES} >= {"models.py", "rules.py", "live.py", "history.py"}


@pytest.mark.parametrize("path", MODULES, ids=lambda path: path.name)
def test_module_does_not_import_django(path):
    assert "django" not in imported_names(path.read_text(encoding="utf-8"))

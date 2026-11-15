"""Architecture fitness tests for the module boundaries in doc 02 §4 and the master prompt.

* domain/ and optimization/ are pure: no FastAPI, HTTPX, SQLAlchemy, Redis, Pydantic or RailKit.
* RailKit code is reachable only via app.providers.factory (and its own package).
* The domain never depends on outer layers.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"

FORBIDDEN_IN_CORE_LOGIC = (
    "fastapi",
    "starlette",
    "httpx",
    "sqlalchemy",
    "redis",
    "pydantic",
    "pydantic_settings",
    "app.integrations",
    "app.api",
    "app.services",
    "app.repositories",
    "app.database",
    "app.cache",
    "app.providers",
    "app.schemas",
    "app.core.config",
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def _python_files(*parts: str) -> list[Path]:
    return sorted((APP.joinpath(*parts)).rglob("*.py"))


def _violations(path: Path, forbidden: tuple[str, ...]) -> list[str]:
    return sorted(
        name
        for name in _imports(path)
        if any(name == f or name.startswith(f + ".") for f in forbidden)
    )


@pytest.mark.parametrize("package", ["domain", "optimization"])
def test_core_logic_is_framework_and_provider_free(package: str) -> None:
    offenders = {
        str(path.relative_to(APP)): bad
        for path in _python_files(package)
        if (bad := _violations(path, FORBIDDEN_IN_CORE_LOGIC))
    }
    assert offenders == {}


def test_domain_depends_on_nothing_outside_itself() -> None:
    for path in _python_files("domain"):
        app_imports = {n for n in _imports(path) if n.startswith("app.")}
        assert all(n.startswith("app.domain") for n in app_imports), (path, app_imports)


def test_optimization_may_only_depend_on_domain_and_itself() -> None:
    for path in _python_files("optimization"):
        app_imports = {n for n in _imports(path) if n.startswith("app.")}
        assert all(n.startswith(("app.domain", "app.optimization")) for n in app_imports), (
            path,
            app_imports,
        )


def test_railkit_integration_is_isolated() -> None:
    allowed = {APP / "providers" / "factory.py"}
    railkit_dir = APP / "integrations" / "railkit"
    offenders = [
        str(path.relative_to(APP))
        for path in APP.rglob("*.py")
        if path not in allowed
        and railkit_dir not in path.parents
        and _violations(path, ("app.integrations.railkit",))
    ]
    assert offenders == []

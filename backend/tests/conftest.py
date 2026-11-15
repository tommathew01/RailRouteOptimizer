"""Shared test configuration.

Tests are hermetic: process environment variables that map to Settings fields are cleared so a
developer's shell (or the root ``.env``) can never switch tests onto the live provider.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.config import Settings

_PRESERVED = {"TEST_DATABASE_URL", "TEST_REDIS_URL", "RUN_LIVE_RAILKIT_TESTS"}


@pytest.fixture(autouse=True)
def _hermetic_environment(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.node.get_closest_marker("live"):
        return
    for name in Settings.model_fields:
        env_name = name.upper()
        if env_name not in _PRESERVED:
            monkeypatch.delenv(env_name, raising=False)


def make_settings(**overrides: Any) -> Settings:
    """Settings for tests: never reads ``.env``; mock provider; synchronous searches."""
    values: dict[str, Any] = {
        "environment": "test",
        "railway_provider": "mock",
        "search_execution_mode": "sync",
        "mock_latency_ms": 0,
        "log_json": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def settings() -> Settings:
    return make_settings()

"""Docker / local configuration parity (docs/08 D-30).

``make backend`` reads every setting from the root ``.env``. The Compose backend container has no
``.env`` file (``backend/.dockerignore``), so it only sees what ``compose.yaml`` forwards. These
tests fail when a setting is added to ``Settings`` without being forwarded, when Compose repeats a
default (which would silently diverge from ``config.py``), or when admin credentials leak into the
runtime container.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core.config import REPO_ROOT, Settings

COMPOSE = REPO_ROOT / "compose.yaml"
ENV_EXAMPLE = REPO_ROOT / ".env.example"

#: Set explicitly for the container network / proxy topology (must differ from the host values).
CONTAINER_SPECIFIC = {"DATABASE_URL", "REDIS_URL", "TRUSTED_PROXY_HOPS"}
#: Schema-owner credentials: only the one-shot ``migrate`` service may receive them.
NEVER_IN_RUNTIME = {"MIGRATION_DATABASE_URL", "POSTGRES_ADMIN_USER", "POSTGRES_ADMIN_PASSWORD"}


def _service_environment(service: str) -> dict[str, str | None]:
    """``environment:`` mapping of one Compose service (``KEY:`` without a value → ``None``).

    A deliberately small parser for the mapping style compose.yaml uses, so the test needs no
    YAML dependency.
    """
    lines = COMPOSE.read_text(encoding="utf-8").splitlines()
    start = lines.index(f"  {service}:")
    env: dict[str, str | None] = {}
    inside = False
    for line in lines[start + 1 :]:
        if line.strip().startswith("#") or not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= 2:  # next service
            break
        if indent == 4:
            inside = line.strip() == "environment:"
            continue
        if inside and indent == 6:
            key, _, value = line.strip().partition(":")
            env[key] = value.strip() or None
    return env


def _setting_env_names() -> set[str]:
    return {name.upper() for name in Settings.model_fields}


def test_every_setting_reaches_the_backend_container() -> None:
    env = _service_environment("backend")
    expected = _setting_env_names() - NEVER_IN_RUNTIME
    missing = sorted(expected - env.keys())
    assert not missing, f"add to compose.yaml backend.environment: {missing}"


def test_compose_forwards_only_real_settings() -> None:
    env = _service_environment("backend")
    unknown = sorted(env.keys() - _setting_env_names())
    assert not unknown, f"not a Settings field (typo?): {unknown}"


def test_compose_never_repeats_defaults() -> None:
    """Pass-through entries carry no value, so config.py stays the single source of defaults."""
    env = _service_environment("backend")
    with_value = {key for key, value in env.items() if value is not None}
    assert with_value == CONTAINER_SPECIFIC


def test_admin_credentials_stay_out_of_the_runtime_container() -> None:
    assert not NEVER_IN_RUNTIME & _service_environment("backend").keys()
    assert "MIGRATION_DATABASE_URL" in _service_environment("migrate")


def test_env_example_documents_every_setting() -> None:
    documented = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", ENV_EXAMPLE.read_text(), re.M))
    undocumented = sorted(_setting_env_names() - documented - {"APP_NAME"})
    assert not undocumented, f"document in .env.example: {undocumented}"


def test_same_dotenv_gives_same_settings_locally_and_in_docker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Local: Settings reads the .env file. Docker: Compose forwards the listed variables into the
    process environment and the container has no .env. The same .env must give the same Settings
    for search budget, concurrency, train/class limits, cache TTLs, Tatkal, retries and limits."""
    values = {
        "SEARCH_MAX_AVAILABILITY_REQUESTS": "100",
        "RAILKIT_MAX_CONCURRENCY": "8",
        "SEARCH_MAX_TRAINS": "4",
        "SEARCH_DEFAULT_TRAINS": "2",
        "SEARCH_MAX_CLASSES": "2",
        "AVAILABILITY_CACHE_TTL_SECONDS": "60",
        "TRAIN_ROUTE_CACHE_TTL_SECONDS": "3600",
        "TATKAL_OPENING_DAYS_BEFORE": "1",
        "TATKAL_AC_OPENING_TIME": "10:00",
        "TATKAL_NON_AC_OPENING_TIME": "11:00",
        "RAILKIT_SUPPORTED_QUOTAS": "GN,TQ",
        "RAILKIT_MAX_RETRIES": "2",
        "PROVIDER_WINDOW_REQUEST_LIMIT": "550",
        "PROVIDER_MONTHLY_REQUEST_LIMIT": "5500",
        "MOCK_LATENCY_MS": "0",
    }
    dotenv = tmp_path / ".env"
    dotenv.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
    local = Settings(_env_file=dotenv)

    forwarded = _service_environment("backend")
    for key, value in values.items():
        if key in forwarded:  # what Compose resolves from .env into the container
            monkeypatch.setenv(key, value)
    docker = Settings(_env_file=None)

    assert docker == local
    assert docker.search_max_availability_requests == 100
    assert docker.railkit_max_concurrency == 8

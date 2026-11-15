from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.domain.enums import AvailabilityDatePolicy
from tests.conftest import make_settings


def test_defaults_are_safe_demo_mode() -> None:
    settings = make_settings()
    assert settings.is_demo_mode
    assert settings.max_segments == 4
    assert settings.availability_date_policy is AvailabilityDatePolicy.SEGMENT_BOARDING_DATE
    # Free-tier quota defaults: a fresh deployment cannot burn a paid plan by accident.
    assert settings.provider_monthly_request_limit == 50
    assert settings.provider_window_request_limit == 100


def test_csv_lists_are_parsed_and_normalized() -> None:
    settings = make_settings(
        cors_allowed_origins="https://a.example, https://b.example",
        supported_classes="3a, sl,3A",
    )
    assert settings.cors_allowed_origins == ["https://a.example", "https://b.example"]
    assert settings.supported_classes == ["3A", "SL"]


def test_unknown_class_codes_are_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown travel class"):
        make_settings(supported_classes="3A,XX")


def test_max_segments_cannot_exceed_four() -> None:
    with pytest.raises(ValidationError):
        make_settings(max_segments=5)


@pytest.mark.parametrize(
    "raw",
    ["postgresql://u:p@h:5432/d", "postgres://u:p@h:5432/d", "postgresql+psycopg://u:p@h:5432/d"],
)
def test_database_url_uses_async_psycopg_driver(raw: str) -> None:
    settings = make_settings(database_url=raw)
    assert settings.database_url is not None
    assert settings.database_url.get_secret_value() == "postgresql+psycopg://u:p@h:5432/d"


def test_railkit_provider_requires_api_key() -> None:
    with pytest.raises(ValidationError, match="RAILKIT_API_KEY"):
        make_settings(railway_provider="railkit")


def test_blank_api_key_counts_as_missing() -> None:
    with pytest.raises(ValidationError, match="RAILKIT_API_KEY"):
        make_settings(railway_provider="railkit", railkit_api_key="   ")


def test_production_refuses_mock_data_and_missing_infrastructure() -> None:
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        make_settings(
            environment="production", railway_provider="railkit", railkit_api_key="k" * 20
        )
    with pytest.raises(ValidationError, match="mock"):
        make_settings(
            environment="production",
            database_url="postgresql://u:p@h/d",
            redis_url="redis://h:6379/0",
        )


def test_base_url_must_be_https() -> None:
    with pytest.raises(ValidationError, match="https"):
        make_settings(railkit_base_url="http://api.example.com")


def test_secret_values_never_appear_in_repr() -> None:
    settings = make_settings(railway_provider="railkit", railkit_api_key="super-secret-key-123")
    assert "super-secret-key-123" not in repr(settings)
    assert "super-secret-key-123" in settings.secret_values


def test_settings_type_is_exported() -> None:
    assert isinstance(make_settings(), Settings)


def test_migration_url_prefers_explicit_value() -> None:
    settings = make_settings(
        database_url="postgresql://app:apppw@db:5432/rr",
        migration_database_url="postgresql://owner:ownerpw@db:5432/rr",
        postgres_admin_user="admin",
        postgres_admin_password="adminpw",
    )
    assert (
        settings.effective_migration_database_url == "postgresql+psycopg://owner:ownerpw@db:5432/rr"
    )


def test_migration_url_derived_from_admin_role() -> None:
    settings = make_settings(
        database_url="postgresql://app:apppw@db:5432/rr",
        postgres_admin_user="admin",
        postgres_admin_password="p@ss:w/rd",
    )
    assert (
        settings.effective_migration_database_url
        == "postgresql+psycopg://admin:p%40ss%3Aw%2Frd@db:5432/rr"
    )


def test_migration_url_falls_back_to_runtime_url() -> None:
    settings = make_settings(database_url="postgresql://app:apppw@db:5432/rr")
    assert settings.effective_migration_database_url == "postgresql+psycopg://app:apppw@db:5432/rr"

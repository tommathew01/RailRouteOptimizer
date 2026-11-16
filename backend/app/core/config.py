"""Typed application settings.

Every value is read from environment variables (or the untracked repository-root ``.env``).
Secrets are wrapped in ``SecretStr`` so they never appear in ``repr()`` or logs.

Cache TTLs are deliberately short and configurable: RailKit's caching / storage terms have not
been confirmed (see docs/09_RAILKIT_CONTRACT_VERIFICATION.md, Q14).
"""

from __future__ import annotations

from datetime import time
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Self
from urllib.parse import quote, urlsplit, urlunsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.domain.enums import KNOWN_CLASS_CODES, QUOTA_ORDER, AvailabilityDatePolicy, Quota
from app.domain.maintenance import MaintenanceWindow
from app.domain.quota_eligibility import OpeningRule

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent

#: Domain hard limit (doc 01 / README binding decisions). Settings may lower it, never raise it.
ABSOLUTE_MAX_SEGMENTS = 4

DEFAULT_SUPPORTED_CLASSES = ("1A", "2A", "3A", "3E", "SL", "CC", "EC", "2S")


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class ProviderName(StrEnum):
    MOCK = "mock"
    RAILKIT = "railkit"


class ExecutionMode(StrEnum):
    ASYNC = "async"
    SYNC = "sync"


def _split_csv(value: object) -> object:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application -------------------------------------------------------------------------
    app_name: str = "RailRoute Optimizer"
    environment: Environment = Environment.DEVELOPMENT
    log_level: str = "INFO"
    log_json: bool = True
    cors_allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )
    max_request_body_bytes: int = Field(default=65_536, ge=1_024, le=1_048_576)
    trusted_proxy_hops: int = Field(default=0, ge=0, le=5)

    # --- Railway provider --------------------------------------------------------------------
    railway_provider: ProviderName = ProviderName.MOCK
    railkit_api_key: SecretStr | None = None
    railkit_base_url: str = "https://api.railkit.in"
    railkit_connect_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    railkit_read_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    railkit_write_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    railkit_pool_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    railkit_max_retries: int = Field(default=1, ge=0, le=3)
    railkit_retry_backoff_seconds: float = Field(default=0.5, ge=0, le=10)
    railkit_max_concurrency: int = Field(default=4, ge=1, le=32)
    railkit_fare_currency: str = Field(default="INR", min_length=3, max_length=3)
    #: Quotas RailKit's seat-availability endpoint accepts. TQ verified live 2026-11-15 (docs/09
    #: Q16). Remove TQ here to disable Tatkal without a code change.
    railkit_supported_quotas: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [Quota.GENERAL.value, Quota.TATKAL.value]
    )

    # --- Reservation quota booking windows (docs/08 D-21) ------------------------------------
    #: Tatkal opens N calendar days before the train's ORIGIN date, at an IST wall-clock time.
    tatkal_opening_days_before: int = Field(default=1, ge=0, le=7)
    tatkal_ac_opening_time: time = time(10, 0)
    tatkal_non_ac_opening_time: time = time(11, 0)

    # --- Daily railway maintenance window (docs/08 D-31) -------------------------------------
    #: IRCTC allows no train search / availability check 23:45-00:20 IST; nor does RailRoute.
    railway_maintenance_enabled: bool = True
    railway_maintenance_start: time = time(23, 45)
    railway_maintenance_end: time = time(0, 20)

    # --- Provider quota guard (set to your RailKit plan; defaults = Free tier) ----------------
    provider_window_request_limit: int = Field(default=100, ge=1)
    provider_window_seconds: int = Field(default=600, ge=1)
    provider_monthly_request_limit: int = Field(default=50, ge=1)
    provider_rate_limit_backoff_seconds: int = Field(default=300, ge=1)

    # --- Search policy -----------------------------------------------------------------------
    supported_classes: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: list(DEFAULT_SUPPORTED_CLASSES)
    )
    max_segments: int = Field(default=ABSOLUTE_MAX_SEGMENTS, ge=1, le=ABSOLUTE_MAX_SEGMENTS)
    #: Trains a user may select for one search (the train list pre-selects none).
    search_max_trains: int = Field(default=5, ge=1, le=20)
    #: Classes per search. Every train x class x quota is a separate combination sharing the
    #: budget; 5 trains x 3 classes x 2 quotas = 30 = the default budget, so every direct ticket
    #: can still be checked (docs/08 D-29).
    search_max_classes: int = Field(default=3, ge=1, le=len(KNOWN_CLASS_CODES))
    #: Provider availability *attempts* per search, retries included (D-28).
    search_max_availability_requests: int = Field(default=30, ge=1, le=500)
    search_deadline_seconds: float = Field(default=90.0, gt=0, le=600)
    planner_max_intermediate_stops: int = Field(default=30, ge=0, le=200)
    max_recommendations: int = Field(default=20, ge=1, le=100)
    max_paths_per_combination: int = Field(default=50, ge=1, le=1_000)
    availability_date_policy: AvailabilityDatePolicy = AvailabilityDatePolicy.SEGMENT_BOARDING_DATE
    max_advance_booking_days: int = Field(default=60, ge=1, le=365)
    search_execution_mode: ExecutionMode = ExecutionMode.ASYNC
    max_concurrent_searches: int = Field(default=4, ge=1, le=64)

    # --- Caching (TTL values pending RailKit agreement verification) -------------------------
    availability_cache_ttl_seconds: int = Field(default=120, ge=0, le=3_600)
    train_search_cache_ttl_seconds: int = Field(default=1_800, ge=0, le=86_400)
    train_route_cache_ttl_seconds: int = Field(default=86_400, ge=0, le=604_800)
    station_search_cache_ttl_seconds: int = Field(default=604_800, ge=0, le=2_592_000)
    single_flight_lock_ttl_seconds: int = Field(default=60, ge=1, le=600)
    stale_after_seconds: int = Field(default=300, ge=10)
    station_search_min_query_length: int = Field(default=3, ge=2, le=10)

    # --- Infrastructure ----------------------------------------------------------------------
    database_url: SecretStr | None = None
    migration_database_url: SecretStr | None = None
    database_pool_size: int = Field(default=5, ge=1, le=50)
    database_max_overflow: int = Field(default=5, ge=0, le=50)
    database_echo: bool = False
    redis_url: SecretStr | None = None
    #: Optional: lets local Compose setups derive MIGRATION_DATABASE_URL from the admin role.
    postgres_admin_user: str | None = None
    postgres_admin_password: SecretStr | None = None

    # --- Public API rate limits (per client IP, fixed window) --------------------------------
    api_rate_limit_window_seconds: int = Field(default=600, ge=1)
    api_rate_limit_search_requests: int = Field(default=20, ge=1)
    api_rate_limit_lookup_requests: int = Field(default=300, ge=1)

    # --- Observability -----------------------------------------------------------------------
    metrics_enabled: bool = True
    metrics_token: SecretStr | None = None

    # --- Mock provider -----------------------------------------------------------------------
    mock_latency_ms: int = Field(default=120, ge=0, le=10_000)

    @field_validator(
        "cors_allowed_origins", "supported_classes", "railkit_supported_quotas", mode="before"
    )
    @classmethod
    def _parse_csv(cls, value: object) -> object:
        return _split_csv(value)

    @field_validator("railkit_supported_quotas")
    @classmethod
    def _validate_quotas(cls, value: list[str]) -> list[str]:
        normalized = {code.strip().upper() for code in value}
        known = {q.value for q in Quota}
        unknown = sorted(normalized - known)
        if unknown:
            raise ValueError(f"unknown quota codes: {', '.join(unknown)}")
        if Quota.GENERAL.value not in normalized:
            raise ValueError("the General quota (GN) must be supported")
        return [q.value for q in QUOTA_ORDER if q.value in normalized]

    @field_validator(
        "tatkal_ac_opening_time",
        "tatkal_non_ac_opening_time",
        "railway_maintenance_start",
        "railway_maintenance_end",
    )
    @classmethod
    def _naive_ist_time(cls, value: time) -> time:
        if value.tzinfo is not None:
            raise ValueError("opening times are IST wall-clock times; omit the UTC offset")
        return value

    @field_validator("supported_classes")
    @classmethod
    def _validate_classes(cls, value: list[str]) -> list[str]:
        normalized = [code.strip().upper() for code in value]
        unknown = sorted(set(normalized) - KNOWN_CLASS_CODES)
        if unknown:
            raise ValueError(f"unknown travel class codes: {', '.join(unknown)}")
        if not normalized:
            raise ValueError("at least one supported class is required")
        return list(dict.fromkeys(normalized))

    @field_validator("database_url", "migration_database_url", mode="before")
    @classmethod
    def _normalize_database_url(cls, value: object) -> object:
        """Accept ``postgresql://`` / ``postgres://`` and use the async psycopg driver."""
        raw = value.get_secret_value() if isinstance(value, SecretStr) else value
        if not isinstance(raw, str) or not raw.strip():
            return None
        for prefix in ("postgresql://", "postgres://"):
            if raw.startswith(prefix):
                return "postgresql+psycopg://" + raw[len(prefix) :]
        return raw

    @field_validator(
        "railkit_api_key", "redis_url", "metrics_token", "postgres_admin_password", mode="before"
    )
    @classmethod
    def _blank_secret_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("railkit_base_url")
    @classmethod
    def _validate_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith("https://") and not value.startswith("http://localhost"):
            raise ValueError("RAILKIT_BASE_URL must use https")
        return value

    @model_validator(mode="after")
    def _cross_field_rules(self) -> Self:
        if self.railway_maintenance_start == self.railway_maintenance_end:
            raise ValueError("RAILWAY_MAINTENANCE_START and RAILWAY_MAINTENANCE_END must differ")
        if self.railway_provider is ProviderName.RAILKIT and self.railkit_api_key is None:
            raise ValueError("RAILKIT_API_KEY is required when RAILWAY_PROVIDER=railkit")
        if self.environment is Environment.PRODUCTION:
            missing = [
                name
                for name, val in (
                    ("DATABASE_URL", self.database_url),
                    ("REDIS_URL", self.redis_url),
                )
                if val is None
            ]
            if missing:
                raise ValueError(f"production requires: {', '.join(missing)}")
            if self.railway_provider is not ProviderName.RAILKIT:
                raise ValueError("production must not serve mock (demo) data")
        return self

    # --- Convenience -------------------------------------------------------------------------
    @property
    def is_demo_mode(self) -> bool:
        return self.railway_provider is ProviderName.MOCK

    @property
    def maintenance_window(self) -> MaintenanceWindow | None:
        if not self.railway_maintenance_enabled:
            return None
        return MaintenanceWindow(self.railway_maintenance_start, self.railway_maintenance_end)

    @property
    def max_classes_per_search(self) -> int:
        """The class-selection limit actually enforced (never more than the supported classes)."""
        return min(self.search_max_classes, len(self.supported_classes))

    @property
    def availability_date_policy_verified(self) -> bool:
        """RailKit expects the boarding date at the segment's from-station.

        Verified live on 2026-11-14 (docs/09 Q1): a stop reached after midnight answered for its
        boarding date and rejected the train's start date with HTTP 400.
        """
        return self.availability_date_policy is AvailabilityDatePolicy.SEGMENT_BOARDING_DATE

    def opening_rule(self, quota: Quota) -> OpeningRule | None:
        """Booking-window rule of ``quota``; ``None`` when no window applies (General)."""
        if quota is Quota.TATKAL:
            return OpeningRule(
                self.tatkal_opening_days_before,
                self.tatkal_ac_opening_time,
                self.tatkal_non_ac_opening_time,
            )
        return None

    @property
    def secret_values(self) -> list[str]:
        """Plain secret strings, registered with the log redactor at startup."""
        secrets = [self.railkit_api_key, self.database_url, self.migration_database_url]
        secrets += [self.redis_url, self.metrics_token, self.postgres_admin_password]
        values = [s.get_secret_value() for s in secrets if s is not None]
        return [v for v in values if len(v) >= 6]

    @property
    def effective_migration_database_url(self) -> str | None:
        """Schema migrations run as the owning (admin) role; the app runs least-privileged.

        Precedence: MIGRATION_DATABASE_URL, then DATABASE_URL with POSTGRES_ADMIN_USER /
        POSTGRES_ADMIN_PASSWORD substituted, then DATABASE_URL itself.
        """
        if self.migration_database_url is not None:
            return self.migration_database_url.get_secret_value()
        if self.database_url is None:
            return None
        url = self.database_url.get_secret_value()
        if self.postgres_admin_user and self.postgres_admin_password:
            parts = urlsplit(url)
            host = parts.hostname or "localhost"
            port = f":{parts.port}" if parts.port else ""
            user = quote(self.postgres_admin_user, safe="")
            password = quote(self.postgres_admin_password.get_secret_value(), safe="")
            netloc = f"{user}:{password}@{host}{port}"
            return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
        return url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

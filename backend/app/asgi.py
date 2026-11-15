"""Production entrypoint: ``uvicorn app.asgi:app``. Reads settings and configures logging."""

from __future__ import annotations

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.main import create_app

settings = get_settings()
configure_logging(
    level=settings.log_level, json_output=settings.log_json, secrets=settings.secret_values
)
app = create_app(settings)

"""Structured JSON logging with correlation IDs and secret redaction."""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, ClassVar

from app.core.context import request_id_var, search_id_var
from app.core.redaction import REDACTED, is_sensitive_key, redact_text, secret_fragments

_STANDARD_ATTRS = frozenset(
    vars(logging.LogRecord("x", logging.INFO, "x", 0, "x", None, None)).keys()
) | {"message", "asctime", "taskName", "color_message"}


class RedactingFilter(logging.Filter):
    """Removes registered secret values from messages and structured extras."""

    fragments: ClassVar[list[str]] = []

    @classmethod
    def register_secrets(cls, values: Iterable[str]) -> None:
        cls.fragments = secret_fragments([*cls.fragments, *values])

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        record.msg = redact_text(message, self.fragments)
        record.args = None
        for key, value in list(record.__dict__.items()):
            if key in _STANDARD_ATTRS:
                continue
            record.__dict__[key] = self._redact_value(key, value)
        return True

    def _redact_value(self, key: str, value: Any) -> Any:
        if is_sensitive_key(key):
            return REDACTED
        if isinstance(value, str):
            return redact_text(value, self.fragments)
        if isinstance(value, dict):
            return {k: self._redact_value(str(k), v) for k, v in value.items()}
        if isinstance(value, list | tuple):
            return [self._redact_value(key, v) for v in value]
        return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if (request_id := request_id_var.get()) is not None:
            entry["request_id"] = request_id
        if (search_id := search_id_var.get()) is not None:
            entry["search_id"] = search_id
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                entry[key] = value
        if record.exc_info:
            entry["exc_info"] = redact_text(
                self.formatException(record.exc_info), RedactingFilter.fragments
            )
        return json.dumps(entry, default=str, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = {
            k: v
            for k, v in record.__dict__.items()
            if k not in _STANDARD_ATTRS and not k.startswith("_")
        }
        ids = " ".join(
            f"{name}={value}"
            for name, value in (("req", request_id_var.get()), ("search", search_id_var.get()))
            if value
        )
        suffix = " ".join(filter(None, [ids, json.dumps(extras, default=str) if extras else ""]))
        return f"{base} {suffix}".rstrip()


def configure_logging(*, level: str, json_output: bool, secrets: Iterable[str] = ()) -> None:
    RedactingFilter.register_secrets(secrets)
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RedactingFilter())
    if json_output:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(ConsoleFormatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    for uvicorn_logger in ("uvicorn", "uvicorn.error"):
        logging.getLogger(uvicorn_logger).handlers[:] = []
        logging.getLogger(uvicorn_logger).propagate = True

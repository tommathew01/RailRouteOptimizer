from __future__ import annotations

import json
import logging

from app.core.context import request_id_var
from app.core.logging import JsonFormatter, RedactingFilter
from app.core.redaction import REDACTED, redact_text, sanitize_payload, secret_fragments


def test_url_passwords_are_extracted_as_fragments() -> None:
    fragments = secret_fragments(["postgresql+psycopg://app:hunter2pass@db:5432/x"])
    assert "hunter2pass" in fragments
    text = "connecting with password hunter2pass"
    assert "hunter2pass" not in redact_text(text, fragments)


def test_sanitize_payload_drops_sensitive_keys_and_bounds_size() -> None:
    payload = {
        "data": {"x-api-key": "abc", "Authorization": "Bearer t", "items": list(range(500))},
        "note": "key=SECRETVALUE123",
    }
    clean = sanitize_payload(payload, fragments=["SECRETVALUE123"], max_items=10)
    assert clean["data"]["x-api-key"] == REDACTED
    assert clean["data"]["Authorization"] == REDACTED
    assert len(clean["data"]["items"]) == 11  # 10 kept + truncation marker
    assert "SECRETVALUE123" not in clean["note"]


def _record(msg: str, **extra: object) -> logging.LogRecord:
    record = logging.LogRecord("test", logging.INFO, __file__, 1, msg, None, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_redacting_filter_scrubs_message_and_extras() -> None:
    RedactingFilter.register_secrets(["rk_live_ABCDEF123456"])
    record = _record(
        "calling provider with rk_live_ABCDEF123456",
        headers={"x-api-key": "rk_live_ABCDEF123456", "accept": "application/json"},
        detail="token rk_live_ABCDEF123456",
    )
    assert RedactingFilter().filter(record)
    assert "rk_live_ABCDEF123456" not in record.getMessage()
    assert record.headers["x-api-key"] == REDACTED  # type: ignore[attr-defined]
    assert record.headers["accept"] == "application/json"  # type: ignore[attr-defined]
    assert "rk_live_ABCDEF123456" not in record.detail  # type: ignore[attr-defined]


def test_json_formatter_includes_correlation_ids_and_extras() -> None:
    token = request_id_var.set("req-12345678")
    try:
        line = JsonFormatter().format(_record("hello", provider="RAILKIT", latency_ms=12.5))
    finally:
        request_id_var.reset(token)
    entry = json.loads(line)
    assert entry["msg"] == "hello"
    assert entry["request_id"] == "req-12345678"
    assert entry["provider"] == "RAILKIT"
    assert entry["latency_ms"] == 12.5

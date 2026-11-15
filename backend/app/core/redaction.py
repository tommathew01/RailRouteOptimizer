"""Secret redaction and provider-payload sanitization.

Used by the log formatter and before any provider payload is persisted (doc 06 §4, §6).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import urlsplit

REDACTED = "***REDACTED***"

SENSITIVE_KEY_PATTERN = re.compile(
    r"(api[-_]?key|authorization|password|passwd|secret|token|cookie|signature|nonce)",
    re.IGNORECASE,
)


def is_sensitive_key(key: object) -> bool:
    return isinstance(key, str) and bool(SENSITIVE_KEY_PATTERN.search(key))


def secret_fragments(values: Iterable[str]) -> list[str]:
    """Return every string that must never be logged, including passwords embedded in URLs."""
    fragments: set[str] = set()
    for value in values:
        if not value:
            continue
        fragments.add(value)
        if "://" in value:
            try:
                password = urlsplit(value).password
            except ValueError:
                password = None
            if password and len(password) >= 4:
                fragments.add(password)
    # Longest first so a URL is replaced before its embedded password.
    return sorted(fragments, key=len, reverse=True)


def redact_text(text: str, fragments: Iterable[str]) -> str:
    for fragment in fragments:
        if fragment and fragment in text:
            text = text.replace(fragment, REDACTED)
    return text


def sanitize_payload(
    payload: Any,
    *,
    fragments: Iterable[str] = (),
    max_depth: int = 8,
    max_items: int = 200,
    max_string_length: int = 2_000,
) -> Any:
    """Return a JSON-safe copy with sensitive keys removed and sizes bounded."""
    frags = list(fragments)

    def _walk(value: Any, depth: int) -> Any:
        if depth > max_depth:
            return "<truncated: depth>"
        if isinstance(value, Mapping):
            out: dict[str, Any] = {}
            for index, (key, item) in enumerate(value.items()):
                if index >= max_items:
                    out["<truncated>"] = f"{len(value) - max_items} more keys"
                    break
                skey = str(key)
                out[skey] = REDACTED if is_sensitive_key(skey) else _walk(item, depth + 1)
            return out
        if isinstance(value, list | tuple):
            items = [_walk(item, depth + 1) for item in list(value)[:max_items]]
            if len(value) > max_items:
                items.append(f"<truncated: {len(value) - max_items} more items>")
            return items
        if isinstance(value, str):
            value = redact_text(value, frags)
            if len(value) > max_string_length:
                return value[:max_string_length] + "<truncated>"
            return value
        if value is None or isinstance(value, bool | int | float):
            return value
        return redact_text(str(value), frags)[:max_string_length]

    return _walk(payload, 0)

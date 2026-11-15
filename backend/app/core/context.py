"""Per-request / per-search correlation identifiers carried through async call chains."""

from __future__ import annotations

from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
search_id_var: ContextVar[str | None] = ContextVar("search_id", default=None)

"""Helpers for RailKit adapter tests: fixtures and an httpx mock transport router."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "railkit"


def load_fixture(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return data


def availability_payload(**entry_overrides: Any) -> dict[str, Any]:
    """The documented seat-availability sample with its single entry modified."""
    payload = copy.deepcopy(load_fixture("seat_availability_docs.json"))
    entry = payload["data"]["availability"][0]
    for key, value in entry_overrides.items():
        if value is ...:
            entry.pop(key, None)
        else:
            entry[key] = value
    return payload


Handler = Callable[[httpx.Request], httpx.Response]


class Router:
    """Records requests and answers them from a queue or a callable."""

    def __init__(self, *responses: httpx.Response | Handler | Exception) -> None:
        self.queue = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self.queue:
            raise AssertionError(f"unexpected request {request.url}")
        item = self.queue.pop(0) if len(self.queue) > 1 else self.queue[0]
        if isinstance(item, Exception):
            raise item
        if callable(item) and not isinstance(item, httpx.Response):
            return item(request)
        return item

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


def json_response(status: int, body: Any, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, json=body, headers=headers)

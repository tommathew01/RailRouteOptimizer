"""Version 1 public API router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import availability, health, journeys, meta, ops, stations, trains

api_router = APIRouter(prefix="/api/v1")
for module in (health, meta, stations, trains, availability, journeys, ops):
    api_router.include_router(module.router)

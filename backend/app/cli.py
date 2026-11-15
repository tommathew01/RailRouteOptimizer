"""Operator commands. Usage: ``python -m app.cli purge --dry-run``.

Retention policy (doc 06 §6), defaults overridable per run:

* raw provider payloads are stripped from observations after ``--raw-payload-days`` (14);
* journey searches older than ``--search-days`` (90) are deleted with their segment runs and
  recommendations (FK cascade);
* availability observations older than ``--search-days`` that no remaining recommendation
  references are deleted;
* provider usage rows older than ``--usage-days`` (400) are deleted (kept longer for billing).

Runs with the least-privileged runtime role (DML only).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, delete, exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.clock import SystemClock
from app.core.config import Settings
from app.database.models import (
    AvailabilityObservationRow,
    JourneySearchRow,
    ProviderUsageRow,
    RecommendationSegmentRow,
)
from app.database.session import create_engine
from app.domain.enums import SearchStatus


def _rows(result: object) -> int:
    return int(getattr(result, "rowcount", 0) or 0)


@dataclass(frozen=True, slots=True)
class PurgeResult:
    payloads_stripped: int
    searches_deleted: int
    observations_deleted: int
    usage_rows_deleted: int


async def purge(
    engine: AsyncEngine,
    *,
    now: datetime,
    raw_payload_days: int,
    search_days: int,
    usage_days: int,
    dry_run: bool,
) -> PurgeResult:
    if min(raw_payload_days, search_days, usage_days) < 1:
        raise ValueError("retention periods must be at least one day")
    payload_cutoff = now - timedelta(days=raw_payload_days)
    search_cutoff = now - timedelta(days=search_days)
    usage_cutoff = now - timedelta(days=usage_days)

    obs = AvailabilityObservationRow
    stale_payload = (obs.observed_at < payload_cutoff) & obs.raw_payload.is_not(None)
    # Unfinished searches are never deleted: they belong to a running process.
    old_search = (JourneySearchRow.created_at < search_cutoff) & JourneySearchRow.status.in_(
        [SearchStatus.COMPLETED.value, SearchStatus.FAILED.value]
    )
    unreferenced_old_obs = (obs.observed_at < search_cutoff) & ~exists().where(
        RecommendationSegmentRow.availability_observation_id == obs.id
    )
    old_usage = ProviderUsageRow.created_at < usage_cutoff

    async with engine.begin() as conn:

        async def count(table: type[Any], condition: ColumnElement[bool]) -> int:
            result = await conn.scalar(select(func.count()).select_from(table).where(condition))
            return int(result or 0)

        if dry_run:
            return PurgeResult(
                payloads_stripped=await count(obs, stale_payload),
                searches_deleted=await count(JourneySearchRow, old_search),
                # Approximate: observations still referenced by searches about to be deleted
                # are not counted, so a real run may delete more.
                observations_deleted=await count(obs, unreferenced_old_obs),
                usage_rows_deleted=await count(ProviderUsageRow, old_usage),
            )
        stripped = await conn.execute(update(obs).where(stale_payload).values(raw_payload=None))
        searches = await conn.execute(delete(JourneySearchRow).where(old_search))
        observations = await conn.execute(delete(obs).where(unreferenced_old_obs))
        usage = await conn.execute(delete(ProviderUsageRow).where(old_usage))
        return PurgeResult(
            payloads_stripped=_rows(stripped),
            searches_deleted=_rows(searches),
            observations_deleted=_rows(observations),
            usage_rows_deleted=_rows(usage),
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    purge_cmd = commands.add_parser("purge", help="apply the data-retention policy")
    purge_cmd.add_argument("--raw-payload-days", type=int, default=14)
    purge_cmd.add_argument("--search-days", type=int, default=90)
    purge_cmd.add_argument("--usage-days", type=int, default=400)
    purge_cmd.add_argument("--dry-run", action="store_true", help="only count affected rows")
    return parser


async def _main(argv: list[str]) -> int:
    args = _parser().parse_args(argv)
    settings = Settings()
    if settings.database_url is None:
        sys.stderr.write("DATABASE_URL is not set.\n")
        return 2
    engine = create_engine(settings.database_url.get_secret_value(), pool_size=1, max_overflow=0)
    try:
        result = await purge(
            engine,
            now=SystemClock().now(),
            raw_payload_days=args.raw_payload_days,
            search_days=args.search_days,
            usage_days=args.usage_days,
            dry_run=args.dry_run,
        )
    finally:
        await engine.dispose()
    mode = "dry run" if args.dry_run else "purged"
    sys.stdout.write(f"{mode}: {asdict(result)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(sys.argv[1:])))

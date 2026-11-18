"""Journey search orchestration (doc 02 §6-7).

submit → persist QUEUED → executor runs:
  train discovery → route retrieval + validation → train x class x quota combinations (quotas whose
  booking window is not open are recorded, never queried) → adaptive planner waves (bounded
  concurrency, budget, deadline) → graph → paths → ranking → completeness → persisted snapshot +
  normalized recommendation rows.

Every quota is a separate search space: a combination, its graph and its paths carry one quota.

Partial results are published after every wave; provider failures never erase successful
observations, and failed or unqueried segments are never treated as unavailable.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
import time
import uuid
from datetime import date, datetime, timedelta

from app.cache import keys
from app.cache.store import KeyValueStore, MemoryStore, StoreError
from app.core import metrics
from app.core.clock import Clock
from app.core.config import Settings
from app.core.context import search_id_var
from app.core.errors import (
    InvalidRequestError,
    SemanticValidationError,
    ServiceUnavailableError,
    require,
)
from app.domain.enums import (
    QUOTA_ORDER,
    AvailabilityDatePolicy,
    AvailabilityStatus,
    IncompleteReason,
    Quota,
    SearchStatus,
    SegmentQueryOutcome,
)
from app.domain.models import SegmentKey, TrainSummary
from app.domain.route import (
    provider_query_date,
    train_start_date,
    validate_journey,
)
from app.domain.time import today_ist
from app.optimization.graph import GraphKey, build_graph
from app.optimization.paths import find_paths
from app.optimization.planner import ComboSpec, PlannedQuery, QueryPlanner
from app.optimization.policy import MAX_SEGMENTS, SearchFilters
from app.optimization.ranking import RankedPath, rank_paths
from app.providers.errors import ProviderError, ProviderErrorCategory
from app.repositories.base import Persistence, PersistenceError
from app.repositories.records import SearchRecord
from app.schemas.journeys import JourneySearchResponse, RecommendationOut, SearchError
from app.services import results
from app.services.availability import (
    AvailabilityService,
    SegmentCheckResult,
    SegmentRequest,
    run_record,
)
from app.services.executor import SearchExecutor
from app.services.quota import QuotaRefusal, SearchBudget
from app.services.quota_eligibility import QuotaEligibilityService
from app.services.search_state import (
    ComboContext,
    JourneyRequest,
    SearchContext,
    TrainContext,
)
from app.services.trains import TrainService

logger = logging.getLogger(__name__)

#: A QUEUED/RUNNING search with no progress for (deadline + this grace) is considered abandoned
#: (its process crashed or was killed) and is reported as FAILED/INTERRUPTED.
STALE_SEARCH_GRACE_SECONDS = 300

FATAL_DISCOVERY_CODES = {
    ProviderErrorCategory.AUTH: "PROVIDER_UNAVAILABLE",
    ProviderErrorCategory.RATE_LIMITED: "PROVIDER_RATE_LIMITED",
    ProviderErrorCategory.QUOTA_EXHAUSTED: "PROVIDER_QUOTA_EXHAUSTED",
    ProviderErrorCategory.TIMEOUT: "PROVIDER_TIMEOUT",
}


class JourneySearchService:
    #: Partial results are republished at most this often (plus after the first wave and at the
    #: end). Rebuilding graphs, ranking and the snapshot on every wave costs ~30 ms of event-loop
    #: time per wave in a 500-request search.
    progress_interval_seconds = 1.0

    def __init__(
        self,
        *,
        settings: Settings,
        clock: Clock,
        trains: TrainService,
        availability: AvailabilityService,
        eligibility: QuotaEligibilityService,
        persistence: Persistence,
        executor: SearchExecutor,
        provider_name: str,
        data_mode: str,
        store: KeyValueStore | None = None,
    ) -> None:
        self._settings = settings
        #: Shared (Redis) store for stop requests, so any replica can stop any search.
        self._store: KeyValueStore = store or MemoryStore()
        #: Searches executing in this process, for an immediate in-process stop.
        self._running: dict[uuid.UUID, SearchContext] = {}
        self._clock = clock
        self._trains = trains
        self._availability = availability
        self._eligibility = eligibility
        self._persistence = persistence
        self._executor = executor
        self._provider_name = provider_name
        self._data_mode = data_mode
        self._wave_size = settings.railkit_max_concurrency

    # --- Public API -----------------------------------------------------------------------------
    def prepare(
        self,
        *,
        source: str,
        destination: str,
        journey_date: date,
        classes: list[str],
        allow_rac: bool,
        allow_waitlist: bool,
        max_segments: int,
        train_numbers: list[str] | None,
        client_quota: str | None,
        quotas: list[str] | None = None,
    ) -> JourneyRequest:
        """Apply server policy: date window, supported classes, segment clamp, quota order.

        ``quotas`` defaults to General. The deprecated single ``client_quota`` field is ignored
        (it predates quota selection), with a note when it asked for something not searched.
        """
        validate_trip(self._settings, self._clock, source, destination, journey_date, classes)
        notes: list[str] = []
        limit = min(self._settings.max_segments, MAX_SEGMENTS)
        if max_segments > limit:
            notes.append(f"max_segments {max_segments} was reduced to the server limit of {limit}.")
        selected = normalize_quotas(quotas)
        supported = [q for q in selected if self._eligibility.is_supported(q)]
        if not supported:  # nothing could be queried: refuse before spending provider requests
            raise SemanticValidationError(
                "The selected quota is not supported by the railway data provider: "
                + ", ".join(f"{q.label} ({q.value})" for q in selected)
                + ". No other quota was substituted.",
                code="QUOTA_NOT_SUPPORTED",
                details={
                    "requested_quotas": [q.value for q in selected],
                    "supported_quotas": [
                        q.value for q in QUOTA_ORDER if self._eligibility.is_supported(q)
                    ],
                },
            )
        if client_quota and client_quota.strip().upper() not in {q.value for q in selected}:
            notes.append(
                "The deprecated 'quota' field was ignored; searched quota(s): "
                + ", ".join(q.value for q in selected)
                + ". Use 'quotas' to choose GN or TQ."
            )
        if train_numbers and len(train_numbers) > self._settings.search_max_trains:
            raise InvalidRequestError(
                f"Select at most {self._settings.search_max_trains} trains per search.",
                code="TOO_MANY_TRAINS",
                details={"max_trains": self._settings.search_max_trains},
            )
        max_classes = self._settings.max_classes_per_search
        if len(classes) > max_classes:
            # Refused, never truncated: the user decides which classes to drop (D-29).
            raise InvalidRequestError(
                f"Select at most {max_classes} classes per search "
                f"({len(classes)} selected: {', '.join(classes)}).",
                code="TOO_MANY_CLASSES",
                details={"max_classes": max_classes, "selected_classes": list(classes)},
            )
        return JourneyRequest(
            source=source,
            destination=destination,
            journey_date=journey_date,
            classes=tuple(classes),
            filters=SearchFilters(allow_rac=allow_rac, allow_waitlist=allow_waitlist),
            max_segments=min(max_segments, limit),
            train_numbers=tuple(train_numbers) if train_numbers else None,
            notes=tuple(notes),
            quotas=selected,
        )

    async def preview(self, request: JourneyRequest) -> SearchContext:
        """Prepare a search exactly as :meth:`submit` would, without any availability request.

        The result lists the train x class x quota combinations a search started now would query
        (D-29). It costs at most one train search and one route per selected train — both cached
        and needed by the search itself. Provider errors propagate to the caller.
        """
        ctx = SearchContext(
            search_id=uuid.uuid4(),
            request=request,
            budget=SearchBudget(self._settings.search_max_availability_requests),
            deadline=self._clock.monotonic(),
        )
        summaries = await self._trains.search_trains(
            request.source, request.destination, request.journey_date
        )
        ctx.stats.trains_found = len(summaries)
        await self._prepare_trains(ctx, summaries)
        self._prepare_combinations(ctx)
        return ctx

    async def submit(self, request: JourneyRequest) -> SearchRecord:
        now = self._clock.now()
        record = SearchRecord(
            id=uuid.uuid4(),
            source=request.source,
            destination=request.destination,
            journey_date=request.journey_date,
            classes=list(request.classes),
            filters={
                "allow_rac": request.filters.allow_rac,
                "allow_waitlist": request.filters.allow_waitlist,
            },
            train_numbers=list(request.train_numbers) if request.train_numbers else None,
            quotas=[q.value for q in request.quotas],
            max_segments=request.max_segments,
            request_budget=self._settings.search_max_availability_requests,
            provider=self._provider_name,
            created_at=now,
            updated_at=now,
        )
        record.result_snapshot = self._snapshot(record, None, [], {}).model_dump(mode="json")
        await self._persistence.create_search(record)
        await self._executor.submit(record.id, lambda: self._run(record, request))
        if self._executor.runs_inline:
            return await self.get(record.id) or record
        return record

    async def request_stop(self, search_id: uuid.UUID) -> tuple[SearchRecord, bool] | None:
        """Ask a running search to stop (D-35). Idempotent; ``None`` for an unknown search.

        Returns the record and whether a stop was requested (``False`` once it has finished).
        The search then sends no new availability request: requests already sent finish and
        are kept, queued ones are withdrawn, and the results checked so far are published.
        """
        record = await self.get(search_id)
        if record is None:
            return None
        if record.status not in (SearchStatus.QUEUED, SearchStatus.RUNNING):
            return record, False
        local = self._running.get(search_id)
        if local is not None:
            self._mark_stopped(local)
        try:
            await self._store.set(
                keys.search_stop(str(search_id)),
                b"1",
                ttl_seconds=self._settings.search_deadline_seconds + STALE_SEARCH_GRACE_SECONDS,
            )
        except StoreError as error:
            if local is None:  # it runs elsewhere and the signal cannot reach it
                message = "The search could not be stopped. Please try again."
                raise ServiceUnavailableError(message) from error
            logger.warning("stop signal not shared; stopped in this process only")
        return record, True

    @staticmethod
    def _mark_stopped(ctx: SearchContext) -> None:
        ctx.stop_requested = True
        ctx.budget.stop()  # refuses new checks and retries; queued requests are withdrawn

    async def _stop_requested(self, ctx: SearchContext) -> bool:
        if ctx.stop_requested:
            return True
        try:
            flagged = await self._store.get(keys.search_stop(str(ctx.search_id))) is not None
        except StoreError:
            return False  # an unreachable store never stops a search by itself
        if flagged:
            self._mark_stopped(ctx)
        return flagged

    def stale_before(self) -> datetime:
        grace = self._settings.search_deadline_seconds + STALE_SEARCH_GRACE_SECONDS
        return self._clock.now() - timedelta(seconds=grace)

    async def get(self, search_id: uuid.UUID) -> SearchRecord | None:
        record = await self._persistence.get_search(search_id)
        if (
            record is not None
            and record.status in (SearchStatus.QUEUED, SearchStatus.RUNNING)
            and (record.updated_at or record.created_at) < self.stale_before()
        ):
            # Lazy reaping: the process running it died (any replica may answer the poll).
            record.status = SearchStatus.FAILED
            record.error_code = "INTERRUPTED"
            record.completed_at = record.updated_at = self._clock.now()
            await self._persistence.save_search(record)
        return record

    @staticmethod
    def response_for(record: SearchRecord) -> JourneySearchResponse:
        if record.result_snapshot is None:
            raise PersistenceError("search has no snapshot")
        response = JourneySearchResponse.model_validate(record.result_snapshot)
        # Status fields are authoritative on the row (e.g. FAILED after a restart).
        return response.model_copy(
            update={
                "status": record.status.value,
                "completed_at": record.completed_at,
                "error": response.error
                or (
                    SearchError(code=record.error_code, message="The search did not complete.")
                    if record.status is SearchStatus.FAILED and record.error_code
                    else None
                ),
            }
        )

    # --- Execution ------------------------------------------------------------------------------
    async def _run(self, record: SearchRecord, request: JourneyRequest) -> None:
        token = search_id_var.set(str(record.id))
        metrics.ACTIVE_SEARCHES.inc()
        started = time.perf_counter()
        try:
            record.status = SearchStatus.RUNNING
            record.started_at = record.updated_at = self._clock.now()
            await self._persistence.save_search(record)
            await self._execute(record, request)
        except asyncio.CancelledError:
            await self._fail(record, "INTERRUPTED", "The search was interrupted.")
            raise
        except PersistenceError:
            logger.exception("search aborted: persistence unavailable")
            await self._fail(record, "SERVICE_UNAVAILABLE", "Results could not be saved.")
        except Exception:
            logger.exception("search failed")
            await self._fail(record, "INTERNAL_ERROR", "The search failed unexpectedly.")
        finally:
            metrics.ACTIVE_SEARCHES.dec()
            metrics.SEARCH_DURATION.observe(time.perf_counter() - started)
            search_id_var.reset(token)

    async def _fail(self, record: SearchRecord, code: str, message: str) -> None:
        record.status = SearchStatus.FAILED
        record.error_code = code
        record.completed_at = record.updated_at = self._clock.now()
        snapshot = self._snapshot(
            record, None, [], {}, error=SearchError(code=code, message=message)
        )
        record.result_snapshot = snapshot.model_dump(mode="json")
        with contextlib.suppress(Exception):
            await self._persistence.save_search(record)

    async def _execute(self, record: SearchRecord, request: JourneyRequest) -> None:
        ctx = SearchContext(
            search_id=record.id,
            request=request,
            budget=SearchBudget(self._settings.search_max_availability_requests),
            deadline=self._clock.monotonic() + self._settings.search_deadline_seconds,
        )
        self._running[record.id] = ctx
        try:
            if not await self._discover_and_explore(ctx, record):
                return
            await self._complete(ctx, record)
        finally:
            self._running.pop(record.id, None)

    async def _discover_and_explore(self, ctx: SearchContext, record: SearchRecord) -> bool:
        """Train discovery, routes, combinations and availability. ``False`` if it failed."""
        request = ctx.request
        if await self._stop_requested(ctx):  # stopped before it started: ask nothing at all
            ctx.stats.stop_reason = IncompleteReason.STOPPED_BY_USER
            return True
        try:
            summaries = await self._trains.search_trains(
                request.source, request.destination, request.journey_date
            )
        except ProviderError as error:
            code = FATAL_DISCOVERY_CODES.get(error.category, "PROVIDER_ERROR")
            await self._fail(record, code, "Trains could not be retrieved from the provider.")
            return False

        ctx.stats.trains_found = len(summaries)
        await self._prepare_trains(ctx, summaries)
        self._prepare_combinations(ctx)
        await self._explore(ctx, record)
        return True

    async def _complete(self, ctx: SearchContext, record: SearchRecord) -> None:
        """Rank what was checked, persist the final snapshot and recommendations."""
        ranked_with_combo = self._rank(ctx)
        recommendation_outs = results.recommendation_outs(ctx, ranked_with_combo)
        counts: dict[int, int] = {}
        for _, combo in ranked_with_combo:
            counts[combo.combo_id] = counts.get(combo.combo_id, 0) + 1

        state, reason = results.completeness(ctx, has_recommendations=bool(recommendation_outs))
        coverage = results.coverage(ctx)
        record.status = SearchStatus.COMPLETED
        record.search_completeness, record.incomplete_reason = state, reason
        record.requests_made, record.cache_hits = ctx.budget.used, ctx.stats.cache_hits
        record.completed_at = record.updated_at = self._clock.now()
        record.result_snapshot = self._snapshot(
            record, ctx, recommendation_outs, counts
        ).model_dump(mode="json")
        await self._persistence.save_recommendations(
            results.recommendation_records(
                record.id, ranked_with_combo, created_at=self._clock.now()
            )
        )
        await self._persistence.save_search(record)

        metrics.SEARCHES.labels(state.value).inc()
        metrics.SEARCH_RESULTS.observe(len(recommendation_outs))
        metrics.SEARCH_BUDGET_USED.observe(ctx.budget.used)
        metrics.SEARCH_RETRIES.labels("made").inc(ctx.budget.retries)
        metrics.SEARCH_RETRIES.labels("refused").inc(ctx.budget.retries_refused)
        metrics.SEARCH_COMBINATIONS_NOT_REACHED.observe(coverage.combinations_not_reached)
        if (share := results.uncertain_prediction_coverage(recommendation_outs)) is not None:
            metrics.PREDICTION_COVERAGE.observe(share)
        logger.info(
            "search completed",
            extra={
                "completeness": state.value,
                "incomplete_reason": reason.value if reason else None,
                "recommendations": len(recommendation_outs),
                "availability_requests_made": ctx.budget.used,
                "availability_checks_made": ctx.budget.checks,
                "availability_retries": ctx.budget.retries,
                "availability_retries_refused": ctx.budget.retries_refused,
                "combinations": coverage.combinations_evaluated,
                "combinations_not_reached": coverage.combinations_not_reached,
                "cache_hits": ctx.stats.cache_hits,
            },
        )

    async def _prepare_trains(self, ctx: SearchContext, summaries: list[TrainSummary]) -> None:
        request = ctx.request
        wanted = set(request.train_numbers) if request.train_numbers else None
        selected: list[TrainSummary] = []
        for summary in summaries:
            if wanted is not None and summary.train_number not in wanted:
                continue
            if (
                summary.from_station_code != request.source
                or summary.to_station_code != request.destination
            ):
                ctx.trains.append(TrainContext(summary, summary.train_number, "DIFFERENT_STATIONS"))
                continue
            if len(selected) >= self._settings.search_max_trains:
                ctx.trains.append(
                    TrainContext(summary, summary.train_number, "SKIPPED_TRAIN_LIMIT")
                )
                continue
            selected.append(summary)
        if wanted is not None:
            found = {s.train_number for s in summaries}
            for number in request.train_numbers or ():
                if number not in found:
                    ctx.trains.append(TrainContext(None, number, "NOT_IN_TRAIN_SEARCH"))
        if any(t.evaluation == "SKIPPED_TRAIN_LIMIT" for t in ctx.trains):
            ctx.warnings.append(
                f"Only the first {self._settings.search_max_trains} trains were evaluated; "
                "choose specific trains to search others."
            )

        async def load(summary: TrainSummary) -> TrainContext:
            train = TrainContext(summary, summary.train_number, "EVALUATED")
            try:
                route, analysis = await self._trains.get_route(summary.train_number)
            except ProviderError as error:
                train.evaluation = "ROUTE_UNAVAILABLE"
                train.issues = [f"PROVIDER_{error.category.value}"]
                ctx.stats.route_failures += 1
                return train
            journey = validate_journey(analysis, request.source, request.destination)
            train.route, train.analysis, train.journey = route, analysis, journey
            train.issues = [issue.value for issue in journey.issues]
            if not journey.verified or journey.source_index is None:
                train.evaluation = "ROUTE_UNVERIFIED"
                return train
            train.start_date = train_start_date(
                request.journey_date, analysis, journey.source_index
            )
            return train

        ctx.trains.extend(await asyncio.gather(*(load(s) for s in selected)))

    def _prepare_combinations(self, ctx: SearchContext) -> None:
        """Turn every offered train x class x quota whose booking window allows it into a
        planner combination. Combination ids are quota-major (General first, exactly as in a
        General-only search); the planner's round-robin order interleaves quotas. Skipped quotas
        are recorded with their eligibility, never queried.
        """
        request = ctx.request
        cap = self._settings.planner_max_intermediate_stops
        now = self._eligibility.now()  # one instant for every combination of this search
        layouts: list[tuple[TrainContext, int, int, tuple[int, ...], dict[int, float]]] = []
        for train in ctx.trains:
            journey, route = train.journey, train.route
            if train.evaluation != "EVALUATED" or journey is None or route is None:
                continue
            source = require(journey.source_index, "source index")
            destination = require(journey.destination_index, "destination index")
            weights = {
                index: float(route.stops[index].halt_minutes or 0)
                + 0.001 * min(index - source, destination - index)
                for index in journey.intermediate_indices
            }
            considered = tuple(
                sorted(sorted(journey.intermediate_indices, key=lambda i: (-weights[i], i))[:cap])
            )
            train.considered = considered
            layouts.append((train, source, destination, considered, weights))
            for travel_class in request.classes:
                if route.classes is not None and travel_class not in route.classes:
                    train.class_states[travel_class] = "NOT_OFFERED"
                    continue
                for quota in request.quotas:
                    train.eligibility[(travel_class, quota)] = self._eligibility.evaluate(
                        quota,
                        travel_class,
                        train_origin_date=train.start_date,  # never the boarding date
                        boarding_date=request.journey_date,
                        now=now,
                    )

        by_quota: dict[Quota, list[ComboSpec]] = {quota: [] for quota in request.quotas}
        for quota in request.quotas:
            for train, source, destination, considered, weights in layouts:
                for travel_class in request.classes:
                    eligibility = train.eligibility.get((travel_class, quota))
                    if eligibility is None:  # class not offered by this train
                        continue
                    if not eligibility.queryable:
                        ctx.stats.combinations_not_queried += 1
                        continue
                    combo_id = len(ctx.combos)
                    ctx.combos[combo_id] = ComboContext(combo_id, train, travel_class, quota)
                    by_quota[quota].append(
                        ComboSpec(
                            combo_id,
                            source,
                            destination,
                            considered,
                            {i: weights[i] for i in considered},
                        )
                    )
        not_offered = sorted(
            {c for t in ctx.trains for c, s in t.class_states.items() if s == "NOT_OFFERED"}
        )
        if not_offered:
            ctx.warnings.append(
                "Some selected classes are not listed for some trains and were not checked: "
                + ", ".join(not_offered)
                + "."
            )
        # Round-robin order alternates quotas (GN, TQ, GN, TQ, …) so that when the budget cannot
        # cover every direct check, neither quota is starved by the other (D-27).
        specs = [
            spec
            for group in itertools.zip_longest(*by_quota.values())
            for spec in group
            if spec is not None
        ]
        ctx.planner = QueryPlanner(
            specs, filters=request.filters, max_segments=request.max_segments
        )

    def _segment_request(self, ctx: SearchContext, query: PlannedQuery) -> SegmentRequest:
        combo = ctx.combos[query.combo_id]
        train = combo.train
        route = require(train.route, "route")
        analysis = require(train.analysis, "route analysis")
        start = require(train.start_date, "train start date")
        stops = route.stops
        key = SegmentKey(
            train.train_number,
            start,
            stops[query.from_index].station_code,
            stops[query.to_index].station_code,
            combo.travel_class,
            combo.quota,
        )
        policy: AvailabilityDatePolicy = self._settings.availability_date_policy
        return SegmentRequest(key, provider_query_date(start, analysis, query.from_index, policy))

    async def _explore(self, ctx: SearchContext, record: SearchRecord) -> None:
        planner = require(ctx.planner, "planner")
        last_published: float | None = None
        window = self._settings.maintenance_window
        while not ctx.stats.hard_stop:
            if await self._stop_requested(ctx):
                # User stop (D-35): no new wave. Requests of the last wave have finished and
                # are kept; any it had to withdraw were released as "not checked".
                if not planner.finished:
                    ctx.stats.stop_reason = IncompleteReason.STOPPED_BY_USER
                break
            if window is not None and window.active(self._clock.now()):
                # A search started just before 23:45 IST sends nothing more once it begins.
                if not planner.finished:
                    ctx.stats.stop_reason = IncompleteReason.RAILWAY_MAINTENANCE_WINDOW
                break
            if self._clock.monotonic() >= ctx.deadline:
                ctx.stats.deadline_hit = not planner.finished
                break
            if ctx.budget.remaining <= 0:
                if not planner.finished:
                    ctx.stats.stop_reason = IncompleteReason.AVAILABILITY_REQUEST_BUDGET_REACHED
                break
            wave = planner.next_wave(min(self._wave_size, ctx.budget.remaining))
            if not wave:
                break
            checks = await asyncio.gather(
                *(
                    self._availability.check(self._segment_request(ctx, q), budget=ctx.budget)
                    for q in wave
                )
            )
            runs = []
            for query, result in zip(wave, checks, strict=True):
                self._absorb(ctx, query, result)
                run = run_record(result, search_id=ctx.search_id, clock=self._clock)
                if run is not None:
                    runs.append(run)
            await self._persistence.add_segment_runs(runs)
            now = self._clock.monotonic()
            if last_published is None or now - last_published >= self.progress_interval_seconds:
                await self._publish_progress(ctx, record)
                last_published = now
        if not planner.finished:
            planner.stop()

    def _absorb(self, ctx: SearchContext, query: PlannedQuery, result: SegmentCheckResult) -> None:
        planner, stats = require(ctx.planner, "planner"), ctx.stats
        if result.outcome is None:
            planner.release(query)
            stats.stop_reason = (
                stats.stop_reason or IncompleteReason.AVAILABILITY_REQUEST_BUDGET_REACHED
            )
            return
        if result.succeeded and result.observation is not None:
            observation = result.observation
            planner.record(query, observation.record.status)
            combo = ctx.combos[query.combo_id]
            combo.observations[query.edge] = observation
            if result.cache_hit:
                stats.cache_hits += 1
                combo.cached_observation_ids.add(observation.id)
            if observation.record.status is AvailabilityStatus.UNKNOWN:
                stats.segments_unknown += 1
            else:
                stats.segments_checked += 1
            return
        outcome = result.outcome
        if outcome is SegmentQueryOutcome.QUOTA_EXHAUSTED:
            planner.release(query)
            reason = result.error.diagnostics.get("reason") if result.error else None
            stats.stop_reason = (
                IncompleteReason.PROVIDER_RATE_LIMITED
                if reason == QuotaRefusal.BACKOFF
                else IncompleteReason.PROVIDER_QUOTA_GUARD_REACHED
            )
            stats.hard_stop = True
            return
        planner.record(query, None)
        stats.segments_failed += 1
        if outcome is SegmentQueryOutcome.RATE_LIMITED:
            stats.stop_reason, stats.hard_stop = IncompleteReason.PROVIDER_RATE_LIMITED, True
        elif outcome is SegmentQueryOutcome.AUTH_ERROR:
            stats.stop_reason, stats.hard_stop = IncompleteReason.PROVIDER_AUTH_ERROR, True

    def _rank(self, ctx: SearchContext) -> list[tuple[RankedPath, ComboContext]]:
        candidates = []
        owner: dict[tuple[GraphKey, tuple[str, ...]], ComboContext] = {}
        for combo in ctx.combos.values():
            train = combo.train
            journey = train.journey
            if journey is None or train.route is None or train.start_date is None:
                continue
            source = require(journey.source_index, "source index")
            destination = require(journey.destination_index, "destination index")
            index = {train.route.stops[i].station_code: i for i in journey.boundary_indices}
            key = GraphKey(train.train_number, train.start_date, combo.travel_class, combo.quota)
            graph = build_graph(key, combo.observations.values(), index, ctx.request.filters)
            for path in find_paths(
                graph,
                source,
                destination,
                max_segments=ctx.request.max_segments,
                max_paths=self._settings.max_paths_per_combination,
            ):
                candidates.append((key, path))
                owner[(key, path.stations)] = combo
        ranked = rank_paths(candidates, limit=self._settings.max_recommendations)
        return [(item, owner[(item.key, item.path.stations)]) for item in ranked]

    async def _publish_progress(self, ctx: SearchContext, record: SearchRecord) -> None:
        ranked = self._rank(ctx)
        outs = results.recommendation_outs(ctx, ranked)
        counts: dict[int, int] = {}
        for _, combo in ranked:
            counts[combo.combo_id] = counts.get(combo.combo_id, 0) + 1
        record.requests_made, record.cache_hits = ctx.budget.used, ctx.stats.cache_hits
        record.updated_at = self._clock.now()
        record.result_snapshot = self._snapshot(record, ctx, outs, counts).model_dump(mode="json")
        await self._persistence.save_search(record)

    def _snapshot(
        self,
        record: SearchRecord,
        ctx: SearchContext | None,
        recommendations: list[RecommendationOut],
        counts: dict[int, int],
        *,
        error: SearchError | None = None,
    ) -> JourneySearchResponse:
        return results.build_response(
            record,
            ctx,
            recommendations=recommendations,
            counts=counts,
            data_mode=self._data_mode,
            stale_after_seconds=self._settings.stale_after_seconds,
            date_policy_verified=self._settings.availability_date_policy_verified,
            provider_quotas=frozenset(q for q in QUOTA_ORDER if self._eligibility.is_supported(q)),
            error=error,
        )


def normalize_quotas(quotas: list[str] | None) -> tuple[Quota, ...]:
    """Requested quota codes in canonical order (GN, TQ); General when none were given."""
    if not quotas:
        return (Quota.GENERAL,)
    wanted: set[Quota] = set()
    for code in quotas:
        try:
            wanted.add(Quota(code.strip().upper()))
        except ValueError:
            raise InvalidRequestError(
                f"Unsupported quota: {code}.",
                code="UNSUPPORTED_QUOTA",
                details={"quotas": [q.value for q in QUOTA_ORDER]},
            ) from None
    return tuple(q for q in QUOTA_ORDER if q in wanted)


def validate_trip(
    settings: Settings,
    clock: Clock,
    source: str,
    destination: str,
    journey_date: date,
    classes: list[str],
) -> None:
    if source == destination:
        raise SemanticValidationError(
            "Source and destination must be different stations.", code="INVALID_JOURNEY"
        )
    today = today_ist(clock.now())
    last = today + timedelta(days=settings.max_advance_booking_days)
    if not today <= journey_date <= last:
        raise InvalidRequestError(
            f"Journey date must be between {today.isoformat()} and {last.isoformat()} (IST).",
            code="INVALID_JOURNEY_DATE",
        )
    unsupported = [c for c in classes if c not in settings.supported_classes]
    if unsupported:
        raise SemanticValidationError(
            f"Unsupported class: {', '.join(unsupported)}.",
            code="UNSUPPORTED_CLASS",
            details={"supported_classes": settings.supported_classes},
        )

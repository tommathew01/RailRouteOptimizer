"use client";

import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { MaintenanceNotice } from "@/components/MaintenanceNotice";
import { Notice } from "@/components/StatusBits";
import { TrainCard } from "@/components/TrainCard";
import { ApiError } from "@/lib/api/client";
import {
  metaQuery,
  searchPreviewQuery,
  startOptimization,
  trainSearchQuery,
  type OptimizeInput,
} from "@/lib/api/queries";
import type { SearchPlan } from "@/lib/api/schemas";
import { formatCalendarDate } from "@/lib/format";
import { canAdd, classLimitMessage, planSummary } from "@/lib/limits";
import { quotaList } from "@/lib/quotas";
import { parseJourneyQuery, type JourneyQuery } from "@/lib/search-params";
import { nearbyStationPairs, pairSearchHref } from "@/lib/station-pairs";
import { useRailwayMaintenance } from "@/lib/use-maintenance";

export function TrainSelection() {
  const params = useSearchParams();
  const query = parseJourneyQuery(params);
  if (!query) {
    return (
      <Notice tone="danger" title="This search link is incomplete">
        <Link href="/" className="font-semibold underline">
          Start a new search
        </Link>
      </Notice>
    );
  }
  return (
    <TrainList
      key={params.toString()}
      query={query}
      fromName={params.get("fromName")}
      toName={params.get("toName")}
      modifyHref={`/?${params.toString()}`}
    />
  );
}

function TrainList({
  query,
  fromName,
  toName,
  modifyHref,
}: {
  query: JourneyQuery;
  fromName: string | null;
  toName: string | null;
  modifyHref: string;
}) {
  const router = useRouter();
  const { data: meta } = useQuery(metaQuery);
  const railway = useRailwayMaintenance();
  // During the IRCTC window no new train lookup is made; an already loaded list stays visible.
  const trains = useQuery({
    ...trainSearchQuery({ source: query.from, destination: query.to, journey_date: query.date }),
    enabled: railway.open,
  });
  const limits = meta?.limits;
  const maxTrains = limits?.max_trains_per_search;
  // Nothing is pre-selected: the user chooses every train (D-32).
  const [chosen, setChosen] = useState<Set<string>>(() => new Set());
  const [selectionError, setSelectionError] = useState<string | null>(null);

  const eligible = (trains.data?.trains ?? []).filter((t) => t.serves_requested_stations);
  const pairs = trains.data ? nearbyStationPairs(trains.data.trains, query) : [];
  // An old link may carry more classes than allowed: say so instead of dropping any (D-29).
  const classProblem = classLimitMessage(query.classes, limits?.max_classes_per_search);

  const input: OptimizeInput = {
    source: query.from,
    destination: query.to,
    journey_date: query.date,
    classes: query.classes,
    filters: { allow_rac: query.rac, allow_waitlist: query.wl },
    train_numbers: [...chosen].sort(),
    quotas: query.quotas,
  };
  const preview = useQuery({
    ...searchPreviewQuery(input),
    enabled: chosen.size > 0 && classProblem === null && eligible.length > 0 && railway.open,
    placeholderData: keepPreviousData,
  });

  const optimize = useMutation({
    mutationFn: () => startOptimization(input),
    onSuccess: ({ searchId }) => router.push(`/results/${searchId}`),
  });

  function toggle(trainNumber: string) {
    const next = new Set(chosen);
    if (next.has(trainNumber)) next.delete(trainNumber);
    else if (canAdd(next.size, maxTrains)) next.add(trainNumber);
    setChosen(next);
    if (next.size > 0) setSelectionError(null);
  }

  function findCombinations() {
    if (chosen.size === 0) {
      // No request without a selection: an omitted train list would mean "all trains".
      setSelectionError("Select at least one train to find segment combinations.");
      return;
    }
    optimize.mutate();
  }

  const optimizeError = optimize.error instanceof ApiError ? optimize.error : null;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">
            {fromName ?? query.from} <span aria-hidden="true">→</span>
            <span className="sr-only"> to </span> {toName ?? query.to}
          </h1>
          <p className="text-muted">
            {formatCalendarDate(query.date)} · {query.classes.join(", ")} · {quotaList(query.quotas)}{" "}
            quota{query.quotas.length === 1 ? "" : "s"}
            {query.rac ? " · RAC allowed" : ""}
            {query.wl ? " · waitlist allowed" : ""}
          </p>
        </div>
        <Link href={modifyHref} className="btn btn-secondary">
          Modify search
        </Link>
      </header>

      {railway.active ? <MaintenanceNotice maintenance={railway.maintenance} /> : null}

      {trains.isPending && railway.active ? null : trains.isPending ? (
        <div className="space-y-3" aria-busy="true" aria-live="polite">
          <p className="text-muted">Finding trains…</p>
          <div className="card h-24 animate-pulse" />
          <div className="card h-24 animate-pulse" />
        </div>
      ) : trains.isError ? (
        <Notice tone="danger" title="Trains could not be loaded">
          {trains.error instanceof ApiError ? trains.error.message : "Please try again."}
        </Notice>
      ) : trains.data.trains.length === 0 ? (
        <Notice tone="info" title="No direct trains found between these stations on this date">
          RailRoute only combines tickets on the same train. Try another date or nearby stations.
        </Notice>
      ) : (
        <>
          {eligible.length === 0 ? (
            <Notice tone="info" title={`No train runs exactly ${query.from} → ${query.to} on this date`}>
              <p>
                The provider found trains between nearby stations. Every ticket in a recommendation
                must start and end at the stations you search, so search one of these instead:
              </p>
              <ul className="mt-2 space-y-1">
                {pairs.map((pair) => (
                  <li key={`${pair.from}-${pair.to}`}>
                    <Link href={pair.href} className="font-semibold text-brand underline-offset-4 hover:underline">
                      {pair.fromName ?? pair.from} ({pair.from}) → {pair.toName ?? pair.to} ({pair.to})
                    </Link>{" "}
                    <span className="text-muted">
                      · {pair.trains} train{pair.trains === 1 ? "" : "s"}
                    </span>
                  </li>
                ))}
              </ul>
            </Notice>
          ) : (
            <p className="text-sm text-muted" id="selection-help">
              {maxTrains ? `Select up to ${maxTrains} trains. ` : ""}Each selected train × class ×
              quota is checked within a fixed request budget, so fewer trains means deeper checks.
              {query.quotas.some((q) => q !== "GN")
                ? " Tatkal quotas are only checked once their booking window has opened."
                : ""}
            </p>
          )}
          {classProblem ? (
            <Notice tone="danger" title="Too many classes for one search">
              <p>{classProblem}</p>
              <Link href={modifyHref} className="font-semibold underline">
                Modify search to choose the classes to keep
              </Link>
            </Notice>
          ) : null}
          <ul className="space-y-3" aria-describedby="selection-help">
            {trains.data.trains.map((train) => (
              <li key={train.train_number}>
                <TrainCard
                  train={train}
                  selected={chosen.has(train.train_number)}
                  onToggle={() => toggle(train.train_number)}
                  route={[query.from, query.to]}
                  alternativeHref={
                    train.serves_requested_stations
                      ? undefined
                      : pairSearchHref(
                          query,
                          train.boards_at,
                          train.alights_at,
                          train.boards_at_name,
                          train.alights_at_name,
                        )
                  }
                />
              </li>
            ))}
          </ul>
          <div
            hidden={eligible.length === 0}
            className="sticky bottom-0 -mx-4 border-t border-border bg-background/95 px-4 py-3 backdrop-blur sm:mx-0 sm:rounded-xl sm:border"
          >
            <PlanPanel
              plan={chosen.size > 0 && classProblem === null ? preview.data : undefined}
              loading={preview.isFetching}
              error={preview.error instanceof ApiError ? preview.error.message : null}
            />
            {selectionError ? (
              <p role="alert" className="mb-2 text-sm text-danger">
                {selectionError}
              </p>
            ) : null}
            {optimizeError ? (
              <p role="alert" className="mb-2 text-sm text-danger">
                {optimizeError.message}
                {optimizeError.retryAfterSeconds
                  ? ` Try again in about ${Math.ceil(optimizeError.retryAfterSeconds / 60)} min.`
                  : ""}
              </p>
            ) : null}
            <button
              type="button"
              className="btn btn-primary w-full sm:w-auto"
              disabled={classProblem !== null || railway.active || optimize.isPending}
              onClick={findCombinations}
            >
              {optimize.isPending
                ? "Starting search…"
                : `Find segment combinations (${chosen.size} train${chosen.size === 1 ? "" : "s"})`}
            </button>
          </div>
        </>
      )}
    </div>
  );
}

/** Combinations, budget and the depth trade-off, computed by the server before the search. */
function PlanPanel({
  plan,
  loading,
  error,
}: {
  plan: SearchPlan | undefined;
  loading: boolean;
  error: string | null;
}) {
  if (error) {
    return (
      <p role="alert" className="mb-2 text-sm text-danger">
        {error}
      </p>
    );
  }
  if (!plan) {
    return loading ? (
      <p className="mb-2 text-sm text-muted" aria-live="polite">
        Counting combinations…
      </p>
    ) : null;
  }
  const notes = plan.quotas.flatMap((q) => q.notes);
  return (
    <div className="mb-3 space-y-1 text-sm" aria-live="polite" aria-busy={loading}>
      <p className={plan.covers_direct_checks ? "font-semibold" : "font-semibold text-danger"}>
        {planSummary(plan)}
      </p>
      {plan.explanation.map((line) => (
        <p key={line} className="text-muted">
          {line}
        </p>
      ))}
      {notes.map((note) => (
        <p key={note} className="text-muted">
          {note}
        </p>
      ))}
    </div>
  );
}

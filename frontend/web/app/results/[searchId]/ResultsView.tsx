"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";

import {
  BookingGuidance,
  CoverageNotice,
  QuotaStatus,
  RecommendationCard,
  SearchProgress,
} from "@/components/Results";
import { Notice } from "@/components/StatusBits";
import { ApiError } from "@/lib/api/client";
import { journeySearchQuery, startOptimization } from "@/lib/api/queries";
import type { JourneySearch } from "@/lib/api/schemas";
import { formatCalendarDate, formatTime } from "@/lib/format";
import { classEvaluationText, quotaList } from "@/lib/quotas";
import { journeyQueryString } from "@/lib/search-params";

const EVALUATION_TEXT: Record<string, string> = {
  EVALUATED: "Checked",
  ROUTE_UNVERIFIED: "Route could not be verified — skipped",
  ROUTE_UNAVAILABLE: "Route unavailable from provider — skipped",
  DIFFERENT_STATIONS: "Serves different stations — skipped",
  NOT_IN_TRAIN_SEARCH: "Not found for this date",
  SKIPPED_TRAIN_LIMIT: "Not checked (train limit)",
};

export function ResultsView({ searchId }: { searchId: string }) {
  const { data, isPending, isError, error } = useQuery(journeySearchQuery(searchId));

  if (isPending) {
    return (
      <div className="space-y-3" aria-busy="true">
        <p className="text-muted">Loading search…</p>
        <div className="card h-40 animate-pulse" />
      </div>
    );
  }
  if (isError) {
    const notFound = error instanceof ApiError && error.status === 404;
    return (
      <Notice tone="danger" title={notFound ? "Search not found" : "Results could not be loaded"}>
        <p>{notFound ? "This search link is invalid or has expired." : error.message}</p>
        <Link href="/" className="font-semibold underline">
          Start a new search
        </Link>
      </Notice>
    );
  }
  return <ResultsBody search={data} />;
}

function ResultsBody({ search }: { search: JourneySearch }) {
  const router = useRouter();
  const request = search.request;
  const running = search.status === "QUEUED" || search.status === "RUNNING";
  const rerun = useMutation({
    mutationFn: () =>
      startOptimization({
        source: request.source,
        destination: request.destination,
        journey_date: request.journey_date,
        classes: request.classes,
        filters: request.filters,
        train_numbers: request.train_numbers ?? undefined,
        quotas: request.quotas,
      }),
    onSuccess: ({ searchId }) => router.push(`/results/${searchId}`),
  });
  const modifyHref = `/?${journeyQueryString({
    from: request.source,
    to: request.destination,
    date: request.journey_date,
    classes: request.classes,
    quotas: request.quotas,
    rac: request.filters.allow_rac,
    wl: request.filters.allow_waitlist,
  })}`;

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
      <div className="space-y-5">
        <header className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold">
              {request.source} <span aria-hidden="true">→</span>
              <span className="sr-only"> to </span> {request.destination}
            </h1>
            <p className="text-muted">
              {formatCalendarDate(request.journey_date)} · {request.classes.join(", ")} ·{" "}
              {quotaList(request.quotas)} quota{request.quotas.length === 1 ? "" : "s"} · up to{" "}
              {request.max_segments} tickets
              {request.filters.allow_rac ? " · RAC allowed" : ""}
              {request.filters.allow_waitlist ? " · waitlist allowed" : ""}
            </p>
          </div>
          <div className="flex gap-2">
            <Link href={modifyHref} className="btn btn-secondary">
              Modify
            </Link>
            <button
              type="button"
              className="btn btn-secondary"
              disabled={running || rerun.isPending}
              onClick={() => rerun.mutate()}
            >
              {rerun.isPending ? "Starting…" : "Check again"}
            </button>
          </div>
        </header>
        {rerun.error instanceof ApiError ? (
          <p role="alert" className="text-sm text-danger">
            {rerun.error.message}
          </p>
        ) : null}

        {running ? <SearchProgress search={search} /> : null}
        {search.status === "FAILED" ? (
          <Notice tone="danger" title="The search did not complete">
            {search.error?.message ?? "Please try again."}
          </Notice>
        ) : null}
        {search.status === "COMPLETED" ? <CoverageNotice search={search} /> : null}
        <QuotaStatus search={search} />

        <section aria-labelledby="results-title" aria-live="polite">
          <h2 id="results-title" className="mb-3 text-lg font-semibold">
            {running ? "Preliminary combinations" : "Recommended combinations"}
            <span className="ml-2 text-sm font-normal text-muted">
              ({search.recommendations.length})
            </span>
          </h2>
          {search.recommendations.length === 0 && !running ? (
            <p className="text-muted">
              No combination matched your filters in the segments checked.
            </p>
          ) : (
            <ol className="space-y-4">
              {search.recommendations.map((rec) => (
                <li key={`${rec.train_number}-${rec.travel_class}-${rec.quota}-${rec.rank}`}>
                  <RecommendationCard recommendation={rec} staleAfter={search.stale_after_seconds} />
                </li>
              ))}
            </ol>
          )}
        </section>

        {search.trains.length ? (
          <details className="card">
            <summary className="cursor-pointer font-semibold">
              Trains checked ({search.trains.length})
            </summary>
            <ul className="mt-3 space-y-3 text-sm">
              {search.trains.map((train) => (
                <li key={train.train_number}>
                  <p className="font-semibold">
                    {train.train_name ?? "Train"} #{train.train_number} —{" "}
                    {EVALUATION_TEXT[train.evaluation] ?? train.evaluation}
                  </p>
                  {train.departure ? (
                    <p className="text-muted">
                      Departs {formatTime(train.departure)} · arrives {formatTime(train.arrival)} IST ·
                      checked {train.intermediate_stops_considered} of {train.intermediate_stops_total} intermediate stops
                    </p>
                  ) : null}
                  <p className="text-muted">
                    {train.classes
                      .map((c) => classEvaluationText(c, request.quotas.length > 1))
                      .join(" · ")}
                  </p>
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </div>

      <div className="space-y-4 lg:sticky lg:top-4 lg:self-start">
        <BookingGuidance warnings={search.warnings} />
      </div>
    </div>
  );
}

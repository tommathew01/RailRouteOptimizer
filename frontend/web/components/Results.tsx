"use client";

import { useState } from "react";

import { AvailabilityBadge, Notice, PredictionIndicator, StaleIndicator, toneClass } from "@/components/StatusBits";
import type { JourneySearch, Recommendation, Segment } from "@/lib/api/schemas";
import { formatDayMonth, formatMoney, formatTime } from "@/lib/format";
import { quotaSummaryText } from "@/lib/quotas";
import { COMPLETENESS_TEXT, stoppedByUser, stoppedTitle, TIER_TONE } from "@/lib/status";

export function SearchProgress({
  search,
  onStop,
  stopping = false,
  stopError = null,
}: {
  search: JourneySearch;
  /** Stops the server-side search; absent when stopping is not possible. */
  onStop?: () => void;
  stopping?: boolean;
  stopError?: string | null;
}) {
  const coverage = search.coverage;
  const made = coverage?.availability_requests_made ?? 0;
  const budget = coverage?.request_budget ?? 0;
  const percent = budget ? Math.min(100, Math.round((made / budget) * 100)) : 0;
  return (
    <section aria-labelledby="progress-title" className="card">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="progress-title" className="font-semibold">
          {stopping
            ? "Stopping…"
            : search.status === "QUEUED"
              ? "Search queued…"
              : "Checking segment availability…"}
        </h2>
        {onStop ? (
          <button type="button" className="btn btn-secondary" onClick={onStop} disabled={stopping}>
            {stopping ? "Stopping…" : "Stop search"}
          </button>
        ) : null}
      </div>
      <div
        className="mt-3 h-2 w-full overflow-hidden rounded-full bg-surface-muted"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={budget || 1}
        aria-valuenow={made}
        aria-label="Availability requests used"
      >
        <div className="h-full bg-brand transition-all" style={{ width: `${percent}%` }} />
      </div>
      <p className="mt-2 text-sm text-muted" aria-live="polite">
        {made} of {budget} provider requests used
        {coverage?.availability_retries ? ` (${coverage.availability_retries} retries)` : ""} ·{" "}
        {coverage?.cache_hits ?? 0} served from cache · {search.recommendations.length}{" "}
        combination(s) found so far
      </p>
      {stopping ? (
        <p className="mt-1 text-sm text-muted" aria-live="polite">
          No new availability checks are sent. Requests already sent are finishing; the results
          found so far will stay.
        </p>
      ) : null}
      {stopError ? (
        <p role="alert" className="mt-1 text-sm text-danger">
          {stopError}
        </p>
      ) : null}
    </section>
  );
}

export function CoverageNotice({ search }: { search: JourneySearch }) {
  const completeness = search.search_completeness;
  if (!completeness || !search.coverage) return null;
  const meta = COMPLETENESS_TEXT[completeness] ?? { title: completeness, tone: "info" as const };
  const c = search.coverage;
  const stopped = stoppedByUser(search);
  return (
    <Notice tone={meta.tone} title={stopped ? stoppedTitle(search) : meta.title}>
      {stopped ? (
        <p className="mb-1">
          You stopped the search. These are the best of the segments checked so far — segments
          that were not checked may hold better options.
        </p>
      ) : null}
      <p>
        Checked {c.segments_checked} segment(s) across {c.trains_evaluated} train(s) and{" "}
        {c.combinations_evaluated} train × class × quota combination(s)
        {c.combinations_not_queried
          ? ` (${c.combinations_not_queried} more not checked: quota not open or not supported)`
          : ""}
        : {c.availability_requests_made} of {c.request_budget} provider requests used
        {c.availability_retries ? ` (including ${c.availability_retries} retries)` : ""},{" "}
        {c.cache_hits} from cache
        {c.segments_failed ? `, ${c.segments_failed} failed` : ""}
        {c.segments_unknown ? `, ${c.segments_unknown} unclear` : ""}.
        {c.combinations_not_reached && !stopped
          ? ` ${c.combinations_not_reached} combination(s) could not be checked at all within the budget — select fewer trains or classes.`
          : ""}
        {c.availability_requests_planned > c.availability_requests_made + c.cache_hits
          ? ` About ${c.availability_requests_planned - c.availability_requests_made - c.cache_hits} more checks were needed for full coverage.`
          : ""}
      </p>
      {completeness.startsWith("NO_PATH") && !stopped ? (
        <p className="mt-1">
          {completeness === "NO_PATH_FOUND_PARTIAL"
            ? "No combination was found in the segments checked — that does not mean none exist."
            : "Try allowing RAC or waitlisted segments, another class or another date."}
        </p>
      ) : null}
    </Notice>
  );
}

function SegmentRow({ segment, staleAfter }: { segment: Segment; staleAfter: number }) {
  return (
    <li className="relative pb-4 pl-6 last:pb-0">
      <span aria-hidden="true" className="absolute top-1.5 left-0 h-3 w-3 rounded-full border-2 border-brand bg-surface" />
      <span aria-hidden="true" className="absolute top-5 bottom-0 left-[5px] w-0.5 bg-border" />
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <p className="font-semibold">
          {segment.source_name ?? segment.source} <span className="font-mono text-xs text-muted">{segment.source}</span>
          <span aria-hidden="true" className="mx-1">→</span>
          <span className="sr-only"> to </span>
          {segment.destination_name ?? segment.destination}{" "}
          <span className="font-mono text-xs text-muted">{segment.destination}</span>
        </p>
        <AvailabilityBadge status={segment.status} text={segment.availability_text} />
      </div>
      <p className="mt-1 text-sm text-muted">
        Departs {formatDayMonth(segment.departure)} {formatTime(segment.departure)} · arrives{" "}
        {formatDayMonth(segment.arrival)} {formatTime(segment.arrival)} IST
        {segment.fare ? ` · ${formatMoney(segment.fare.amount, segment.fare.currency)}` : " · fare unavailable"}
      </p>
      <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1">
        {segment.status === "RAC" || segment.status === "WAITLIST" || segment.prediction ? (
          <PredictionIndicator prediction={segment.prediction} />
        ) : null}
        {segment.raw_status ? (
          <span className="text-xs text-muted">
            Provider status: <span className="font-mono">{segment.raw_status}</span>
          </span>
        ) : null}
        {segment.can_book === true && segment.status === "WAITLIST" ? (
          <span className="text-xs text-muted">Bookable, but not confirmed</span>
        ) : null}
        <StaleIndicator checkedAt={segment.checked_at} staleAfterSeconds={staleAfter} />
      </div>
      {segment.boards_on_later_date ? (
        <p className="mt-1 text-xs text-rac">
          Boards after midnight · availability checked for {segment.provider_query_date}.
        </p>
      ) : null}
    </li>
  );
}

export function RecommendationCard({
  recommendation: rec,
  staleAfter,
}: {
  recommendation: Recommendation;
  staleAfter: number;
}) {
  const [showSteps, setShowSteps] = useState(false);
  const tone = TIER_TONE[rec.status_tier] ?? "unknown";
  const tickets = rec.segment_count === 1 ? "1 ticket (direct)" : `${rec.segment_count} separate tickets`;
  return (
    <article className="card" aria-labelledby={`rec-${rec.rank}`}>
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold tracking-wide text-muted uppercase">Option {rec.rank}</p>
          <h3 id={`rec-${rec.rank}`} className="text-lg font-semibold">
            {rec.train_name ?? "Train"} <span className="font-mono text-sm text-muted">#{rec.train_number}</span>
          </h3>
          <p className="text-sm text-muted">
            {rec.travel_class_label} ({rec.travel_class}) · {rec.quota_label} ({rec.quota}) quota ·{" "}
            {tickets}
          </p>
        </div>
        <div className="text-right">
          <span className={`inline-flex rounded-full border px-3 py-1 text-xs font-semibold ${toneClass(tone)}`}>
            {rec.status_tier_label}
          </span>
          <p className="mt-2 text-lg font-semibold">
            {rec.total_fare ? formatMoney(rec.total_fare.amount, rec.total_fare.currency) : (
              <span className="text-sm font-normal text-muted">Total fare unavailable</span>
            )}
          </p>
        </div>
      </header>

      <ol className="mt-4" aria-label="Segments">
        {rec.segments.map((segment) => (
          <SegmentRow key={segment.sequence} segment={segment} staleAfter={staleAfter} />
        ))}
      </ol>

      {rec.prediction_summary.segments_needing_estimate > 0 ? (
        <p className="mt-3 text-xs text-muted">
          Lowest provider estimate on RAC/waitlist segments:{" "}
          <span className="font-semibold text-foreground">
            {rec.prediction_summary.minimum_percentage !== null ? `${rec.prediction_summary.minimum_percentage}%` : "not available for every segment"}
          </span>
          . {rec.prediction_summary.note}
        </p>
      ) : null}

      <details className="mt-3 text-sm">
        <summary className="cursor-pointer text-muted">Why this rank?</summary>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          {rec.explanation.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </details>

      <div className="mt-4 border-t border-border pt-3">
        <button
          type="button"
          className="text-sm font-semibold text-brand underline-offset-4 hover:underline"
          aria-expanded={showSteps}
          onClick={() => setShowSteps((v) => !v)}
        >
          {showSteps ? "Hide booking steps" : "How to book this option"}
        </button>
        {showSteps ? (
          <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm">
            {rec.booking_steps.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
        ) : null}
      </div>
    </article>
  );
}

/**
 * Per-quota status. A quota that was not queried is shown as "not checked" with the opening time
 * the backend computed — never as unavailable.
 */
export function QuotaStatus({ search }: { search: JourneySearch }) {
  const summaries = search.quotas;
  const interesting = summaries.some(
    (q) => q.quota !== "GN" || !q.provider_supported || q.combinations_not_queried > 0,
  );
  if (!summaries.length || !interesting) return null;
  return (
    <section aria-labelledby="quota-status-title" className="card">
      <h2 id="quota-status-title" className="font-semibold">
        Quotas
      </h2>
      <ul className="mt-2 space-y-1 text-sm">
        {summaries.map((summary) => (
          <li key={summary.quota}>
            <span className="font-semibold">
              {summary.quota_label} ({summary.quota})
            </span>
            : {quotaSummaryText(summary)}
            {summary.queried ? ` · ${summary.recommendations} combination(s)` : ""}
          </li>
        ))}
      </ul>
      {summaries.some((q) => q.combinations_not_queried > 0 && q.provider_supported) ? (
        <p className="mt-2 text-xs text-muted">
          Quotas that are not open yet are not re-checked automatically. Use “Check again” after
          the booking window opens.
        </p>
      ) : null}
    </section>
  );
}

export function BookingGuidance({ warnings }: { warnings: string[] }) {
  return (
    <aside aria-labelledby="guidance-title" className="card border-rac/40 bg-rac-bg/60">
      <h2 id="guidance-title" className="flex items-center gap-2 font-semibold">
        <span aria-hidden="true">⚠</span> Before you book
      </h2>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">
        {warnings.map((warning) => (
          <li key={warning}>{warning}</li>
        ))}
      </ul>
      <p className="mt-3 text-sm">
        Book on an authorized platform such as the official IRCTC website or app (
        <a className="font-semibold underline" href="https://www.irctc.co.in/" target="_blank" rel="noopener noreferrer">
          irctc.co.in
        </a>
        ). RailRoute does not book tickets or handle payments.
      </p>
    </aside>
  );
}

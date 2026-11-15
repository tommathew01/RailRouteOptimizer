"use client";

import { useState } from "react";

import { AvailabilityBadge, Notice, PredictionIndicator, StaleIndicator, toneClass } from "@/components/StatusBits";
import type { JourneySearch, Recommendation, Segment } from "@/lib/api/schemas";
import { formatDayMonth, formatMoney, formatTime } from "@/lib/format";
import { COMPLETENESS_TEXT, TIER_TONE } from "@/lib/status";

export function SearchProgress({ search }: { search: JourneySearch }) {
  const coverage = search.coverage;
  const made = coverage?.availability_requests_made ?? 0;
  const budget = coverage?.request_budget ?? 0;
  const percent = budget ? Math.min(100, Math.round((made / budget) * 100)) : 0;
  return (
    <section aria-labelledby="progress-title" className="card">
      <h2 id="progress-title" className="font-semibold">
        {search.status === "QUEUED" ? "Search queued…" : "Checking segment availability…"}
      </h2>
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
        {made} of {budget} availability checks used · {coverage?.cache_hits ?? 0} served from cache ·{" "}
        {search.recommendations.length} combination(s) found so far
      </p>
    </section>
  );
}

export function CoverageNotice({ search }: { search: JourneySearch }) {
  const completeness = search.search_completeness;
  if (!completeness || !search.coverage) return null;
  const meta = COMPLETENESS_TEXT[completeness] ?? { title: completeness, tone: "info" as const };
  const c = search.coverage;
  return (
    <Notice tone={meta.tone} title={meta.title}>
      <p>
        Checked {c.segments_checked} segment(s) across {c.trains_evaluated} train(s) and{" "}
        {c.combinations_evaluated} train × class combination(s): {c.availability_requests_made} of{" "}
        {c.request_budget} provider checks used, {c.cache_hits} from cache
        {c.segments_failed ? `, ${c.segments_failed} failed` : ""}
        {c.segments_unknown ? `, ${c.segments_unknown} unclear` : ""}.
        {c.availability_requests_planned > c.availability_requests_made + c.cache_hits
          ? ` About ${c.availability_requests_planned - c.availability_requests_made - c.cache_hits} more checks were needed for full coverage.`
          : ""}
      </p>
      {completeness.startsWith("NO_PATH") ? (
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
            {rec.travel_class_label} ({rec.travel_class}) · General quota · {tickets}
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

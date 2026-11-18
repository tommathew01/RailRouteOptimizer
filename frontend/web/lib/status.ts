import type { AvailabilityStatus } from "./api/schemas";

export type Tone = "ok" | "rac" | "wl" | "na" | "unknown";

export const STATUS_META: Record<
  AvailabilityStatus,
  { label: string; tone: Tone; icon: string; description: string }
> = {
  CONFIRMED: {
    label: "Confirmed",
    tone: "ok",
    icon: "✓",
    description: "The provider reports a confirmed seat or berth for this segment.",
  },
  AVAILABLE: {
    label: "Available",
    tone: "ok",
    icon: "✓",
    description: "Seats are currently available for this segment.",
  },
  RAC: {
    label: "RAC",
    tone: "rac",
    icon: "◐",
    description: "Reservation Against Cancellation: a shared berth/seat is guaranteed.",
  },
  WAITLIST: {
    label: "Waitlist",
    tone: "wl",
    icon: "⏳",
    description: "Waitlisted: the ticket may or may not be confirmed later.",
  },
  NOT_AVAILABLE: {
    label: "Not available",
    tone: "na",
    icon: "✕",
    description: "The provider reports no availability for this segment.",
  },
  UNKNOWN: {
    label: "Unknown",
    tone: "unknown",
    icon: "?",
    description: "The provider's answer could not be interpreted.",
  },
};

export const TIER_TONE: Record<number, Tone> = { 0: "ok", 1: "rac", 2: "wl" };

export const COMPLETENESS_TEXT: Record<string, { title: string; tone: "info" | "warning" }> = {
  COMPLETE: { title: "Search complete", tone: "info" },
  PARTIAL_BUDGET: { title: "Partial search — request budget reached", tone: "warning" },
  PARTIAL_PROVIDER_ERRORS: { title: "Partial search — some checks failed", tone: "warning" },
  PARTIAL_TIMEOUT: { title: "Partial search — time limit reached", tone: "warning" },
  PARTIAL_QUOTA_NOT_QUERIED: {
    title: "Partial search — some quotas not checked yet",
    tone: "warning",
  },
  PARTIAL_STOPPED: { title: "Search stopped", tone: "info" },
  NO_PATH_FOUND: { title: "No combination found", tone: "info" },
  NO_PATH_FOUND_PARTIAL: {
    title: "No combination found in the segments checked",
    tone: "warning",
  },
};

type SearchOutcome = {
  status: string;
  search_completeness: string | null;
  incomplete_reason: string | null;
  recommendations: readonly unknown[];
};

/** The user pressed "Stop search" (docs/08 D-35). */
export function stoppedByUser(search: SearchOutcome): boolean {
  return search.incomplete_reason === "STOPPED_BY_USER";
}

function combinations(count: number): string {
  return `${count} combination${count === 1 ? "" : "s"}`;
}

/** Title of the coverage notice for a stopped search, with the real count. */
export function stoppedTitle(search: SearchOutcome): string {
  const count = search.recommendations.length;
  return count
    ? `Search stopped. Showing ${combinations(count)} found so far.`
    : "Search stopped before any combination was found.";
}

/**
 * Heading of the results list. Only a search that checked everything it planned shows "Top"
 * recommendations; partial ones never claim to be the overall best.
 */
export function resultsHeading(search: SearchOutcome): string {
  if (search.status === "QUEUED" || search.status === "RUNNING") return "Preliminary combinations";
  if (stoppedByUser(search)) return "Best combinations found before you stopped";
  const done = search.search_completeness;
  if (done === "COMPLETE" || done === "NO_PATH_FOUND") return "Top recommendations";
  return "Best combinations among the segments checked";
}

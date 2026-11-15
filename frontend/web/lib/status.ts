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
  NO_PATH_FOUND: { title: "No combination found", tone: "info" },
  NO_PATH_FOUND_PARTIAL: {
    title: "No combination found in the segments checked",
    tone: "warning",
  },
};

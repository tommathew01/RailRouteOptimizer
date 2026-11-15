/** Quota presentation helpers. Eligibility comes from the backend; nothing is computed here. */
import type { ClassEvaluation, Meta, QuotaCode, QuotaSummary } from "./api/schemas";
import { QUOTA_CODES } from "./search-params";

const IST = "Asia/Kolkata";

export const QUOTA_LABELS: Record<QuotaCode, string> = {
  GN: "General",
  TQ: "Tatkal",
};

export function quotaName(code: QuotaCode): string {
  return `${QUOTA_LABELS[code]} (${code})`;
}

/** "GN, TQ" → "General, Tatkal" for headers. */
export function quotaList(codes: readonly QuotaCode[]): string {
  return codes.map((c) => QUOTA_LABELS[c]).join(" + ");
}

const dateTimeFormatter = new Intl.DateTimeFormat("en-IN", {
  timeZone: IST,
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

/** An instant as "19 Nov 2026, 10:00 IST". */
export function formatIstDateTime(instant: string): string {
  const parts = dateTimeFormatter.formatToParts(new Date(instant));
  const get = (type: Intl.DateTimeFormatPartTypes) => parts.find((p) => p.type === type)?.value ?? "";
  return `${get("day")} ${get("month")} ${get("year")}, ${get("hour")}:${get("minute")} IST`;
}

/** Selectable quotas from /meta; General only while meta is loading or from an older backend. */
export function quotaOptions(meta: Meta | undefined): Meta["quotas"] {
  if (meta?.quotas.length) return meta.quotas;
  return [
    {
      code: "GN",
      label: "General",
      default: true,
      provider_supported: true,
      opening_rule: null,
      note: null,
    },
  ];
}

/** One-line hint describing the opening rule of the selectable windowed quotas. */
export function openingRuleHint(meta: Meta | undefined): string | null {
  const tatkal = meta?.quotas.find((q) => q.code === "TQ" && q.opening_rule);
  const rule = tatkal?.opening_rule;
  if (!rule) return null;
  const days = rule.days_before === 1 ? "1 day" : `${rule.days_before} days`;
  return (
    `Tatkal booking opens ${days} before the train leaves its origin station: ` +
    `${rule.ac_opens_at} IST for AC and ${rule.non_ac_opens_at} IST for non-AC classes. ` +
    "A quota that is not open yet is not checked."
  );
}

/** Short status of one quota in a search, never phrased as "unavailable". */
export function quotaSummaryText(summary: QuotaSummary): string {
  if (!summary.provider_supported) return "not supported by the railway data provider — not checked";
  if (summary.combinations_not_queried === 0) {
    if (summary.queried) return "checked";
    return summary.combinations_eligible === 0
      ? "not checked — no train in this search offers the selected classes"
      : "not reached within the request budget";
  }
  const opening = summary.next_opening_at
    ? `booking opens ${formatIstDateTime(summary.next_opening_at)}`
    : "booking opening time could not be determined";
  if (summary.combinations_eligible === 0) return `not checked — ${opening}`;
  return `partly checked — ${summary.combinations_not_queried} combination(s) not open yet (${opening})`;
}

export const CLASS_STATE_TEXT: Record<ClassEvaluation["state"], string> = {
  SOLVED: "best option found",
  EXHAUSTED: "fully explored",
  STOPPED: "stopped early",
  ACTIVE: "in progress",
  NOT_OFFERED: "class not offered",
  NOT_EVALUATED: "not checked",
  NOT_YET_OPEN: "not checked — booking not open yet",
  QUOTA_NOT_SUPPORTED: "not checked — quota not supported by the provider",
  NOT_QUERIED: "not checked",
};

/** Text for one train × class × quota row, including the backend's opening time. */
export function classEvaluationText(row: ClassEvaluation, showQuota: boolean): string {
  const name = showQuota ? `${row.travel_class} ${row.quota}` : row.travel_class;
  let text = CLASS_STATE_TEXT[row.state] ?? row.state;
  if (row.state === "NOT_YET_OPEN" && row.eligibility?.opens_at) {
    text = `not checked — opens ${formatIstDateTime(row.eligibility.opens_at)}`;
  } else if (row.state === "NOT_QUERIED" && row.eligibility?.state === "CLASS_CATEGORY_UNKNOWN") {
    text = "not checked — opening time unknown for this class";
  }
  return `${name}: ${text}`;
}

export { QUOTA_CODES };

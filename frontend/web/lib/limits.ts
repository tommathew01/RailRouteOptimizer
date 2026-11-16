/**
 * Client-side mirrors of the server's search limits (docs/08 D-29). The numbers always come from
 * `/api/v1/meta`; the server refuses requests above them and never truncates. Nothing here
 * silently drops a user's selection.
 */
import type { Meta } from "@/lib/api/schemas";

export type SearchLimits = Meta["limits"];

/** Can one more item be added to a selection of `size` under `limit`? (No limit known: yes.) */
export function canAdd(size: number, limit: number | undefined): boolean {
  return limit === undefined || size < limit;
}

/** Message when a selection exceeds the class limit (e.g. an old link), else null. */
export function classLimitMessage(classes: readonly string[], limit: number | undefined): string | null {
  if (limit === undefined || classes.length <= limit) return null;
  return (
    `Select at most ${limit} class${limit === 1 ? "" : "es"} per search ` +
    `(${classes.length} selected: ${classes.join(", ")}). Each class is checked separately and ` +
    "shares the same request budget."
  );
}

/** "12 combinations · budget 30 requests · about 2.5 per combination". */
export function planSummary(plan: {
  combinations: number;
  request_budget: number;
  requests_per_combination: number | null;
}): string {
  const combos = `${plan.combinations} combination${plan.combinations === 1 ? "" : "s"} to check`;
  const budget = `budget ${plan.request_budget} provider request${plan.request_budget === 1 ? "" : "s"}`;
  if (plan.requests_per_combination === null) return `${combos} · ${budget}`;
  const per = Number.isInteger(plan.requests_per_combination)
    ? String(plan.requests_per_combination)
    : plan.requests_per_combination.toFixed(1);
  return `${combos} · ${budget} · about ${per} per combination`;
}

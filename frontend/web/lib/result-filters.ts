/**
 * Client-side filters for the recommended combinations. They work on the results already
 * retrieved: no request is made, and the original list is never modified (a new array is
 * returned; recommendations keep their rank numbers).
 *
 * Categories combine with AND; within a category any selected value matches (OR). An empty
 * category does not filter.
 */
import type { Recommendation } from "@/lib/api/schemas";

export type ResultFilters = {
  classes: readonly string[];
  quotas: readonly string[];
  trains: readonly string[];
  /** Free text matched against train number and name (case-insensitive). */
  trainText: string;
};

export const NO_FILTERS: ResultFilters = { classes: [], quotas: [], trains: [], trainText: "" };

export type FilterOption = { value: string; label: string; count: number };

export type FilterOptions = {
  classes: FilterOption[];
  quotas: FilterOption[];
  trains: FilterOption[];
};

function collect(
  recommendations: readonly Recommendation[],
  key: (r: Recommendation) => string,
  label: (r: Recommendation) => string,
): FilterOption[] {
  const options = new Map<string, FilterOption>();
  for (const rec of recommendations) {
    const value = key(rec);
    const existing = options.get(value);
    if (existing) existing.count += 1;
    else options.set(value, { value, label: label(rec), count: 1 });
  }
  return [...options.values()];
}

/** The classes, quotas and trains present in the results (first-seen order = rank order). */
export function filterOptions(recommendations: readonly Recommendation[]): FilterOptions {
  return {
    classes: collect(recommendations, (r) => r.travel_class, (r) => `${r.travel_class_label} (${r.travel_class})`),
    quotas: collect(recommendations, (r) => r.quota, (r) => `${r.quota_label} (${r.quota})`),
    trains: collect(
      recommendations,
      (r) => r.train_number,
      (r) => (r.train_name ? `${r.train_number} · ${r.train_name}` : r.train_number),
    ),
  };
}

function trainMatchesText(rec: Recommendation, text: string): boolean {
  const needle = text.trim().toLowerCase();
  if (!needle) return true;
  return (
    rec.train_number.toLowerCase().includes(needle) ||
    (rec.train_name ?? "").toLowerCase().includes(needle)
  );
}

export function applyFilters(
  recommendations: readonly Recommendation[],
  filters: ResultFilters,
): Recommendation[] {
  return recommendations.filter(
    (rec) =>
      (filters.classes.length === 0 || filters.classes.includes(rec.travel_class)) &&
      (filters.quotas.length === 0 || filters.quotas.includes(rec.quota)) &&
      (filters.trains.length === 0 || filters.trains.includes(rec.train_number)) &&
      trainMatchesText(rec, filters.trainText),
  );
}

export function isFiltering(filters: ResultFilters): boolean {
  return (
    filters.classes.length > 0 ||
    filters.quotas.length > 0 ||
    filters.trains.length > 0 ||
    filters.trainText.trim() !== ""
  );
}

/** Toggle one value in a category, returning new filters (the input is not changed). */
export function toggleValue(
  filters: ResultFilters,
  category: "classes" | "quotas" | "trains",
  value: string,
): ResultFilters {
  const current = filters[category];
  const next = current.includes(value) ? current.filter((v) => v !== value) : [...current, value];
  return { ...filters, [category]: next };
}

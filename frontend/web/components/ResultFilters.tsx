"use client";

import { useId, type ReactNode } from "react";

import {
  isFiltering,
  NO_FILTERS,
  toggleValue,
  type FilterOption,
  type FilterOptions,
  type ResultFilters,
} from "@/lib/result-filters";

type Category = "classes" | "quotas" | "trains";

function ChipGroup({
  legend,
  category,
  options,
  filters,
  onChange,
  children,
}: {
  legend: string;
  category: Category;
  options: FilterOption[];
  filters: ResultFilters;
  onChange: (next: ResultFilters) => void;
  children?: ReactNode;
}) {
  const labelId = useId();
  const selected = filters[category];
  const clearable = selected.length > 0 || (category === "trains" && filters.trainText !== "");
  return (
    <fieldset className="min-w-0" aria-labelledby={labelId}>
      <div className="mb-1 flex items-center justify-between gap-2">
        <span id={labelId} className="text-sm font-semibold">
          {legend}
        </span>
        {clearable ? (
          <button
            type="button"
            className="text-xs font-semibold text-brand underline-offset-4 hover:underline"
            onClick={() =>
              onChange({
                ...filters,
                [category]: [],
                ...(category === "trains" ? { trainText: "" } : {}),
              })
            }
          >
            Clear {legend.toLowerCase()}
          </button>
        ) : null}
      </div>
      {children}
      <div className="flex flex-wrap gap-2">
        {options.map((option) => {
          const checked = selected.includes(option.value);
          return (
            <label
              key={option.value}
              className={`inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-full border px-3 text-sm transition-colors ${checked ? "border-brand bg-brand text-brand-contrast" : "border-border bg-surface hover:bg-surface-muted"}`}
            >
              <input
                type="checkbox"
                className="sr-only"
                checked={checked}
                onChange={() => onChange(toggleValue(filters, category, option.value))}
              />
              <span aria-hidden="true">{checked ? "✓" : "+"}</span>
              <span>{option.label}</span>
              <span className={checked ? "text-xs" : "text-xs text-muted"}>({option.count})</span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

/**
 * Filters for the combinations already on screen. Groups with a single value are omitted
 * (nothing to choose); the panel is omitted when no group has two values.
 */
export function ResultFiltersPanel({
  options,
  filters,
  onChange,
  shown,
  total,
}: {
  options: FilterOptions;
  filters: ResultFilters;
  onChange: (next: ResultFilters) => void;
  shown: number;
  total: number;
}) {
  const searchId = useId();
  const showClasses = options.classes.length > 1;
  const showQuotas = options.quotas.length > 1;
  const showTrains = options.trains.length > 1;
  if (!showClasses && !showQuotas && !showTrains) return null;
  const active = isFiltering(filters);
  return (
    <section aria-labelledby="filters-title" className="card space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="filters-title" className="font-semibold">
          Filter combinations
        </h2>
        <p className="text-sm text-muted" aria-live="polite">
          {active ? `Showing ${shown} of ${total}` : `${total} combination${total === 1 ? "" : "s"}`}
          {active ? (
            <button
              type="button"
              className="ml-3 font-semibold text-brand underline-offset-4 hover:underline"
              onClick={() => onChange(NO_FILTERS)}
            >
              Reset all filters
            </button>
          ) : null}
        </p>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        {showClasses ? (
          <ChipGroup legend="Class" category="classes" options={options.classes} filters={filters} onChange={onChange} />
        ) : null}
        {showQuotas ? (
          <ChipGroup legend="Quota" category="quotas" options={options.quotas} filters={filters} onChange={onChange} />
        ) : null}
      </div>
      {showTrains ? (
        <ChipGroup legend="Train" category="trains" options={options.trains} filters={filters} onChange={onChange}>
          <label htmlFor={searchId} className="sr-only">
            Search trains by number or name
          </label>
          <input
            id={searchId}
            type="search"
            className="field-input mb-2"
            placeholder="Search train number or name"
            value={filters.trainText}
            onChange={(event) => onChange({ ...filters, trainText: event.target.value })}
          />
        </ChipGroup>
      ) : null}
    </section>
  );
}

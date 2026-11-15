"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { StationAutocomplete, type StationValue } from "@/components/StationAutocomplete";
import { metaQuery } from "@/lib/api/queries";
import { istDate } from "@/lib/format";
import { openingRuleHint, quotaOptions } from "@/lib/quotas";
import { canonicalQuotas, journeyQueryString } from "@/lib/search-params";
import { useNow } from "@/lib/use-now";

type Errors = Partial<Record<"from" | "to" | "date" | "classes" | "quotas", string>>;

export type JourneyFormInitial = {
  from?: StationValue | null;
  to?: StationValue | null;
  date?: string;
  classes?: string[];
  quotas?: string[];
  allowRac?: boolean;
  allowWaitlist?: boolean;
};

export function JourneySearchForm({ initial }: { initial?: JourneyFormInitial }) {
  const router = useRouter();
  const { data: meta, isError: metaError } = useQuery(metaQuery);
  const now = useNow(60_000);

  const [from, setFrom] = useState<StationValue | null>(initial?.from ?? null);
  const [to, setTo] = useState<StationValue | null>(initial?.to ?? null);
  const [date, setDate] = useState(initial?.date ?? "");
  const [classes, setClasses] = useState<string[]>(initial?.classes ?? ["3A"]);
  const [quotas, setQuotas] = useState<string[]>(initial?.quotas ?? ["GN"]);
  const [allowRac, setAllowRac] = useState(initial?.allowRac ?? false);
  const [allowWaitlist, setAllowWaitlist] = useState(initial?.allowWaitlist ?? false);
  const [errors, setErrors] = useState<Errors>({});

  const minDate = now !== null ? istDate(now) : undefined;
  const maxDate =
    now !== null && meta ? istDate(now, meta.limits.max_advance_booking_days) : undefined;
  const minLength = meta?.station_search_min_query_length ?? 3;

  function toggleClass(code: string) {
    setClasses((current) =>
      current.includes(code) ? current.filter((c) => c !== code) : [...current, code],
    );
  }

  function toggleQuota(code: string) {
    setQuotas((current) =>
      current.includes(code) ? current.filter((c) => c !== code) : [...current, code],
    );
  }

  const quotaChoices = quotaOptions(meta);
  const unsupported = new Set(
    quotaChoices.filter((q) => !q.provider_supported).map((q) => q.code as string),
  );
  const selectedQuotas = canonicalQuotas(quotas.filter((q) => !unsupported.has(q)));
  const ruleHint = openingRuleHint(meta);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const next: Errors = {};
    if (!from) next.from = "Choose a station from the list.";
    if (!to) next.to = "Choose a station from the list.";
    if (from && to && from.code === to.code) next.to = "Destination must differ from source.";
    if (!date) next.date = "Choose a journey date.";
    else if ((minDate && date < minDate) || (maxDate && date > maxDate))
      next.date = "Date is outside the reservation window.";
    if (classes.length === 0) next.classes = "Select at least one class.";
    if (selectedQuotas.length === 0) next.quotas = "Select at least one quota.";
    setErrors(next);
    if (Object.keys(next).length || !from || !to) return;
    const query = journeyQueryString({
      from: from.code,
      to: to.code,
      date,
      classes,
      quotas: selectedQuotas,
      rac: allowRac,
      wl: allowWaitlist,
    });
    const names = new URLSearchParams({ fromName: from.name, toName: to.name });
    router.push(`/search?${query}&${names.toString()}`);
  }

  return (
    <form onSubmit={submit} noValidate className="card space-y-5" aria-label="Journey search">
      <div className="grid gap-4 md:grid-cols-[1fr_auto_1fr] md:items-start">
        <StationAutocomplete
          label="From"
          value={from}
          onChange={setFrom}
          minLength={minLength}
          error={errors.from}
          placeholder="e.g. Tirur or TIR"
        />
        <button
          type="button"
          className="btn btn-secondary self-center md:mt-6"
          onClick={() => {
            setFrom(to);
            setTo(from);
          }}
          aria-label="Swap source and destination"
        >
          <span aria-hidden="true">⇄</span>
          <span className="md:sr-only">Swap</span>
        </button>
        <StationAutocomplete
          label="To"
          value={to}
          onChange={setTo}
          minLength={minLength}
          error={errors.to}
          placeholder="e.g. Thiruvananthapuram or TVC"
        />
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label htmlFor="journey-date" className="field-label">
            Journey date <span className="font-normal text-muted">(departure from source, IST)</span>
          </label>
          <input
            id="journey-date"
            type="date"
            className="field-input"
            value={date}
            min={minDate}
            max={maxDate}
            onChange={(event) => setDate(event.target.value)}
            aria-invalid={errors.date ? true : undefined}
            aria-describedby={errors.date ? "journey-date-error" : undefined}
          />
          {errors.date ? (
            <p id="journey-date-error" className="field-error">
              {errors.date}
            </p>
          ) : null}
        </div>
        <fieldset aria-describedby={errors.quotas ? "quotas-error" : "quotas-hint"}>
          <legend className="field-label">Quota</legend>
          <div className="flex flex-wrap gap-2">
            {quotaChoices.map((option) => {
              const disabled = !option.provider_supported;
              const checked = !disabled && quotas.includes(option.code);
              return (
                <label
                  key={option.code}
                  className={`inline-flex min-h-11 items-center gap-2 rounded-full border px-3 text-sm transition-colors ${disabled ? "cursor-not-allowed border-border bg-surface-muted text-muted" : checked ? "cursor-pointer border-brand bg-brand text-brand-contrast" : "cursor-pointer border-border bg-surface hover:bg-surface-muted"}`}
                >
                  <input
                    type="checkbox"
                    className="sr-only"
                    checked={checked}
                    disabled={disabled}
                    onChange={() => toggleQuota(option.code)}
                  />
                  <span aria-hidden="true">{disabled ? "–" : checked ? "✓" : "+"}</span>
                  <span>
                    {option.label} <span className="font-semibold">({option.code})</span>
                  </span>
                  {disabled ? <span className="text-xs">not supported</span> : null}
                </label>
              );
            })}
          </div>
          <p id="quotas-hint" className="mt-1 text-xs text-muted">
            Each quota is searched separately; one recommendation never mixes quotas.
            {ruleHint ? ` ${ruleHint}` : ""}
          </p>
          {errors.quotas ? (
            <p id="quotas-error" className="field-error">
              {errors.quotas}
            </p>
          ) : null}
        </fieldset>
      </div>

      <fieldset aria-describedby={errors.classes ? "classes-error" : "classes-hint"}>
        <legend className="field-label">Classes</legend>
        <p id="classes-hint" className="mb-2 text-xs text-muted">
          Each class is searched separately; one recommendation never mixes classes.
        </p>
        <div className="flex flex-wrap gap-2">
          {(meta?.supported_classes ?? []).map((option) => {
            const checked = classes.includes(option.code);
            return (
              <label
                key={option.code}
                className={`inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-full border px-3 text-sm transition-colors ${checked ? "border-brand bg-brand text-brand-contrast" : "border-border bg-surface hover:bg-surface-muted"}`}
              >
                <input
                  type="checkbox"
                  className="sr-only"
                  checked={checked}
                  onChange={() => toggleClass(option.code)}
                />
                <span aria-hidden="true">{checked ? "✓" : "+"}</span>
                <span className="font-semibold">{option.code}</span>
                <span className="hidden sm:inline">{option.label}</span>
              </label>
            );
          })}
          {metaError ? <p className="text-sm text-danger">Could not load classes.</p> : null}
        </div>
        {errors.classes ? (
          <p id="classes-error" className="field-error">
            {errors.classes}
          </p>
        ) : null}
      </fieldset>

      <fieldset>
        <legend className="field-label">Also accept</legend>
        <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
          <label className="inline-flex min-h-11 items-center gap-2">
            <input type="checkbox" checked={allowRac} onChange={(e) => setAllowRac(e.target.checked)} className="h-5 w-5 accent-[var(--brand)]" />
            RAC segments
          </label>
          <label className="inline-flex min-h-11 items-center gap-2">
            <input type="checkbox" checked={allowWaitlist} onChange={(e) => setAllowWaitlist(e.target.checked)} className="h-5 w-5 accent-[var(--brand)]" />
            Waitlisted segments
          </label>
        </div>
        <p className="text-xs text-muted">
          By default only confirmed or available segments are recommended.
        </p>
      </fieldset>

      <button type="submit" className="btn btn-primary w-full sm:w-auto">
        Find trains
      </button>
    </form>
  );
}

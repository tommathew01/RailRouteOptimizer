"use client";

import { useId, useState, type ReactNode } from "react";

import type { AvailabilityStatus, Prediction } from "@/lib/api/schemas";
import { formatAge } from "@/lib/format";
import { STATUS_META, type Tone } from "@/lib/status";
import { useNow } from "@/lib/use-now";

const TONE_CLASS: Record<Tone, string> = {
  ok: "bg-ok-bg text-ok border-ok/30",
  rac: "bg-rac-bg text-rac border-rac/30",
  wl: "bg-wl-bg text-wl border-wl/30",
  na: "bg-na-bg text-na border-na/30",
  unknown: "bg-na-bg text-na border-na/30",
};

export function toneClass(tone: Tone): string {
  return TONE_CLASS[tone];
}

/** Current availability: icon + text, never colour alone. */
export function AvailabilityBadge({
  status,
  text,
}: {
  status: AvailabilityStatus;
  text: string | null;
}) {
  const meta = STATUS_META[status];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold ${TONE_CLASS[meta.tone]}`}
      title={meta.description}
    >
      <span aria-hidden="true">{meta.icon}</span>
      <span>{meta.label}</span>
      {text && text.toUpperCase() !== meta.label.toUpperCase() ? (
        <span className="font-mono font-medium opacity-90">· {text}</span>
      ) : null}
    </span>
  );
}

/** Provider estimate, clearly attributed and never presented as a guarantee. */
export function PredictionIndicator({ prediction }: { prediction: Prediction | null }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  if (!prediction) {
    return <span className="text-xs text-muted">No provider estimate</span>;
  }
  const value =
    prediction.percentage !== null ? `${prediction.percentage}%` : (prediction.text ?? "—");
  return (
    <span className="relative inline-flex items-center gap-1.5 text-xs">
      <span className="text-muted">{prediction.label}:</span>
      <span className="font-semibold">{value}</span>
      <button
        type="button"
        className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-border text-[11px] text-muted hover:bg-surface-muted"
        aria-expanded={open}
        aria-controls={id}
        aria-label={`About the ${prediction.label}`}
        onClick={() => setOpen((v) => !v)}
      >
        i
      </button>
      {open ? (
        <span
          id={id}
          role="note"
          className="absolute top-6 left-0 z-10 w-64 rounded-lg border border-border bg-surface p-3 text-xs leading-relaxed text-foreground shadow-lg"
        >
          {prediction.provider === "RAILKIT"
            ? "Estimate supplied by RailKit"
            : "Simulated estimate (demo data)"}
          {prediction.text ? <> — “{prediction.text}”</> : null}. It is not a guarantee and does
          not change the current status shown above.
        </span>
      ) : null}
    </span>
  );
}

export function StaleIndicator({ checkedAt, staleAfterSeconds }: { checkedAt: string; staleAfterSeconds: number }) {
  const now = useNow(15_000);
  if (now === null) return null;
  const ageSeconds = (now - new Date(checkedAt).getTime()) / 1000;
  const stale = ageSeconds > staleAfterSeconds;
  return (
    <span className={`text-xs ${stale ? "font-semibold text-wl" : "text-muted"}`}>
      {stale ? "⚠ " : ""}Checked {formatAge(checkedAt, now)}
      {stale ? " — may be out of date" : ""}
    </span>
  );
}

export function Notice({
  tone,
  title,
  children,
}: {
  tone: "info" | "warning" | "danger";
  title: string;
  children?: ReactNode;
}) {
  const palette = {
    info: "border-info/30 bg-info-bg text-info",
    warning: "border-rac/40 bg-rac-bg text-rac",
    danger: "border-danger/40 bg-danger-bg text-danger",
  }[tone];
  const icon = { info: "ℹ", warning: "⚠", danger: "✕" }[tone];
  return (
    <div role={tone === "danger" ? "alert" : "status"} className={`rounded-xl border p-4 ${palette}`}>
      <p className="flex items-start gap-2 font-semibold">
        <span aria-hidden="true">{icon}</span>
        <span>{title}</span>
      </p>
      {children ? <div className="mt-1 pl-6 text-sm text-foreground">{children}</div> : null}
    </div>
  );
}

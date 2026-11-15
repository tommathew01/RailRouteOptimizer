/** Formatting helpers. Railway times are always shown in Asia/Kolkata (IST). */

const IST = "Asia/Kolkata";

const dateFormatter = new Intl.DateTimeFormat("en-IN", {
  timeZone: IST,
  weekday: "short",
  day: "numeric",
  month: "short",
  year: "numeric",
});
const timeFormatter = new Intl.DateTimeFormat("en-IN", {
  timeZone: IST,
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});
const shortDateFormatter = new Intl.DateTimeFormat("en-IN", {
  timeZone: IST,
  day: "numeric",
  month: "short",
});

/** "2026-11-20" (a calendar date, not an instant) → "Fri, 20 Nov 2026". */
export function formatCalendarDate(isoDate: string): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  if (!year || !month || !day) return isoDate;
  // Noon UTC keeps the same calendar day in IST; parts keep the output locale-data independent.
  const parts = dateFormatter.formatToParts(new Date(Date.UTC(year, month - 1, day, 12)));
  const get = (type: Intl.DateTimeFormatPartTypes) => parts.find((p) => p.type === type)?.value ?? "";
  return `${get("weekday")}, ${get("day")} ${get("month")} ${get("year")}`;
}

export function formatTime(instant: string | null): string {
  return instant ? timeFormatter.format(new Date(instant)) : "—";
}

export function formatDayMonth(instant: string | null): string {
  return instant ? shortDateFormatter.format(new Date(instant)) : "";
}

export function formatDuration(minutes: number | null): string {
  if (minutes === null || minutes < 0) return "—";
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h ? `${h}h ${m.toString().padStart(2, "0")}m` : `${m}m`;
}

export function formatMoney(amount: string, currency: string): string {
  const value = Number(amount);
  if (!Number.isFinite(value)) return `${currency} ${amount}`;
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency,
    maximumFractionDigits: value % 1 === 0 ? 0 : 2,
  }).format(value);
}

export function formatAge(fromIso: string, nowMs: number): string {
  const seconds = Math.max(0, Math.round((nowMs - new Date(fromIso).getTime()) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  return `${hours} h ago`;
}

/** Today's calendar date in IST as YYYY-MM-DD, plus an offset in days. */
export function istDate(nowMs: number, addDays = 0): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: IST,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(nowMs + addDays * 86_400_000));
  return parts; // en-CA formats as YYYY-MM-DD
}

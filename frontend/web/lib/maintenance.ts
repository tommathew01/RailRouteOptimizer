/**
 * Daily IRCTC maintenance window (docs/08 D-31), mirrored from `/api/v1/meta`. The server is
 * authoritative and refuses railway requests inside the window; this only explains it early.
 *
 * Timezone independence: `Date.now()` is an absolute instant (UTC milliseconds), whatever the
 * device's timezone. India Standard Time is a fixed UTC+05:30 with no daylight saving, so the IST
 * wall-clock minute is plain arithmetic on that instant — no timezone database is needed.
 */
import type { Meta } from "@/lib/api/schemas";

export type MaintenanceWindow = NonNullable<Meta["railway_maintenance"]>;

const IST_OFFSET_MINUTES = 5 * 60 + 30;
const MINUTES_PER_DAY = 24 * 60;

/** Minute of the day (0–1439) in IST for an absolute instant. */
export function istMinuteOfDay(nowMs: number): number {
  const minutes = Math.floor(nowMs / 60_000) + IST_OFFSET_MINUTES;
  return ((minutes % MINUTES_PER_DAY) + MINUTES_PER_DAY) % MINUTES_PER_DAY;
}

function parseClock(value: string): number | null {
  const match = /^(\d{2}):(\d{2})$/.exec(value);
  if (!match) return null;
  return Number(match[1]) * 60 + Number(match[2]);
}

/** Inside [starts_at, ends_at) IST? The window may cross midnight (23:45 → 00:20). */
export function inMaintenanceWindow(nowMs: number, window: MaintenanceWindow | undefined): boolean {
  if (!window?.enabled) return false;
  const start = parseClock(window.starts_at);
  const end = parseClock(window.ends_at);
  if (start === null || end === null || start === end) return false;
  const now = istMinuteOfDay(nowMs);
  return start < end ? now >= start && now < end : now >= start || now < end;
}

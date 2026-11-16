"use client";

import { useQuery } from "@tanstack/react-query";

import { metaQuery } from "@/lib/api/queries";
import { inMaintenanceWindow, type MaintenanceWindow } from "@/lib/maintenance";
import { useNow } from "@/lib/use-now";

/**
 * Whether new railway requests are blocked right now. Re-evaluated every 10 s, so the page
 * unlocks by itself when the window ends (no refresh needed).
 *
 * `ready` is false until the device clock and the server's window are known (or `/meta` failed):
 * automatic railway requests wait for it, so a page opened inside the window sends nothing. The
 * server refuses railway requests inside the window in any case.
 */
export function useRailwayMaintenance(): {
  ready: boolean;
  active: boolean;
  /** True when automatic railway requests may run now (`ready && !active`). */
  open: boolean;
  maintenance: MaintenanceWindow | undefined;
} {
  const { data: meta, isError } = useQuery(metaQuery);
  const now = useNow(10_000);
  const maintenance = meta?.railway_maintenance;
  const ready = now !== null && (meta !== undefined || isError);
  const active = now !== null && inMaintenanceWindow(now, maintenance);
  return { ready, active, open: ready && !active, maintenance };
}

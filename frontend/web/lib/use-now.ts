"use client";

import { useSyncExternalStore } from "react";

/**
 * Current time, refreshed every `intervalMs`. Returns `null` on the server and during hydration,
 * so prerendering (Cache Components) never reads the clock.
 */
export function useNow(intervalMs = 30_000): number | null {
  return useSyncExternalStore(
    (onChange) => {
      const id = window.setInterval(onChange, intervalMs);
      return () => window.clearInterval(id);
    },
    () => Math.floor(Date.now() / intervalMs) * intervalMs,
    () => null,
  );
}

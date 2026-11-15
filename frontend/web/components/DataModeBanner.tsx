"use client";

import { useQuery } from "@tanstack/react-query";

import { metaQuery } from "@/lib/api/queries";

/**
 * Makes demo (mock-provider) mode impossible to miss. Live mode shows nothing extra.
 * If the API is unreachable the banner says so instead of silently showing nothing.
 */
export function DataModeBanner() {
  const { data, isError } = useQuery(metaQuery);

  if (isError) {
    return (
      <div role="status" className="banner banner-warning">
        <strong>Service unavailable.</strong> The RailRoute API cannot be reached right now.
      </div>
    );
  }
  if (data?.data_mode !== "DEMO") return null;
  return (
    <div role="status" className="banner banner-demo">
      <strong>Demo mode</strong> — trains and availability are simulated mock data, not live
      railway information.
    </div>
  );
}

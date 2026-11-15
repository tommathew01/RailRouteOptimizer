import type { Train } from "./api/schemas";
import { journeyQueryString, type JourneyQueryInput } from "./search-params";

export type StationPair = {
  from: string;
  to: string;
  fromName: string | null;
  toName: string | null;
  trains: number;
  href: string;
};

/** Search link for the same journey between other stations (names are display-only). */
export function pairSearchHref(
  query: JourneyQueryInput,
  from: string,
  to: string,
  fromName: string | null,
  toName: string | null,
): string {
  const names = new URLSearchParams();
  if (fromName) names.set("fromName", fromName);
  if (toName) names.set("toName", toName);
  const suffix = names.toString();
  return `/search?${journeyQueryString({ ...query, from, to })}${suffix ? `&${suffix}` : ""}`;
}

/**
 * RailKit matches station clusters (searching NDLS also returns trains boarding at NZM or DEE).
 * Recommendations must start and end at the requested stations, so trains that use other
 * stations are offered as a new search for their own station pair instead.
 */
export function nearbyStationPairs(trains: Train[], query: JourneyQueryInput): StationPair[] {
  const pairs = new Map<string, StationPair>();
  for (const train of trains) {
    if (train.serves_requested_stations) continue;
    const key = `${train.boards_at}-${train.alights_at}`;
    const existing = pairs.get(key);
    if (existing) {
      existing.trains += 1;
      continue;
    }
    pairs.set(key, {
      from: train.boards_at,
      to: train.alights_at,
      fromName: train.boards_at_name,
      toName: train.alights_at_name,
      trains: 1,
      href: pairSearchHref(query, train.boards_at, train.alights_at, train.boards_at_name, train.alights_at_name),
    });
  }
  return [...pairs.values()].sort((a, b) => b.trains - a.trains || a.from.localeCompare(b.from) || a.to.localeCompare(b.to));
}

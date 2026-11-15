import { describe, expect, it } from "vitest";

import type { Train } from "@/lib/api/schemas";
import { nearbyStationPairs } from "@/lib/station-pairs";

const QUERY = { from: "NDLS", to: "BCT", date: "2026-11-28", classes: ["3A"], rac: true, wl: false };

function train(number: string, boards: string, alights: string, exact = false): Train {
  return {
    train_number: number,
    train_name: null,
    boards_at: boards,
    boards_at_name: boards === "NZM" ? "Hazrat Nizamuddin" : null,
    alights_at: alights,
    alights_at_name: alights === "BDTS" ? "Bandra Terminus" : null,
    serves_requested_stations: exact,
    departure_time: null,
    arrival_time: null,
    duration_minutes: null,
    running_days: null,
    origin_station_code: null,
    terminus_station_code: null,
    distance_km: null,
    halts: null,
  };
}

describe("nearbyStationPairs", () => {
  it("groups trains that use other stations by pair, most trains first", () => {
    const pairs = nearbyStationPairs(
      [
        train("12904", "NZM", "BDTS"),
        train("12138", "NDLS", "CSMT"),
        train("12248", "NZM", "BDTS"),
        train("12951", "NDLS", "BCT", true),
      ],
      QUERY,
    );
    expect(pairs.map((p) => [p.from, p.to, p.trains])).toEqual([
      ["NZM", "BDTS", 2],
      ["NDLS", "CSMT", 1],
    ]);
  });

  it("links to a new search for that pair, keeping date, classes and filters", () => {
    const [pair] = nearbyStationPairs([train("12904", "NZM", "BDTS")], QUERY);
    const url = new URL(pair.href, "http://x");
    expect(url.pathname).toBe("/search");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      from: "NZM",
      to: "BDTS",
      date: "2026-11-28",
      classes: "3A",
      rac: "1",
      wl: "0",
      fromName: "Hazrat Nizamuddin",
      toName: "Bandra Terminus",
    });
  });

  it("returns nothing when every train serves the requested stations", () => {
    expect(nearbyStationPairs([train("12951", "NDLS", "BCT", true)], QUERY)).toEqual([]);
  });
});

import { queryOptions } from "@tanstack/react-query";

import { apiRequest } from "./client";
import {
  JourneySearchSchema,
  MetaSchema,
  OptimizeResultSchema,
  StationSearchResponseSchema,
  TrainRouteResponseSchema,
  TrainSearchResponseSchema,
  type JourneySearch,
} from "./schemas";

export const metaQuery = queryOptions({
  queryKey: ["meta"] as const,
  queryFn: ({ signal }) => apiRequest("/meta", { schema: MetaSchema, signal }),
  staleTime: 5 * 60_000,
});

export const stationSearchQuery = (q: string) =>
  queryOptions({
    queryKey: ["stations", q.trim().toLowerCase()] as const,
    queryFn: ({ signal }) =>
      apiRequest(`/stations/search?q=${encodeURIComponent(q.trim())}`, {
        schema: StationSearchResponseSchema,
        signal,
      }),
    staleTime: 60 * 60_000,
  });

export type TrainSearchInput = { source: string; destination: string; journey_date: string };

export const trainSearchQuery = (input: TrainSearchInput) =>
  queryOptions({
    queryKey: ["trains", input.source, input.destination, input.journey_date] as const,
    queryFn: ({ signal }) =>
      apiRequest("/trains/search", {
        method: "POST",
        body: input,
        schema: TrainSearchResponseSchema,
        signal,
      }),
    staleTime: 10 * 60_000,
  });

export const trainRouteQuery = (trainNumber: string) =>
  queryOptions({
    queryKey: ["route", trainNumber] as const,
    queryFn: ({ signal }) =>
      apiRequest(`/trains/${encodeURIComponent(trainNumber)}/route`, {
        schema: TrainRouteResponseSchema,
        signal,
      }),
    staleTime: 60 * 60_000,
  });

const ACTIVE_POLL_MS = 1_500;

export const journeySearchQuery = (searchId: string) =>
  queryOptions({
    queryKey: ["journey", searchId] as const,
    queryFn: ({ signal }) =>
      apiRequest(`/journeys/${encodeURIComponent(searchId)}`, {
        schema: JourneySearchSchema,
        signal,
      }),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "QUEUED" || status === "RUNNING" ? ACTIVE_POLL_MS : false;
    },
    staleTime: 0,
  });

export type OptimizeInput = {
  source: string;
  destination: string;
  journey_date: string;
  classes: string[];
  filters: { allow_rac: boolean; allow_waitlist: boolean };
  train_numbers?: string[];
};

export async function startOptimization(input: OptimizeInput): Promise<{
  searchId: string;
  completed: JourneySearch | null;
}> {
  const result = await apiRequest("/journeys/optimize", {
    method: "POST",
    body: input,
    schema: OptimizeResultSchema,
  });
  const completed = "request" in result ? result : null;
  return { searchId: result.search_id, completed };
}

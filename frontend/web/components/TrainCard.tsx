"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useId, useState } from "react";

import { trainRouteQuery } from "@/lib/api/queries";
import type { Train } from "@/lib/api/schemas";
import { formatDuration } from "@/lib/format";

export function RouteTimeline({
  trainNumber,
  highlight,
}: {
  trainNumber: string;
  highlight: [string, string];
}) {
  const { data, isPending, isError } = useQuery(trainRouteQuery(trainNumber));
  if (isPending) return <p className="text-sm text-muted">Loading route…</p>;
  if (isError || !data) return <p className="text-sm text-danger">Route unavailable.</p>;
  const from = data.stops.findIndex((s) => s.station_code === highlight[0]);
  const to = data.stops.findIndex((s) => s.station_code === highlight[1]);
  return (
    <div>
      {!data.route_verified ? (
        <p className="mb-2 text-sm font-semibold text-wl">
          ⚠ Route could not be verified ({data.issues.join(", ")}); no recommendations will use it.
        </p>
      ) : null}
      <ol className="relative ml-2 border-l-2 border-border">
        {data.stops.map((stop, index) => {
          const inJourney = from >= 0 && to >= 0 && index >= from && index <= to;
          const endpoint = index === from || index === to;
          return (
            <li key={stop.sequence} className={`relative py-1 pl-5 text-sm ${inJourney ? "" : "text-muted"}`}>
              <span
                aria-hidden="true"
                className={`absolute top-2.5 -left-[7px] h-3 w-3 rounded-full border-2 ${endpoint ? "border-brand bg-brand" : inJourney ? "border-brand bg-surface" : "border-border bg-surface"}`}
              />
              <span className={endpoint ? "font-semibold" : ""}>
                {stop.station_name ?? stop.station_code}{" "}
                <span className="font-mono text-xs">({stop.station_code})</span>
              </span>
              <span className="ml-2 text-xs text-muted">
                {stop.arrival ? `arr ${stop.arrival}` : "starts"} ·{" "}
                {stop.departure ? `dep ${stop.departure}` : "ends"}
                {stop.day_offset ? ` · day ${stop.day_offset + 1}` : ""}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

export function TrainCard({
  train,
  selected,
  onToggle,
  route,
  alternativeHref,
}: {
  train: Train;
  selected: boolean;
  onToggle: () => void;
  route: [string, string];
  alternativeHref?: string;
}) {
  const [showRoute, setShowRoute] = useState(false);
  const routeId = useId();
  return (
    <article className={`card transition-colors ${selected ? "border-brand" : ""}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <label className="flex min-h-11 cursor-pointer items-start gap-3">
          <input
            type="checkbox"
            checked={selected}
            onChange={onToggle}
            disabled={!train.serves_requested_stations}
            className="mt-1 h-5 w-5 accent-[var(--brand)]"
            aria-describedby={`${routeId}-summary`}
          />
          <span>
            <span className="block text-base font-semibold">
              {train.train_name ?? "Train"} <span className="font-mono text-sm text-muted">#{train.train_number}</span>
            </span>
            <span id={`${routeId}-summary`} className="block text-sm text-muted">
              {train.boards_at} {train.departure_time ?? "—"} → {train.alights_at}{" "}
              {train.arrival_time ?? "—"} · {formatDuration(train.duration_minutes)}
              {train.halts !== null ? ` · ${train.halts} stops between` : ""}
            </span>
          </span>
        </label>
        <button
          type="button"
          className="btn btn-secondary"
          aria-expanded={showRoute}
          aria-controls={routeId}
          onClick={() => setShowRoute((v) => !v)}
        >
          {showRoute ? "Hide route" : "View route"}
        </button>
      </div>
      {!train.serves_requested_stations ? (
        <p className="mt-2 text-sm text-wl">
          ⚠ Runs {train.boards_at} → {train.alights_at}, not your exact stations, so it cannot be
          used in this search.{" "}
          {alternativeHref ? (
            <Link href={alternativeHref} className="font-semibold underline underline-offset-4">
              Search {train.boards_at} → {train.alights_at} instead
            </Link>
          ) : null}
        </p>
      ) : null}
      <div id={routeId} hidden={!showRoute} className="mt-4">
        {showRoute ? <RouteTimeline trainNumber={train.train_number} highlight={route} /> : null}
      </div>
    </article>
  );
}

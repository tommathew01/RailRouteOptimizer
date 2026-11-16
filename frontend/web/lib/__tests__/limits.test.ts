import { describe, expect, it } from "vitest";

import { canAdd, classLimitMessage, defaultTrainSelection, planSummary } from "@/lib/limits";

const limits = {
  max_segments: 4,
  max_trains_per_search: 5,
  default_trains_selected: 3,
  max_classes_per_search: 3,
  max_availability_requests_per_search: 30,
  max_advance_booking_days: 60,
};

describe("search limits (mirrored from /meta, never hard-coded)", () => {
  it("pre-selects the configured default, not the maximum", () => {
    const trains = ["1", "2", "3", "4", "5", "6"];
    expect([...defaultTrainSelection(trains, limits)]).toEqual(["1", "2", "3"]);
    expect([...defaultTrainSelection(["1", "2"], limits)]).toEqual(["1", "2"]);
    expect(
      [...defaultTrainSelection(trains, { ...limits, default_trains_selected: 9 })],
    ).toHaveLength(5);
  });

  it("waits for the server's limits instead of guessing", () => {
    expect(defaultTrainSelection(["1", "2"], undefined).size).toBe(0);
    expect(canAdd(99, undefined)).toBe(true); // the server stays authoritative
  });

  it("stops adding at the limit", () => {
    expect(canAdd(2, 3)).toBe(true);
    expect(canAdd(3, 3)).toBe(false);
  });

  it("explains an over-limit class selection without dropping any class", () => {
    expect(classLimitMessage(["3A", "SL"], 3)).toBeNull();
    const message = classLimitMessage(["1A", "2A", "3A", "SL"], 3);
    expect(message).toContain("at most 3 classes");
    expect(message).toContain("1A, 2A, 3A, SL");
    expect(classLimitMessage(["1A", "2A", "3A", "SL"], undefined)).toBeNull();
  });

  it("summarizes combinations against the budget", () => {
    expect(planSummary({ combinations: 12, request_budget: 30, requests_per_combination: 2.5 })).toBe(
      "12 combinations to check · budget 30 provider requests · about 2.5 per combination",
    );
    expect(planSummary({ combinations: 1, request_budget: 30, requests_per_combination: 30 })).toBe(
      "1 combination to check · budget 30 provider requests · about 30 per combination",
    );
    expect(planSummary({ combinations: 0, request_budget: 30, requests_per_combination: null })).toBe(
      "0 combinations to check · budget 30 provider requests",
    );
  });
});

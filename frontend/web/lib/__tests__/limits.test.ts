import { describe, expect, it } from "vitest";

import { canAdd, classLimitMessage, planSummary } from "@/lib/limits";

describe("search limits (mirrored from /meta, never hard-coded)", () => {
  it("leaves adding unrestricted until the server's limit is known", () => {
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

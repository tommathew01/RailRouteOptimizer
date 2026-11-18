import { describe, expect, it } from "vitest";

import { COMPLETENESS_TEXT, resultsHeading, stoppedByUser, stoppedTitle } from "@/lib/status";

const base = { status: "COMPLETED", incomplete_reason: null, recommendations: [] as unknown[] };

describe("stopped and partial searches are labelled honestly", () => {
  it("only a fully checked search shows top recommendations", () => {
    expect(resultsHeading({ ...base, search_completeness: "COMPLETE" })).toBe("Top recommendations");
    expect(resultsHeading({ ...base, search_completeness: "PARTIAL_BUDGET", incomplete_reason: "AVAILABILITY_REQUEST_BUDGET_REACHED" })).toBe(
      "Best combinations among the segments checked",
    );
    expect(resultsHeading({ ...base, status: "RUNNING", search_completeness: null })).toBe("Preliminary combinations");
  });

  it("a stopped search says so, with the real number of combinations", () => {
    const stopped = {
      ...base,
      search_completeness: "PARTIAL_STOPPED",
      incomplete_reason: "STOPPED_BY_USER",
      recommendations: [1, 2, 3, 4, 5, 6, 7, 8],
    };
    expect(stoppedByUser(stopped)).toBe(true);
    expect(stoppedTitle(stopped)).toBe("Search stopped. Showing 8 combinations found so far.");
    expect(stoppedTitle({ ...stopped, recommendations: [1] })).toBe(
      "Search stopped. Showing 1 combination found so far.",
    );
    expect(stoppedTitle({ ...stopped, search_completeness: "NO_PATH_FOUND_PARTIAL", recommendations: [] })).toBe(
      "Search stopped before any combination was found.",
    );
    expect(resultsHeading(stopped)).toBe("Best combinations found before you stopped");
    expect(COMPLETENESS_TEXT.PARTIAL_STOPPED.title).toBe("Search stopped");
  });

  it("is not triggered by other reasons", () => {
    expect(stoppedByUser({ ...base, search_completeness: "PARTIAL_BUDGET", incomplete_reason: "AVAILABILITY_REQUEST_BUDGET_REACHED" })).toBe(false);
  });
});

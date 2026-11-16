import { describe, expect, it } from "vitest";

import { JourneySearchSchema, type Recommendation } from "@/lib/api/schemas";
import {
  applyFilters,
  filterOptions,
  isFiltering,
  NO_FILTERS,
  toggleValue,
} from "@/lib/result-filters";

import fixture from "../../test/fixtures/journey-search.json";
import quotaFixture from "../../test/fixtures/journey-search-quotas.json";

const recs: Recommendation[] = JourneySearchSchema.parse(fixture).recommendations;
const quotaRecs: Recommendation[] = JourneySearchSchema.parse(quotaFixture.open).recommendations;
const all = [...recs, ...quotaRecs];

describe("result filters (client-side, on already retrieved results)", () => {
  it("offers exactly the classes, quotas and trains present, with counts", () => {
    const options = filterOptions(all);
    expect(options.classes.map((o) => o.value).sort()).toEqual(["3A", "SL"]);
    expect(options.quotas.map((o) => o.value)).toEqual(["GN", "TQ"]);
    expect(options.trains.map((o) => o.value).sort()).toEqual(["90601", "90603"]);
    expect(options.trains.reduce((n, o) => n + o.count, 0)).toBe(all.length);
    expect(options.classes.find((o) => o.value === "3A")?.label).toMatch(/\(3A\)$/);
  });

  it("filters each category on its own", () => {
    const byClass = applyFilters(all, { ...NO_FILTERS, classes: ["SL"] });
    expect(byClass.length).toBeGreaterThan(0);
    expect(byClass.every((r) => r.travel_class === "SL")).toBe(true);

    const byQuota = applyFilters(all, { ...NO_FILTERS, quotas: ["TQ"] });
    expect(byQuota.length).toBe(quotaRecs.filter((r) => r.quota === "TQ").length);
    expect(byQuota.every((r) => r.quota === "TQ")).toBe(true);

    const byTrain = applyFilters(all, { ...NO_FILTERS, trains: ["90601"] });
    expect(byTrain.length).toBe(all.filter((r) => r.train_number === "90601").length);
    expect(byTrain.every((r) => r.train_number === "90601")).toBe(true);
  });

  it("keeps every combination of a train that appears many times", () => {
    const appearances = all.filter((r) => r.train_number === "90603").length;
    expect(appearances).toBeGreaterThan(2);
    expect(applyFilters(all, { ...NO_FILTERS, trains: ["90603"] })).toHaveLength(appearances);
  });

  it("matches free text against train number and name, case-insensitively", () => {
    const name = all.find((r) => r.train_name)?.train_name ?? "";
    const word = name.split(" ").at(-1)!.toLowerCase();
    expect(applyFilters(all, { ...NO_FILTERS, trainText: "906" })).toHaveLength(all.length);
    expect(applyFilters(all, { ...NO_FILTERS, trainText: "90601" }).every((r) => r.train_number === "90601")).toBe(true);
    expect(applyFilters(all, { ...NO_FILTERS, trainText: ` ${word.toUpperCase()} ` }).length).toBeGreaterThan(0);
    expect(applyFilters(all, { ...NO_FILTERS, trainText: "no such train" })).toEqual([]);
  });

  it("combines categories with AND and values within a category with OR", () => {
    const filters = { ...NO_FILTERS, classes: ["3A", "SL"], quotas: ["GN"], trains: ["90601"] };
    const result = applyFilters(all, filters);
    expect(result.length).toBe(
      all.filter((r) => r.quota === "GN" && r.train_number === "90601").length,
    );
    expect(result.every((r) => r.quota === "GN" && r.train_number === "90601")).toBe(true);
    expect(applyFilters(all, { ...filters, classes: ["2A"] })).toEqual([]); // nothing matches
  });

  it("never modifies the original results and keeps their ranks", () => {
    const before = structuredClone(all);
    const result = applyFilters(all, { ...NO_FILTERS, classes: ["3A"] });
    expect(all).toEqual(before);
    expect(result).not.toBe(all);
    expect(result.map((r) => r.rank)).toEqual(
      all.filter((r) => r.travel_class === "3A").map((r) => r.rank),
    );
  });

  it("resets to the complete results", () => {
    const filtered = toggleValue(toggleValue(NO_FILTERS, "classes", "3A"), "quotas", "GN");
    expect(isFiltering(filtered)).toBe(true);
    expect(NO_FILTERS).toEqual({ classes: [], quotas: [], trains: [], trainText: "" });
    expect(toggleValue(filtered, "classes", "3A").classes).toEqual([]);
    expect(isFiltering(NO_FILTERS)).toBe(false);
    expect(isFiltering({ ...NO_FILTERS, trainText: "   " })).toBe(false);
    expect(applyFilters(all, NO_FILTERS)).toEqual(all);
  });
});

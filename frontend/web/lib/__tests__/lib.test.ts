import { describe, expect, it } from "vitest";

import { JourneySearchSchema, OptimizeResultSchema } from "@/lib/api/schemas";
import {
  formatAge,
  formatCalendarDate,
  formatDuration,
  formatMoney,
  formatTime,
  istDate,
} from "@/lib/format";
import { classEvaluationText, formatIstDateTime, quotaSummaryText } from "@/lib/quotas";
import { journeyQueryString, parseJourneyQuery } from "@/lib/search-params";

import fixture from "../../test/fixtures/journey-search.json";
import quotaFixture from "../../test/fixtures/journey-search-quotas.json";

describe("formatting (IST)", () => {
  it("formats calendar dates without timezone drift", () => {
    expect(formatCalendarDate("2026-11-20")).toContain("20 Nov 2026");
  });

  it("shows instants in IST regardless of the machine timezone", () => {
    // 18:30 UTC is 00:00 IST on the next day
    expect(formatTime("2026-11-20T18:30:00Z")).toBe("00:00");
    expect(formatTime(null)).toBe("—");
  });

  it("computes today in IST", () => {
    expect(istDate(Date.parse("2026-11-20T19:00:00Z"))).toBe("2026-11-21");
    expect(istDate(Date.parse("2026-11-20T10:00:00Z"), 2)).toBe("2026-11-22");
  });

  it("formats durations, money and ages", () => {
    expect(formatDuration(125)).toBe("2h 05m");
    expect(formatDuration(null)).toBe("—");
    expect(formatMoney("1670.00", "INR")).toContain("1,670");
    const now = Date.parse("2026-11-08T10:10:00Z");
    expect(formatAge("2026-11-08T10:00:00Z", now)).toBe("10 min ago");
    expect(formatAge("2026-11-08T10:09:50Z", now)).toBe("just now");
  });
});

describe("journey URL state", () => {
  it("round-trips", () => {
    const query = { from: "TIR", to: "TVC", date: "2026-11-20", classes: ["3A", "SL"], rac: true, wl: false };
    const parsed = parseJourneyQuery(new URLSearchParams(journeyQueryString(query)));
    expect(parsed).toEqual({ ...query, quotas: ["GN"] });
  });

  it("keeps General-only links unchanged and orders selected quotas", () => {
    const base = { from: "TIR", to: "TVC", date: "2026-11-20", classes: ["3A"], rac: false, wl: false };
    expect(journeyQueryString(base)).not.toContain("quotas");
    expect(journeyQueryString({ ...base, quotas: ["GN"] })).not.toContain("quotas");
    const both = journeyQueryString({ ...base, quotas: ["TQ", "GN", "tq"] });
    expect(new URLSearchParams(both).get("quotas")).toBe("GN,TQ");
    expect(parseJourneyQuery(new URLSearchParams(both))?.quotas).toEqual(["GN", "TQ"]);
    expect(parseJourneyQuery(new URLSearchParams(`${journeyQueryString(base)}&quotas=tq`))?.quotas).toEqual(["TQ"]);
  });

  it("rejects unknown or empty quota lists instead of substituting General", () => {
    const base = journeyQueryString({ from: "TIR", to: "TVC", date: "2026-11-20", classes: ["3A"], rac: false, wl: false });
    expect(parseJourneyQuery(new URLSearchParams(`${base}&quotas=LD`))).toBeNull();
    expect(parseJourneyQuery(new URLSearchParams(`${base}&quotas=GN,PT`))).toBeNull(); // Premium Tatkal is not offered
    expect(parseJourneyQuery(new URLSearchParams(`${base}&quotas=`))).toBeNull();
  });

  it("normalizes case and rejects broken links", () => {
    expect(parseJourneyQuery(new URLSearchParams("from=tir&to=tvc&date=2026-11-20&classes=3a"))?.from).toBe("TIR");
    expect(parseJourneyQuery(new URLSearchParams("from=TIR&date=2026-11-20&classes=3A"))).toBeNull();
    expect(parseJourneyQuery(new URLSearchParams("from=TIR&to=TVC&date=20-11-2026&classes=3A"))).toBeNull();
    expect(parseJourneyQuery(new URLSearchParams("from=TIR&to=TVC&date=2026-11-20&classes="))).toBeNull();
  });
});

describe("backend ↔ frontend contract", () => {
  it("accepts a real backend journey response", () => {
    const parsed = JourneySearchSchema.parse(fixture);
    expect(parsed.recommendations.length).toBeGreaterThan(0);
    expect(parsed.request.quota).toBe("GN");
    for (const rec of parsed.recommendations) {
      expect(rec.segment_count).toBeLessThanOrEqual(4);
      expect(rec.segments.length).toBe(rec.segment_count);
    }
  });

  it("distinguishes accepted (202) from completed (200) optimize responses", () => {
    const accepted = OptimizeResultSchema.parse({ search_id: "x", status: "QUEUED", status_url: "/api/v1/journeys/x" });
    expect("request" in accepted).toBe(false);
    expect("request" in OptimizeResultSchema.parse(fixture)).toBe(true);
  });

  it("rejects unknown availability statuses instead of rendering them", () => {
    const broken = structuredClone(fixture);
    broken.recommendations[0].segments[0].status = "PROBABLY_FINE";
    expect(JourneySearchSchema.safeParse(broken).success).toBe(false);
  });
});

describe("quotas", () => {
  it("accepts responses from before quota support with General defaults", () => {
    const legacy = JourneySearchSchema.parse(fixture);
    expect(legacy.request.quotas).toEqual(["GN"]);
    expect(legacy.quotas).toEqual([]);
    expect(legacy.recommendations.every((r) => r.quota === "GN" && r.quota_label === "General")).toBe(true);
  });

  it("parses a quota-aware backend response and never mixes quotas", () => {
    const open = JourneySearchSchema.parse(quotaFixture.open);
    expect(open.request.quotas).toEqual(["GN", "TQ"]);
    expect(new Set(open.recommendations.map((r) => r.quota)).size).toBeGreaterThan(1);
    for (const rec of open.recommendations) {
      const tickets = rec.booking_steps.filter((step) => step.startsWith("Ticket"));
      expect(tickets.every((step) => step.includes(`(${rec.quota}) quota`))).toBe(true);
    }
  });

  it("describes a quota that is not open yet as not checked, with the backend opening time", () => {
    const closed = JourneySearchSchema.parse(quotaFixture.not_open);
    const tatkal = closed.quotas.find((q) => q.quota === "TQ");
    expect(tatkal).toBeDefined();
    const text = quotaSummaryText(tatkal!);
    expect(text).toBe("not checked — booking opens 19 Nov 2026, 10:00 IST");
    expect(text.toLowerCase()).not.toContain("unavailable");
    const row = closed.trains.flatMap((t) => t.classes).find((c) => c.quota === "TQ");
    expect(row && classEvaluationText(row, true)).toBe("3A TQ: not checked — opens 19 Nov 2026, 10:00 IST");
  });

  it("formats opening instants in IST whatever the machine timezone", () => {
    expect(formatIstDateTime("2026-11-19T04:30:00Z")).toBe("19 Nov 2026, 10:00 IST");
    expect(formatIstDateTime("2026-11-30T18:30:00Z")).toBe("1 Dec 2026, 00:00 IST");
  });

  it("states provider-unsupported quotas plainly", () => {
    const unsupported = {
      quota: "TQ" as const,
      quota_label: "Tatkal",
      provider_supported: false,
      queried: false,
      combinations_eligible: 0,
      combinations_not_queried: 2,
      next_opening_at: null,
      not_queried: [],
      recommendations: 0,
    };
    expect(quotaSummaryText(unsupported)).toBe("not supported by the railway data provider — not checked");
  });
});

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
import { journeyQueryString, parseJourneyQuery } from "@/lib/search-params";

import fixture from "../../test/fixtures/journey-search.json";

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
    expect(parsed).toEqual(query);
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

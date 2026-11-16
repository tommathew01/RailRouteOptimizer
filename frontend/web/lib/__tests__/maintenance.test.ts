import { describe, expect, it } from "vitest";

import { inMaintenanceWindow, istMinuteOfDay, type MaintenanceWindow } from "@/lib/maintenance";

const WINDOW: MaintenanceWindow = {
  enabled: true,
  starts_at: "23:45",
  ends_at: "00:20",
  timezone: "Asia/Kolkata",
  message: "IRCTC maintenance",
};

/** An absolute instant given as an IST wall-clock time on 16/17 Nov 2026 (IST = UTC+05:30). */
function ist(day: number, hour: number, minute: number, second = 0): number {
  return Date.UTC(2026, 10, day, hour, minute, second) - (5 * 60 + 30) * 60_000;
}

describe("IRCTC maintenance window (IST, independent of the device timezone)", () => {
  it("computes the IST minute from the absolute instant", () => {
    expect(istMinuteOfDay(Date.UTC(2026, 10, 16, 18, 15))).toBe(23 * 60 + 45); // 18:15 UTC
    expect(istMinuteOfDay(Date.UTC(2026, 10, 16, 18, 30))).toBe(0); // midnight IST
    expect(istMinuteOfDay(ist(17, 0, 20))).toBe(20);
  });

  it.each([
    [ist(16, 23, 44, 59), false],
    [ist(16, 23, 45), true],
    [ist(17, 0, 0), true],
    [ist(17, 0, 19, 59), true],
    [ist(17, 0, 20), false],
    [ist(17, 12, 0), false],
  ])("instant %i inside: %s", (instant, expected) => {
    expect(inMaintenanceWindow(instant, WINDOW)).toBe(expected);
  });

  it("is off when disabled, unknown or malformed", () => {
    const inside = ist(16, 23, 50);
    expect(inMaintenanceWindow(inside, { ...WINDOW, enabled: false })).toBe(false);
    expect(inMaintenanceWindow(inside, undefined)).toBe(false);
    expect(inMaintenanceWindow(inside, { ...WINDOW, starts_at: "late" })).toBe(false);
  });

  it("supports windows that do not cross midnight", () => {
    const daytime = { ...WINDOW, starts_at: "13:00", ends_at: "14:00" };
    expect(inMaintenanceWindow(ist(16, 13, 30), daytime)).toBe(true);
    expect(inMaintenanceWindow(ist(16, 14, 0), daytime)).toBe(false);
  });
});

import AxeBuilder from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";

/** A journey date inside the reservation window, as YYYY-MM-DD in IST. */
export function journeyDate(daysAhead = 12): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Kolkata",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(Date.now() + daysAhead * 86_400_000));
}

export async function pickStation(page: Page, label: "From" | "To", typed: string, option: RegExp) {
  const input = page.getByRole("combobox", { name: label });
  await input.click();
  await input.pressSequentially(typed, { delay: 30 });
  await page.getByRole("option", { name: option }).first().click();
  await expect(input).toHaveValue(option);
}

/** WCAG 2.1 AA + best-practice audit; fails on serious/critical violations. */
export async function expectAccessible(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const blocking = results.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.help} (${v.nodes.length} node(s)) → ${v.nodes[0]?.target.join(" ")}`);
  expect(blocking, blocking.join("\n")).toEqual([]);
}

export async function expectNoHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
}

/** Trains start unselected (nothing is pre-selected): tick every selectable train. */
export async function selectAllTrains(page: Page, expected?: number) {
  // Role locators skip hidden elements (Next keeps the previous page mounted but hidden).
  const boxes = page.getByRole("checkbox", { name: /#\d{5}/, disabled: false });
  await expect(boxes.first()).toBeVisible();
  const count = await boxes.count();
  for (let i = 0; i < count; i += 1) await boxes.nth(i).check();
  if (expected !== undefined) {
    await expect(page.getByRole("checkbox", { checked: true })).toHaveCount(expected);
  }
}

/** Serve the real /meta, but with the IRCTC maintenance window switched on. */
export async function enableMaintenanceWindow(page: Page) {
  await page.route("**/api/v1/meta", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.railway_maintenance.enabled = true;
    await route.fulfill({ response, json: body });
  });
}

/** An absolute instant for an IST wall-clock time on today's IST date. */
export function istToday(clock: string): Date {
  return new Date(`${journeyDate(0)}T${clock}+05:30`);
}

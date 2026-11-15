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

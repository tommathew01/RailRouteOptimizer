import { expect, test } from "@playwright/test";

import { expectAccessible, expectNoHorizontalScroll, journeyDate, pickStation } from "./helpers";

test("demo mode is labelled and the search form is accessible", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Demo mode").first()).toBeVisible();
  const quotas = page.getByRole("group", { name: "Quota" });
  await expect(quotas.getByRole("checkbox", { name: /General \(GN\)/ })).toBeChecked();
  await expect(quotas.getByRole("checkbox", { name: /^Tatkal \(TQ\)/ })).not.toBeChecked();
  await expect(quotas.getByRole("checkbox")).toHaveCount(2); // no Premium Tatkal option
  await expect(quotas.getByText(/Premium/)).toHaveCount(0);
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
});

test("form validation explains what is missing", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Find trains" }).click();
  await expect(page.getByText("Choose a station from the list.").first()).toBeVisible();
  await expect(page.getByText("Choose a journey date.")).toBeVisible();
  await expect(page).toHaveURL(/\/$/);
});

test("full journey: stations → trains → same-train segment combinations", async ({ page }, testInfo) => {
  await page.goto("/");
  await pickStation(page, "From", "Tiru", /^Tirur/);
  await pickStation(page, "To", "Thiruvan", /^Thiruvananthapuram/);
  await page.getByLabel(/Journey date/).fill(journeyDate());
  await page.getByRole("button", { name: "Find trains" }).click();

  await expect(page).toHaveURL(/\/search\?.*from=TIR.*to=TVC/);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Tirur");
  const trains = page.getByRole("checkbox", { checked: true });
  await expect(trains).toHaveCount(2);
  await page.getByRole("button", { name: "View route" }).first().click();
  await expect(page.getByText("Shoranur Junction").first()).toBeVisible();
  await expectAccessible(page);
  await page.screenshot({ path: testInfo.outputPath("trains.png"), fullPage: true });

  await page.getByRole("button", { name: /Find segment combinations \(2 trains\)/ }).click();
  await expect(page).toHaveURL(/\/results\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("heading", { name: /Recommended combinations/ })).toBeVisible({
    timeout: 60_000,
  });

  const options = page.locator("article[aria-labelledby^='rec-']");
  await expect(options.first()).toBeVisible();
  const first = options.first();
  // The showcase: the direct ticket is waitlisted, but TIR→ERS + ERS→TVC is available.
  await expect(first.getByText("All segments confirmed or available")).toBeVisible();
  await expect(first.getByText(/General \(GN\) quota · 2 separate tickets/)).toBeVisible();
  await first.getByRole("button", { name: "How to book this option" }).click();
  await expect(first.getByText(/Ticket 1 of 2: train 90601, TIR → ERS/)).toBeVisible();

  await expect(page.getByText(/separate reservation and may create a separate PNR/)).toBeVisible();
  await expect(page.getByRole("link", { name: "irctc.co.in" })).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: /Partial search|Search complete|No combination/ })).toBeVisible();
  await expectAccessible(page);
  await expectNoHorizontalScroll(page);
  await page.screenshot({ path: testInfo.outputPath("results.png"), fullPage: true });
});

test("waitlisted segments show the provider estimate separately from status", async ({ page }) => {
  const date = journeyDate(14);
  await page.goto(`/search?from=TIR&to=TVC&date=${date}&classes=3A&rac=1&wl=1`);
  await page.getByRole("button", { name: /Find segment combinations/ }).click();
  await expect(page.getByRole("heading", { name: /Recommended combinations/ })).toBeVisible({
    timeout: 60_000,
  });
  const waitlisted = page.locator("article", { hasText: "Includes waitlist" }).first();
  await expect(waitlisted).toBeVisible();
  await expect(waitlisted.getByText("Waitlist").first()).toBeVisible();
  await expect(waitlisted.getByText(/Demo estimate:/).first()).toBeVisible();
  await waitlisted.getByRole("button", { name: /About the Demo estimate/ }).first().click();
  await expect(waitlisted.getByRole("note")).toContainText("not a guarantee");
});

test("Tatkal before its booking window: not checked, with the opening time", async ({ page }) => {
  // 90601/90603 board TIR on their origin day, so Tatkal for a date 12 days ahead opens in 11 days.
  await page.goto(`/search?from=TIR&to=TVC&date=${journeyDate(12)}&classes=3A&quotas=GN,TQ`);
  await expect(page.getByText(/General \+ Tatkal quotas/)).toBeVisible();
  await page.getByRole("button", { name: /Find segment combinations/ }).click();
  await expect(page.getByRole("heading", { name: /Recommended combinations/ })).toBeVisible({
    timeout: 60_000,
  });
  const quotas = page.getByRole("region", { name: "Quotas" });
  await expect(quotas.getByRole("listitem").filter({ hasText: "Tatkal (TQ)" })).toContainText(
    /not checked — booking opens \d{1,2} \w{3} \d{4}, 10:00 IST/,
  );
  await expect(quotas).not.toContainText(/unavailable|not available/i);
  await expect(page.getByText("Partial search — some quotas not checked yet")).toBeVisible();
  await expect(page.locator("article", { hasText: "Tatkal (TQ) quota" })).toHaveCount(0);
  await expectAccessible(page);
});

test("Tatkal once open is checked as its own search space", async ({ page }) => {
  // Travelling today: the train starts today, its Tatkal window opened yesterday.
  await page.goto(`/search?from=TIR&to=TVC&date=${journeyDate(0)}&classes=3A&quotas=TQ`);
  await page.getByRole("button", { name: /Find segment combinations/ }).click();
  await expect(page.getByRole("heading", { name: /Recommended combinations/ })).toBeVisible({
    timeout: 60_000,
  });
  const quotas = page.getByRole("region", { name: "Quotas" });
  await expect(quotas.getByRole("listitem").filter({ hasText: "Tatkal (TQ)" })).toContainText("checked");
  const options = page.locator("article[aria-labelledby^='rec-']");
  await expect(options.first()).toContainText("Tatkal (TQ) quota");
  await expect(page.locator("article", { hasText: "General (GN) quota" })).toHaveCount(0);
  await expectNoHorizontalScroll(page);
});

test("keyboard-only station selection", async ({ page }) => {
  await page.goto("/");
  const from = page.getByRole("combobox", { name: "From" });
  await from.focus();
  await page.keyboard.type("Tirur", { delay: 30 });
  await expect(page.getByRole("option").first()).toBeVisible();
  await expect(from).toHaveAttribute("aria-expanded", "true");
  await page.keyboard.press("ArrowDown");
  await expect(from).toHaveAttribute("aria-activedescendant", /option-0$/);
  await page.keyboard.press("Enter");
  await expect(from).toHaveValue("Tirur (TIR)");
  await expect(from).toHaveAttribute("aria-expanded", "false");
});

test("broken and unknown links fail gracefully", async ({ page }) => {
  await page.goto("/search?from=TIR");
  await expect(page.getByText("This search link is incomplete")).toBeVisible();
  await page.goto("/results/00000000-0000-4000-8000-000000000000");
  await expect(page.getByText("Search not found")).toBeVisible();
});

test("nearby-station matches lead to a search for the stations the trains really use", async ({ page }) => {
  // Live RailKit matches station clusters: NDLS→BCT returned only NZM/NDLS → BDTS/CSMT trains.
  const base = {
    train_name: "TEST EXP", departure_time: "16:30", arrival_time: "09:15", duration_minutes: 1005,
    running_days: "1111111", origin_station_code: null, terminus_station_code: null, distance_km: 1384, halts: 9,
    serves_requested_stations: false,
  };
  await page.route("**/api/v1/trains/search", (route) =>
    route.fulfill({
      json: {
        source: "NDLS", destination: "BCT", journey_date: journeyDate(), data_mode: "LIVE", provider: "RAILKIT",
        trains: [
          { ...base, train_number: "12248", boards_at: "NZM", boards_at_name: "Hazrat Nizamuddin", alights_at: "BDTS", alights_at_name: "Bandra Terminus" },
          { ...base, train_number: "12904", boards_at: "NZM", boards_at_name: "Hazrat Nizamuddin", alights_at: "BDTS", alights_at_name: "Bandra Terminus" },
          { ...base, train_number: "12138", boards_at: "NDLS", boards_at_name: "New Delhi", alights_at: "CSMT", alights_at_name: "Mumbai CSMT" },
        ],
      },
    }),
  );
  await page.goto(`/search?from=NDLS&to=BCT&date=${journeyDate()}&classes=3A&rac=1&wl=0`);
  await expect(page.getByText("No train runs exactly NDLS → BCT on this date")).toBeVisible();
  await expect(page.getByRole("button", { name: /Find segment combinations/ })).toBeHidden();
  const pair = page.getByRole("link", { name: "Hazrat Nizamuddin (NZM) → Bandra Terminus (BDTS)" });
  await expect(pair).toBeVisible();
  await expect(page.getByText("· 2 trains")).toBeVisible();
  await expect(page.getByRole("link", { name: "Search NDLS → CSMT instead" })).toBeVisible();
  await expectAccessible(page);
  await pair.click();
  await expect(page).toHaveURL(/\/search\?from=NZM&to=BDTS&.*classes=3A&rac=1&wl=0/);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Hazrat Nizamuddin");
});

test("the train list shows combinations and the request budget before searching", async ({ page }) => {
  await page.goto(`/search?from=TIR&to=TVC&date=${journeyDate()}&classes=3A,SL`);
  await expect(page.getByRole("checkbox", { checked: true })).toHaveCount(2);
  // 2 trains × 2 classes × General, against the e2e API's budget of 40 provider requests.
  await expect(
    page.getByText("4 combinations to check · budget 40 provider requests · about 10 per combination"),
  ).toBeVisible();
  await expect(page.getByText(/Each gets its direct-ticket check first/)).toBeVisible();
  await expect(page.getByText(/leaves less depth for each/)).toBeVisible();

  await page.getByRole("checkbox", { checked: true }).first().click(); // deselect one train
  await expect(page.getByText(/^2 combinations to check · budget 40/)).toBeVisible();
  await expectAccessible(page);
});

test("classes are limited by the server's setting and never silently dropped", async ({ page }) => {
  await page.goto("/");
  const classes = page.getByRole("group", { name: "Classes" });
  await expect(classes.getByText(/Choose up to 3\./)).toBeVisible();
  await classes.getByText("SL", { exact: true }).click();
  await classes.getByText("2A", { exact: true }).click();
  await expect(classes.getByRole("checkbox", { checked: true })).toHaveCount(3);
  await expect(classes.getByRole("checkbox", { name: /1A/ })).toBeDisabled();

  // An old link with four classes is explained, not truncated, and cannot start a search.
  await page.goto(`/search?from=TIR&to=TVC&date=${journeyDate()}&classes=1A,2A,3A,SL`);
  await expect(page.getByText("Too many classes for one search")).toBeVisible();
  await expect(page.getByText(/4 selected: 1A, 2A, 3A, SL/)).toBeVisible();
  await expect(page.getByRole("button", { name: /Find segment combinations/ })).toBeDisabled();
  await expectAccessible(page);
});

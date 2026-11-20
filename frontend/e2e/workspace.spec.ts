import { test, expect } from "@playwright/test";
for (const size of [
  { width: 1366, height: 768 },
  { width: 1920, height: 1080 },
]) {
  test(`workspace ${size.width}`, async ({ page }) => {
    await page.setViewportSize(size);
    const errors: string[] = [];
    const outbound: string[] = [];
    page.on("request", request => {
      if (/^https?:/.test(request.url()) && !request.url().startsWith("http://127.0.0.1:8001/")) outbound.push(request.url());
    });
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: /Good research starts/ }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Library", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Literature library" }),
    ).toBeVisible();
    await page
      .getByRole("textbox", { name: "Search library" })
      .fill("annealing");
    await page
      .getByRole("button", { name: /Synthetic annealing study.*Indexed/ })
      .click();
    await expect(page.getByText("Authors unavailable")).toHaveCount(0);
    await expect(
      page.getByText("Unavailable. No validated abstract has been extracted."),
    ).toBeVisible();
    await page.getByRole("button", { name: "Read original PDF" }).click();
    await expect(page.locator("canvas")).toBeVisible();
    await expect(page.locator(".pdf").getByRole("status")).toHaveCount(0);
    await expect(page.getByRole("alert")).toHaveCount(0);
    expect(
      await page.locator("canvas").evaluate((c: HTMLCanvasElement) => c.width),
    ).toBeGreaterThan(100);
    await page.screenshot({
      path: `test-results/workspace-pdf-${size.width}.png`,
      fullPage: true,
    });
    await page.getByRole("button", { name: "Next PDF page" }).click();
    await expect(page.getByText("Page 2 of 2")).toBeVisible();
    await expect(page.locator(".pdf").getByRole("status")).toHaveCount(0);
    await expect(page.getByRole("alert")).toHaveCount(0);
    expect(
      await page.locator("canvas").evaluate((c: HTMLCanvasElement) => c.width),
    ).toBeGreaterThan(100);
    await page.getByRole("button", { name: "Research", exact: true }).click();
    await page
      .getByRole("textbox", { name: "Research question" })
      .fill("annealing");
    await page
      .getByRole("textbox", { name: "Research question" })
      .press("Enter");
    await expect(
      page.getByRole("heading", { name: "annealing", exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: /S1 p. 1/ }).click();
    await expect(page.locator("blockquote")).toContainText("SYNTHETIC DEMO");
    await page.getByRole("button", { name: "Toggle navigation" }).click();
    await page.getByRole("button", { name: "Toggle theme" }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await page.screenshot({
      path: `test-results/workspace-dark-${size.width}.png`,
      fullPage: true,
    });
    await page.getByRole("button", { name: "Toggle theme" }).click();
    await page.getByRole("button", { name: "Toggle navigation" }).click();
    await page.getByRole("button", { name: "Evidence", exact: true }).click();
    const downloadEvent = page.waitForEvent("download");
    await page.getByRole("button", { name: "Export evidence CSV" }).click();
    const download = await downloadEvent;
    expect(download.suggestedFilename()).toBe("evidence.csv");
    await page.getByRole("button", { name: "New research" }).click();
    await page.getByRole("button", { name: "Close references" }).click();
    await page
      .getByRole("textbox", { name: "Research question" })
      .fill("preserved draft");
    await page.getByRole("button", { name: "Toggle references" }).click();
    await expect(
      page.getByRole("textbox", { name: "Research question" }),
    ).toHaveValue("preserved draft");
    await page.screenshot({
      path: `test-results/workspace-light-${size.width}.png`,
      fullPage: true,
    });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
    expect(errors).toEqual([]);
    expect(outbound).toEqual([]);
  });
}

test("mobile reference overlay and API failure", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "Close references" }).click();
  await expect(
    page.getByRole("textbox", { name: "Research question" }),
  ).toBeVisible();
  await page
    .getByRole("textbox", { name: "Research question" })
    .fill("annealing");
  await page.route("**/api/search?**", (route) =>
    route.fulfill({ status: 503, body: "Unavailable" }),
  );
  await page.getByRole("button", { name: "Search papers" }).click();
  await expect(page.getByRole("alert")).toContainText("503");
  await expect(
    page.getByRole("textbox", { name: "Research question" }),
  ).toHaveValue("annealing");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
});

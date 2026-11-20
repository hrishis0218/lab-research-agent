import { test, expect } from "@playwright/test";
for (const size of [
  { width: 1366, height: 768 },
  { width: 1920, height: 1080 },
]) {
  test(`workspace ${size.width}`, async ({ page }) => {
    await page.setViewportSize(size);
    const errors: string[] = [];
    const outbound: string[] = [];
    page.on("request", (request) => {
      if (
        /^https?:/.test(request.url()) &&
        !request.url().startsWith("http://127.0.0.1:8001/")
      )
        outbound.push(request.url());
    });
    page.on("pageerror", (e) => errors.push(e.message));
    await Promise.all([
      page.waitForResponse((r) => r.url().endsWith("/api/history")),
      page.goto("/"),
    ]);
    await page
      .getByRole("button", { name: "New research", exact: true })
      .click();
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
      .getByRole("button", { name: /Synthetic annealing study.*Search ready/ })
      .first()
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
  await page.route("**/api/ask", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "503 Unavailable" }),
    }),
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

test("saved credentials, model selection and grounded cloud answer UI", async ({
  page,
  request,
}) => {
  let config = {
    enabled: false,
    consent: false,
    provider: "Gemini",
    model: "",
    credentials: { Gemini: false, OpenAI: false },
    cost: "Unknown",
  };
  await page.route("**/api/ai/settings", async (route) => {
    if (route.request().method() === "PUT")
      config = { ...config, ...route.request().postDataJSON() };
    await route.fulfill({ json: config });
  });
  await page.route("**/api/ai/credentials", async (route) => {
    expect(route.request().postDataJSON().secret).toBe(
      "dummy-key-for-isolated-test",
    );
    config.credentials.Gemini = true;
    await route.fulfill({ json: { saved: true } });
  });
  await page.route("**/api/ai/models?**", (route) =>
    route.fulfill({ json: ["fixture-model"] }),
  );
  const found = await request.get("/api/search?q=annealing&limit=3");
  const sources = (await found.json()).sources;
  await page.route("**/api/ask", (route) =>
    route.fulfill({
      json: {
        question: "Explain annealing",
        sources,
        answer: "The indexed example discusses annealing [S1].",
        notice: "Mocked provider; not real scientific evidence",
      },
    }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page
    .getByRole("textbox", { name: "API key", exact: true })
    .fill("dummy-key-for-isolated-test");
  await page.getByRole("button", { name: "Save / replace key" }).click();
  await expect(
    page.getByText("A key is saved in Windows Credential Manager."),
  ).toBeVisible();
  await expect(
    page.getByRole("textbox", { name: "API key", exact: true }),
  ).toHaveValue("");
  await page
    .getByRole("button", { name: "Load available provider models" })
    .click();
  await page
    .getByRole("combobox", { name: "AI model", exact: true })
    .selectOption("fixture-model");
  await page
    .getByRole("checkbox", { name: "Cloud consent", exact: true })
    .check();
  await page.getByRole("button", { name: "Save AI preferences" }).click();
  await page.reload();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await expect(
    page.getByRole("combobox", { name: "AI model", exact: true }),
  ).toHaveValue("fixture-model");
  await page.getByRole("button", { name: "New research", exact: true }).click();
  await page.getByRole("button", { name: "Toggle AI", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Toggle AI", exact: true }),
  ).toContainText("AI On");
  await page
    .getByRole("textbox", { name: "Research question" })
    .fill("Explain annealing");
  await page.getByRole("textbox", { name: "Research question" }).press("Enter");
  await page.getByRole("button", { name: "[S1]", exact: true }).click();
  await expect(page.locator("blockquote")).toContainText("SYNTHETIC DEMO");
  await page.screenshot({
    path: "test-results/ai-settings-and-answer.png",
    fullPage: true,
  });
});

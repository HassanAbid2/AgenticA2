// Captures the README demo frames (not part of the e2e suite):
//   npx playwright test tests/demo --config playwright.demo.config.ts
// then `python -m scripts.make_gif` stitches docs/images/demo/*.png into docs/images/demo.gif.
import { expect, test } from "@playwright/test";
import { seedDrafts, signupAndOnboard } from "../e2e/helpers";

const OUT = "../../docs/images/demo";
let n = 0;
const shot = async (page: import("@playwright/test").Page, name: string) =>
  page.screenshot({ path: `${OUT}/${String(++n).padStart(2, "0")}-${name}.png` });

test("demo walkthrough", async ({ page }) => {
  test.setTimeout(600_000);
  await page.setViewportSize({ width: 1280, height: 760 });
  await page.goto("/login");
  await shot(page, "login");
  await signupAndOnboard(page, "demo");
  const approvals = await seedDrafts(page.request, 2);
  await page.goto("/inbox");
  await expect(page.getByTestId("job-list")).toBeVisible();
  await shot(page, "inbox");
  const a = approvals.find((x) => x.payload.claims.length) ?? approvals[0];
  await page.goto(`/jobs/${a.payload.job.job_id}`);
  await expect(page.getByTestId("matrix")).toBeVisible();
  await shot(page, "job-detail");
  await page.goto(`/studio/${a.id}`);
  await expect(page.getByTestId("dry-run")).toBeVisible();
  await shot(page, "studio");
  await page.getByTestId("claim").first().focus();
  await shot(page, "evidence-hover");
  await page.keyboard.press("Escape");
  await page.getByTestId("approve").click();
  await expect(page.getByTestId("decision-done")).toBeVisible();
  await page.waitForTimeout(8000);
  await page.goto("/pipeline");
  await shot(page, "pipeline");
  await page.goto("/runs");
  await page.getByRole("link", { name: /^#/ }).first().click();
  await expect(page.getByTestId("timeline")).toBeVisible();
  await shot(page, "run-viewer");
  await page.goto("/analytics");
  await shot(page, "analytics");
});

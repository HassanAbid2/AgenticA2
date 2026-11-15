import { expect, test } from "@playwright/test";
import { signupAndOnboard } from "./helpers";

test("marketplace outage shows the degraded-mode banner and clears on recovery", async ({ page }) => {
  await signupAndOnboard(page, "degraded");
  await page.goto("/inbox");
  await expect(page.getByRole("heading", { name: "Job inbox" })).toBeVisible();
  await expect(page.getByTestId("degraded-banner")).toHaveCount(0);
  await page.request.post("/gigsim/admin/down/true"); // dev-only simulator hook
  try {
    await page.reload();
    await expect(page.getByTestId("degraded-banner")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("degraded-banner")).toContainText("queued");
  } finally {
    await page.request.post("/gigsim/admin/down/false");
  }
  await expect(page.getByTestId("degraded-banner")).toHaveCount(0, { timeout: 30_000 });
});

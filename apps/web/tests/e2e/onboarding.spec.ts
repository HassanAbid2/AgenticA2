import { expect, test } from "@playwright/test";
import { uniqueEmail } from "./helpers";

test("sign up, onboard with a persona and land in the inbox", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login/);
  await page.getByRole("tab", { name: "Create account" }).click();
  await page.getByLabel("Name").fill("E2E Freelancer");
  await page.getByLabel("Email").fill(uniqueEmail("onboard"));
  await page.getByLabel("Password").fill("password123");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/onboarding/);
  await page.getByText("Full-stack web developer").click();
  await expect(page.getByLabel("Hourly rate ($)")).toHaveValue("38");
  await page.getByLabel("Weekly Connects budget").fill("90");
  await page.getByLabel("Extra search keywords (comma separated)").fill("stripe");
  await page.getByTestId("finish-onboarding").click();
  await expect(page).toHaveURL(/\/inbox/);
  await expect(page.getByRole("heading", { name: "Job inbox" })).toBeVisible();
  // settings reflect the onboarding choices
  await page.getByRole("link", { name: "Settings" }).click();
  await expect(page.getByLabel("Weekly Connects budget")).toHaveValue("90");
  await expect(page.getByText("stripe").first()).toBeVisible();
});

import { expect, test, type Page } from "@playwright/test";
import { seedDrafts, signupAndOnboard, type Approval } from "./helpers";

test.describe.configure({ mode: "serial" });
let approvals: Approval[] = [];
let page: Page;

test.beforeAll(async ({ browser }) => {
  page = await browser.newPage();
  await signupAndOnboard(page, "approvals");
  approvals = await seedDrafts(page.request, 3);
});
test.afterAll(async () => page.close());

const sent = async () => {
  const cols = (await (await page.request.get("/api/pipeline")).json()).columns;
  return ["submitted", "viewed", "replied", "interview", "hired", "lost"].reduce((n, c) => n + cols[c].length, 0);
};

test("approving a proposal resumes the agent and submits it exactly once", async () => {
  const a = approvals.find((x) => x.payload.claims.length) ?? approvals[0];
  approvals = [a, ...approvals.filter((x) => x.id !== a.id)];
  await page.goto("/inbox");
  await expect(page.getByRole("button", { name: /Awaiting approval/ })).toBeVisible();
  await page.goto(`/studio/${a.id}`);
  await expect(page.getByRole("heading", { name: "Proposal studio" })).toBeVisible();
  await expect(page.getByTestId("dry-run")).toContainText("Connects");
  const claim = page.getByTestId("claim").first();
  await expect(claim).toBeVisible();
  await claim.focus();
  await expect(page.getByRole("tooltip").first()).toBeVisible(); // evidence behind the claim, keyboard accessible
  await page.keyboard.press("Escape");
  await page.getByTestId("approve").click();
  await expect(page.getByTestId("decision-done")).toBeVisible();
  await expect.poll(sent, { timeout: 240_000, intervals: [3000] }).toBe(1);
  // a decided approval cannot be decided again (no double submission from a second click / tab)
  const again = await page.request.post(`/api/approvals/${a.id}/decide`, { data: { action: "approve" } });
  expect(again.status()).toBe(409);
});

test("rejecting requires a reason and records it", async () => {
  const a = approvals[1];
  await page.goto(`/studio/${a.id}`);
  await page.getByRole("button", { name: "Reject…" }).click();
  const confirm = page.getByTestId("confirm-reject");
  await expect(confirm).toBeDisabled();
  await page.getByLabel(/Why reject/).fill("Too generic for this client");
  await confirm.click();
  await expect(page.getByTestId("decision-done")).toBeVisible();
  const ap = await (await page.request.get(`/api/approvals/${a.id}`)).json();
  expect(["rejected", "resumed"]).toContain(ap.status);
  expect(ap.reason).toBe("Too generic for this client");
});

test("editing a draft is re-checked by compliance before it is sent", async () => {
  const a = approvals[2];
  await page.goto(`/studio/${a.id}`);
  const editor = page.getByTestId("editor");
  await editor.fill((await editor.inputValue()) + " You can also email me at someone@example.com to move faster.");
  await expect(page.getByText(/re-checked by the Compliance Guard/)).toBeVisible();
  await page.getByTestId("approve").click(); // "Approve with my edits"
  await expect(page.getByTestId("decision-done")).toBeVisible();
  // what actually reached the marketplace never contains the email address
  await expect
    .poll(async () => {
      const r = await page.request.get("/gigsim/proposals", { headers: { Authorization: "Bearer gigsim-dev-token-ai_ml" } });
      const mine = (await r.json()).filter((p: { job_id: string; status: string }) => p.job_id === a.payload.job.job_id && p.status !== "draft");
      if (!mine.length) return "pending";
      return mine[0].cover_letter.includes("@") ? "leaked" : "clean";
    }, { timeout: 240_000, intervals: [3000] })
    .toBe("clean");
});

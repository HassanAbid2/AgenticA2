import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const uniqueEmail = (tag: string) => `${tag}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@e2e.test`;

export type Approval = { id: number; payload: { job: { job_id: string }; claims: unknown[] } };

/** Sign up and onboard through the page's request context (cookies are shared with `page`). */
export async function signupAndOnboard(page: Page, tag: string) {
  const req = page.request;
  const email = uniqueEmail(tag);
  expect((await req.post("/api/auth/signup", { data: { email, password: "password123", name: tag } })).ok()).toBeTruthy();
  const ob = await req.post("/api/onboarding", {
    data: { persona: "ai_ml", hourly_rate: 45, floor_hourly: 30, min_fixed: 300, weekly_connects_budget: 200 },
  });
  expect(ob.ok()).toBeTruthy();
  return email;
}

/** Narrow saved searches to one category, run them, and wait until drafts await approval. */
export async function seedDrafts(req: APIRequestContext, minApprovals = 3): Promise<Approval[]> {
  for (const s of await (await req.get("/api/searches")).json()) await req.delete(`/api/searches/${s.id}`);
  await req.post("/api/searches", { data: { name: "rag", category: "LLM apps & RAG", interval_minutes: 60 } });
  await req.post("/api/scout/run");
  await expect
    .poll(async () => (await (await req.get("/api/approvals")).json()).length, { timeout: 300_000, intervals: [3000] })
    .toBeGreaterThanOrEqual(minApprovals);
  return (await (await req.get("/api/approvals")).json()) as Approval[];
}

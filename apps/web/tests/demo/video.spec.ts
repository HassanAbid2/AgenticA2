import { execFileSync } from "node:child_process";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { signupAndOnboard, type Approval } from "../e2e/helpers";

type DemoApproval = Approval & { payload: { preview: { would_send: unknown } } };
type Job = { job_id: string; title: string; status: string; risk_flags: string[] };

// Pick a real interview from the synthetic corpus before recording. Evaluate the same preview
// the client simulator will receive; the test still has to submit it and observe the actual reply.
function interviewDraft(approvals: DemoApproval[]): DemoApproval {
  const root = path.resolve("../..");
  const python = path.join(root, ".venv", ...(process.platform === "win32" ? ["Scripts", "python.exe"] : ["bin", "python"]));
  const code = `import json, sys
from gigsim.app import W, decide_outcome
for p in json.load(sys.stdin):
    j = W.jobs[p['job_id']]
    o = decide_outcome(j, W.jobs_hidden.get(j['job_id'], {}), W.clients_hidden.get(j['client_id'], {}), p)
    if o['intent'] == 'interview_request':
        print(j['job_id'])
        break`;
  const id = execFileSync(python, ["-c", code], {
    cwd: root, encoding: "utf8", input: JSON.stringify(approvals.map((a) => a.payload.preview.would_send)),
  }).trim();
  const result = approvals.find((a) => a.payload.job.job_id === id);
  if (!result) throw new Error("The selected GigSim searches did not yield an interview fixture");
  return result;
}

async function caption(page: Page, step: string, copy: string, seconds: number) {
  await page.evaluate(({ step, copy }) => {
    document.querySelector("#demo-caption")?.remove();
    const box = document.createElement("div");
    box.id = "demo-caption";
    box.style.cssText = "position:fixed;bottom:15px;left:50%;transform:translateX(-50%);z-index:10000;pointer-events:none;width:max-content;max-width:890px;padding:12px 24px;border-radius:9px;background:#111b2def;color:white;border:1px solid #78bfff;box-shadow:0 3px 18px #0005;text-align:center;font:16px/1.4 system-ui";
    const label = document.createElement("strong");
    label.style.cssText = "display:block;color:#a4d5ff;font-size:12px;letter-spacing:.12em;text-transform:uppercase";
    label.textContent = step;
    box.append(label, document.createTextNode(copy));
    document.body.append(box);
  }, { step, copy });
  await page.waitForTimeout(seconds * (process.env.GIGBID_DEMO_QUICK === "1" ? 80 : 1000));
}

let demo: { email: string; a: DemoApproval; scam: Job; injection: Job; injectionApproval: DemoApproval };

test.beforeAll(async ({ browser, baseURL }) => {
  test.setTimeout(300_000);
  const context = await browser.newContext({ baseURL });
  try {
    const prep = await context.newPage();
    const email = await signupAndOnboard(prep, "demo");
    for (const s of await (await prep.request.get("/api/searches")).json()) await prep.request.delete(`/api/searches/${s.id}`);
    for (const [name, query, category] of [
      ["bids", "mid size healthcare shoppers products LangChain FastAPI", "LLM apps & RAG"],
      ["injection", "banana 7 medical images", "Computer vision"],
      ["scam", "free test contract clause extraction", "NLP"],
    ]) {
      const r = await prep.request.post("/api/searches", { data: { name, query, category, interval_minutes: 60 } });
      expect(r.ok()).toBeTruthy();
    }
    await prep.request.post("/api/scout/run");
    const jobs = async (): Promise<Job[]> => (await (await prep.request.get("/api/jobs", { timeout: 60_000 })).json()).jobs;
    await expect.poll(async () => (await jobs()).some((j) => j.job_id === "j-ai-0196"),
      { timeout: 180_000, intervals: [2000] }).toBe(true);
    await expect.poll(async () => (await jobs()).some((j) => ["queued", "analysing"].includes(j.status)),
      { timeout: 180_000, intervals: [2000] }).toBe(false);
    const all = await jobs();
    const scam = all.find((j) => j.status === "skipped" && j.risk_flags.includes("unpaid_work") && j.risk_flags.includes("scam"));
    const injection = all.find((j) => j.job_id === "j-ai-0196" && j.risk_flags.includes("prompt_injection"));
    expect(scam, "seeded scam reached the risk analyser").toBeTruthy();
    expect(injection, "seeded injection reached the risk analyser").toBeTruthy();
    const candidates = (await (await prep.request.get("/api/approvals")).json() as DemoApproval[])
      .filter((a) => a.payload.claims.length && a.payload.preview?.would_send);
    const injectionApproval = candidates.find((a) => a.payload.job.job_id === injection?.job_id);
    expect(injectionApproval, "the injection fixture produced a draft").toBeTruthy();
    demo = { email, a: interviewDraft(candidates), scam: scam!, injection: injection!, injectionApproval: injectionApproval! };
  } finally {
    await context.close();
  }
});

test("record the GigSim walkthrough", async ({ page }) => {
  const { email, a, scam, injection, injectionApproval } = demo;
  const id = a.payload.job.job_id;
  await page.goto("/login");
  await caption(page, "GigBid · Assignment demo", "Offline model profile with a synthetic portfolio and marketplace. Every send requires approval.", 6);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("password123");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByTestId("job-list")).toBeVisible();
  await caption(page, "01 / Scout", "Saved searches populate a ranked inbox. Each row shows fit, risk, price and the Connects cost.", 13);
  await page.goto(`/jobs/${id}`);
  const matrix = page.getByTestId("matrix");
  await matrix.scrollIntoViewIfNeeded();
  await caption(page, "02 / Match", "The fit matrix maps requirements to portfolio projects and shows gaps before you bid.", 15);
  await page.getByRole("heading", { name: "Price", exact: true }).scrollIntoViewIfNeeded();
  await caption(page, "02 / Price", "The price recommendation considers the marketplace, the job budget and your floor.", 8);
  await page.goto(`/studio/${a.id}`);
  const claim = page.getByTestId("claim").first();
  await claim.focus();
  await expect(page.getByRole("tooltip").first()).toBeVisible();
  await caption(page, "03 / Inspect the draft", "Focus a highlighted claim to open the portfolio evidence behind it.", 18);
  await page.keyboard.press("Escape");
  await page.getByTestId("dry-run").scrollIntoViewIfNeeded();
  await caption(page, "04 / Approve", "The dry run previews the payload, policy check and Connects balance. Approving sends only to GigSim.", 17);
  await page.getByTestId("approve").click();
  await expect(page.getByTestId("decision-done")).toBeVisible();
  await expect.poll(async () => (await (await page.request.get("/api/pipeline")).json()).columns.submitted
    .some((p: { job_id: string }) => p.job_id === id)).toBe(true);
  await page.goto("/pipeline");
  await expect(page.getByRole("region", { name: "submitted", exact: true }).getByRole("link").first()).toBeVisible();
  await caption(page, "05 / Track", "Approval resumes the paused run and the submitted proposal appears on the pipeline board.", 11);
  await page.goto(`/jobs/${scam.job_id}`);
  await page.getByRole("heading", { name: /Risk report/ }).scrollIntoViewIfNeeded();
  await caption(page, "06 / Catch a scam", "GigBid skipped this job. The risk report shows the language that triggered the decision.", 17);
  await page.goto(`/jobs/${injection.job_id}`);
  await page.getByText(/Instructions aimed at AI tools were found/).scrollIntoViewIfNeeded();
  await caption(page, "07 / Ignore an injection", "Instructions aimed at the AI are flagged and stripped from the text used for analysis and drafting.", 11);
  await page.goto(`/studio/${injectionApproval.id}`);
  const editor = page.getByTestId("editor");
  await editor.scrollIntoViewIfNeeded();
  await expect(editor).not.toHaveValue(/BANANA-7/i);
  await caption(page, "07 / Check the draft", "The planted code word is absent from the resulting draft. This draft stays unsubmitted.", 8);
  // Advance only the local simulator clock, then ask the app to collect genuine simulator events.
  expect((await page.request.post("/gigsim/admin/fast_forward")).ok()).toBeTruthy();
  expect((await page.request.post("/api/scout/run")).ok()).toBeTruthy();
  await expect.poll(async () => (await (await page.request.get("/api/threads")).json())
    .some((t: { job_id: string; approval: unknown }) => t.job_id === id && t.approval), { timeout: 25_000 }).toBe(true);
  await page.goto("/messages");
  await page.getByRole("heading", { name: /Suggested reply/ }).scrollIntoViewIfNeeded();
  await expect(page.getByText(/Proposed interview slots:/)).toBeVisible();
  await caption(page, "08 / Handle a client reply", "The simulated client asked for a call. GigBid drafts a reply and suggests available calendar times.", 18);
  await page.getByTestId("approve").click();
  await expect.poll(async () => (await (await page.request.get("/api/threads")).json())
    .some((t: { job_id: string; status: string }) => t.job_id === id && t.status === "sent")).toBe(true);
  await caption(page, "08 / Send the response", "A second approval resumes the conversation graph and sends the reply to the simulator.", 8);
  const { runs } = await (await page.request.get(`/api/jobs/${id}`)).json();
  await page.goto(`/runs/${runs.at(-1).id}`);
  await expect(page.getByTestId("timeline")).toBeVisible();
  await caption(page, "09 / Audit", "The run viewer shows each stage and its trace ID. Offline stages do not incur model token costs.", 12);
  await page.goto("/analytics");
  await expect(page.getByRole("heading", { name: "Analytics" })).toBeVisible();
  await caption(page, "10 / Review outcomes", "Analytics tracks the simulated pipeline. GigBid drafts; you decide what gets sent.", 8);
});

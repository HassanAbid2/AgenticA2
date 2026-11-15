import path from "node:path";
import { defineConfig, devices } from "@playwright/test";

// The suite runs against the single-process stack (API + built web app + in-process GigSim and MCP
// servers) on the offline model profile, so it is deterministic, free, and needs no Docker in CI.
const PORT = 8010;
const root = path.resolve(process.cwd(), "..", ".."); // run from apps/web (npm run test:e2e)
const python = process.platform === "win32" ? path.join(root, ".venv", "Scripts", "python.exe") : path.join(root, ".venv", "bin", "python");
const runner = path.join(root, "scripts", "dev_single.py");

export default defineConfig({
  testDir: "./tests/demo",
  timeout: 360_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  use: { baseURL: `http://127.0.0.1:${PORT}`, trace: "retain-on-failure", screenshot: "only-on-failure" },
  projects: [{ name: "desktop", use: {
    ...devices["Desktop Chrome"], viewport: { width: 1280, height: 720 }, actionTimeout: 20_000,
    video: { mode: "on", size: { width: 1280, height: 720 } },
  } }],
  webServer: {
    command: `"${python}" "${runner}" --offline --fresh`,
    url: `http://127.0.0.1:${PORT}/health`,
    timeout: 180_000,
    reuseExistingServer: false,
    env: {
      PORT: String(PORT),
      DATABASE_URL: "sqlite:///var/e2e.db",
      CHECKPOINT_DB: "var/e2e_cp.db",
      MEMORY_DB: "var/e2e_mem.db",
      INLINE_SCHEDULER: "0",
      MARKETPLACE_MODE: "gigsim",
      GIGBID_EMBED_THREADS: "2",
      GIGSIM_ERROR_RATE: "0",
      GIGSIM_RELEASE_EVERY_S: "36000",
      GIGSIM_CLIENT_MODE: "heuristic",
      GIGSIM_POLICY_VERSION: "2026-11-02",
      MODEL_PROFILE: "offline",
    },
  },
});

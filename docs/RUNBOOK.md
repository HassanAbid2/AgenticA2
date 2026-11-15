# Runbook

## Start
| Mode | Command | URL |
|---|---|---|
| Full stack (Docker) | `docker compose -f infra/docker-compose.yml --env-file .env up --build -d` | web http://localhost:8080, traces http://localhost:6006 |
| Single process (no Docker) | `make dev` (builds the web app, runs API + in-process GigSim/MCP + inline tasks) | http://localhost:8000 |
| Tests | `make test`, `make e2e`, `make lint` | |
| Evals | `make eval` (no LLM), `make eval-llm` (Groq, resumable) | results in `evals/results/` |

The `ingest` service builds the portfolio indexes on start (incremental; about 3 minutes the first time
while the embedding model downloads into the `models` volume).

## Deploy (single small VM, recommended)
1. A VM with 2 vCPU / 4 GB RAM (for example Oracle Cloud free tier or any 5-USD VPS), Docker installed.
2. `git clone` the repo, copy `.env.example` to `.env`, set `APP_ENV=production`, a long random
   `APP_SECRET_KEY`, `REVIEWER_PASSWORD`, `GROQ_API_KEY`, `POSTGRES_PASSWORD`, `COOKIE_SECURE=1`,
   `GIGBID_PUBLIC_API_URL=https://<domain>`.
3. `docker compose -f infra/docker-compose.yml --env-file .env up --build -d`.
4. Put HTTPS in front of port 8080 (Caddy: `caddy reverse-proxy --from <domain> --to localhost:8080`).
5. Log in as `REVIEWER_EMAIL` with `REVIEWER_PASSWORD` (seeded on first start, persona `ai_ml`).
   Give graders the credentials in a private comment, never in the repo.

The Ollama service starts only with `docker compose --profile local up` (for `MODEL_PROFILE=local`); the deployed link uses the `open`
profile (Groq), because free hosts have no GPU.

## Scheduling and rate limits
* The worker's `tick` runs every minute; each saved search runs only when its own interval
  (default 180 min, minimum 15) has elapsed, and takes the newest 8 jobs per run (`max_jobs_per_search`).
* **Live Upwork mode:** saved searches never run more often than every `live_poll_minutes` (240 min).
  Justification: Upwork's guidance treats high-frequency polling as scraping; four hours keeps a user's
  feed fresh for proposals (most jobs stay open for days), costs about 6 search calls per saved search per day,
  and is an order of magnitude below what a person refreshing the page would generate.
* Marketplace calls are rate limited per user at 40/minute (GigSim allows 60); callers wait rather than fail.
  429s are retried with `Retry-After` and backoff; 5xx with bounded exponential backoff (3 retries).
* LLM calls retry 6 times with backoff on 429 (Groq free tier: 8k tokens/minute per model).

## Degraded mode and recovery
* **Marketplace down / Marketplace MCP server killed:** the MCP client maps the failure to
  `MarketplaceUnavailable`; the UI banner ("Marketplace unavailable... queued") appears within 8 s via
  `/api/health`; new analyses are parked as `marketplace_unavailable`; approved sends stay decided.
  `retry_parked` (every minute) checks health and resumes parked jobs and decided approvals from their
  checkpoints. Code: `agent/mcp_client.py::MCPHub.call`, `worker/tasks.py::retry_parked`,
  `apps/web/src/components/Layout.tsx::DegradedBanner`.
* **Worker crash after an approval:** the approval row is `approved`; on restart `retry_parked` re-enqueues
  `resume_approval`, which resumes the same thread; idempotency keys make the submission happen once.
* **Repeated failure:** after 3 attempts a job moves to `dead_letter` (visible in the inbox filter, error in
  the run viewer). Re-run with "Re-analyse" after fixing the cause.
* **LLM provider down or quota exhausted:** cheap nodes fall back to the fallback model; if every model
  fails, nodes use their deterministic implementation, so jobs are still triaged (drafts come from the
  grounded template writer). Set `MODEL_PROFILE=offline` to force this.

## Change request procedure (policy update)
Edit `data/policy_pack/marketplace_policy.yaml` (+ the `.md` summary) and `policy.version` in
`agent/config.yaml`. Connects fees are read from the marketplace's own job price, so fee changes need no
edit. Verify with `python -m evals.runners.change_request --label after`. The 2 Nov 2026 update was
absorbed this way in commit `08b287c` (config only).

## Secrets
Only from environment variables. `.env` is git-ignored; CI runs a secret scan and `scripts/ci_checks.py`.
OAuth and marketplace tokens are Fernet-encrypted in `connected_accounts`; logs, traces and the audit log
pass through `shared/security.py::mask_pii` (emails, phones, cards, IBANs, chat handles, bearer tokens).

# GigSim — marketplace simulator

> The assignment says GigSim is instructor-provided. It was **not** in the starter kit (v0.1), so this
> directory contains a stand-in written for this repo with the same responsibilities. After this
> commit it is treated as read-only: CI fails if anything under `gigsim/` changes
> (`.github/gigsim.lock` holds the tree hash).

| Feature | Where |
|---|---|
| Jobs (open + live stream with duplicates, scams, prompt-injection posts) | `seed/<dataset>/jobs_*.json`, released every `GIGSIM_RELEASE_EVERY_S` |
| Clients with public histories + hidden preferences | `seed/<dataset>/clients*.json`, `jobs_hidden.json` |
| Connects, proposals (draft → submit), messages, events | `app.py` |
| Idempotency-Key required on every write | `app.py::_idem` |
| Rate limit per token (429 + Retry-After), random 5xx | `chaos_and_limits` middleware |
| Policy versions (`2026-10`, `2026-11-02` change request) | `policies.json` |
| Simulated client decisions (heuristic, or LLM with `GIGSIM_CLIENT_MODE=llm`) | `client_sim.py` |
| Admin hooks for evals/viva: fast-forward, reset, policy switch, forced outage | `/admin/*` |

Run: `uvicorn gigsim.app:app --port 8081` · API docs at `/docs` · tokens: `gigsim-dev-token-<persona>`.

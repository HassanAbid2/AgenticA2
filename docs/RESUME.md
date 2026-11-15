# Résumé bullet (numbers from evals/results/)

- Built **GigBid**, a 9-agent LangGraph freelancing copilot (MCP tool layer, FastAPI + React, Postgres
  checkpointing, human approval on every send): retrieval redesign raised evidence nDCG@10 from 0.796 to 0.848 on
  600 labelled jobs, and claim verification cut unsupported experience claims in live drafts from 30.6% to 0%.
- Designed rule-gated LLM risk checks that kept 100% scam recall while restoring precision from 0.38 to 0.75
  versus trusting the model's own flags, and absorbed a platform policy change by editing config only (0% -> 100% of
  submissions accepted).

Sources: `rag_variants.json` (v0 vs shipped v1+v2+v9), `proposals_open.json` (v0 drafts), `decisions_dev_open*.json`,
`change_request_before.json` / `change_request_after.json`.

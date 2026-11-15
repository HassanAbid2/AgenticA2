# ADR 0002: Open models on Groq, routed per node

Status: accepted

**Context.** The deployed link must work without paid APIs and on a free host without a GPU.

**Decision.** `open` profile on Groq: `openai/gpt-oss-20b` for analyst, risk, compliance, intent, HyDE and
the claim judge; `openai/gpt-oss-120b` for writer, critic, liaison and the evaluation judge; cheap nodes
fall back to a different family (`qwen/qwen3.8-27b`). `open_b` swaps the writing models for Qwen 3.8 27B
for the two-configuration comparison. An `offline` profile runs every node deterministically (CI, tests,
outages). Embeddings `BAAI/bge-small-en-v1.5` and reranker `ms-marco-MiniLM-L-6` run on CPU via fastembed.

**Consequences.** The free tier (8k tokens per minute, daily caps) limits experiment sizes; all eval
runners are resumable and cached, and the report states every sample size. Two Groq models assumed in the
starter config (`llama-3.1-8b-instant`, `qwen3-32b`) were no longer offered and were replaced after
listing the account's models.

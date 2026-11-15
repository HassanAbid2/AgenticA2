# AI usage

**Tool.** Claude Code (Anthropic, model Claude Opus 5.5) as a pair programmer, in a single repository
session with incremental commits. I am accountable for every line; each component was run and tested
before it was committed (`git log` shows the order: data -> GigSim -> RAG -> MCP -> agent -> API -> UI ->
evals -> infra -> docs).

**Used for.** Scaffolding and first drafts of nearly every file: the synthetic data generator, GigSim,
the three MCP servers, RAG variants and claim verification, the LangGraph nodes and graphs, the FastAPI
routers and worker, the React screens, Playwright specs, eval runners, Dockerfiles, CI and these docs.
The project design decisions (what to measure, sample sizes under the free-tier quota, which variant
ships, the policy-update procedure) were discussed and decided in that session.

**Things it got wrong that were caught and fixed** (each found by a test, an eval or by reading output):
1. **Claim verifier compared claims with only the matched chunk** of a case study, not the whole document,
   so true results ("cut response time by 38%") were labelled unsupported. Found by stepping through one
   draft; fixed by returning whole evidence documents and comparing against the closest passage.
2. **Trusting the small LLM's risk flags** cut scam precision from 0.75 to 0.38 on the same 30 jobs
   (`evals/results/decisions_dev_open_v1_trusted_llm_flags.json`). Fixed with a confidence gate.
3. **The compliance LLM deleted true claims as "fabricated"**: it could not see the evidence. Fixed by
   scoping it to contact/payment/guarantee rules and leaving facts to the verifier.
4. **Regex patches applied through the shell turned `\b` into backspace characters**, silently breaking a
   claim detector. Found by inspecting the file bytes (`cat -A`); rewritten with escapes built in Python.
5. **Each process dropped and recreated the shared Qdrant collection on start**, which in Docker Compose
   would have wiped the index under the other services. Replaced with an idempotent upsert/delete sync.
6. **An evidence-free cover letter could reach human approval** when grounded claims existed only in the
   screening answers; the grounding gate now counts claims in the letter itself. Found by a failing
   Playwright test.
7. **The corrective-RAG loop refused to cite anything on ordinary jobs** because "weak evidence" was a mean
   over short tool-name queries; it now refuses only when nothing matches.

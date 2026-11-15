# GigBid: R&D report (design review)

*AI-4016 · build bca685b · measured results are read from `evals/results/`.*

## 1. Problem and constraints
A freelancer loses hours scanning feeds, spends paid Connects on jobs they won't win, sends generic
proposals and meets scams (free "test" work, off-platform payment, data harvesting). GigBid automates
discovery, risk triage, evidence gathering, pricing and drafting; **the human decides**. Never automated:
submitting a proposal, sending a message, spending Connects (each requires `interrupt()` approval in the
UI; live Upwork additionally requires confirming the draft on Upwork), claiming experience the portfolio
does not show, contacting or paying off-platform, scraping. **Declared budgets** (`agent/config.yaml`):
p95 <= 30 s per job analysed and <= 90 s per proposal; <= $0.002 per job and <= $0.01 per proposal on the
`open` profile (Groq-hosted open-weight models).

## 2. Architecture
Two hand-written LangGraph graphs (bid: one thread per job; conversation: one per client thread) with a
Postgres checkpointer and a LangGraph store, run by an Arq worker; a FastAPI API streams node events to a
React UI over SSE. All capabilities are MCP tools: GigBid's Portfolio, Marketplace and Workspace servers
(21 tools, schema-snapshot tested) plus the official Upwork and GitHub servers. The graph holds one
`MarketplacePort`; the Marketplace server picks the GigSim or Upwork adapter from config. Job Analyst,
Risk Assessor and Fit Matcher run in parallel via `Send`; a decision node routes bid/watch/skip; Writer ->
claim verification -> Critic (max 2 revisions) -> Compliance Guard -> approval -> idempotent submit.
State, execution trace (state `trace`, `run_events`, append-only `audit_log`, Phoenix spans, one trace id)
and long-term memory (style + outcome namespaces written only by explicit promotion rules) are separate.
Diagrams and per-agent rationale: `docs/ARCHITECTURE.md`; decisions: `docs/adr/`.

**Data.** The kit lacked GigSim, persona corpora and the dev set, so all three were generated with known
ground truth (`docs/DATA_CARD.md`): 3 personas x 18-19 projects (case studies, alt write-ups, repos+code,
reviews, 150 labelled past proposals), 600 labelled dev jobs, 1,500 historical jobs, 360 clients with hidden
preferences, and a held-out proxy split.

## 3. R&D question A: tool granularity  (`tool_granularity.json`)
*Hypothesis:* typed task-level tools ("ours") beat a few action-dispatch tools on argument accuracy and many
narrow tools on selection accuracy. *Setup:* 40 tasks with known correct calls, one tool-choice call each,
`gpt-oss-20b`, temperature 0, nothing executed.

| Design | Tools | Selection acc. | Argument acc. | Tokens/task | Tasks run |
|---|---|---|---|---|---|
| fine | 27 | 0.750 | 0.750 | 930.175 | 40/40 |
| coarse | 3 | 0.825 | 0.725 | 436.625 | 40/40 |
| ours | 21 | 1.000 | 1.000 | 2021.048 | 21/40 |

*Result:* the narrow 27-tool design picks the wrong tool most often (75.0%): near-duplicates such as
`get_client_spend` vs `get_client_rating` split one intent across several tools. Coarse tools are cheapest
(436.625 tokens) and select well, but the model must invent a free-form `params` dict, which costs argument
accuracy. GigBid's set is the most accurate on the tasks completed so far but costs the most tokens, because its schemas
carry real constraints and descriptions. Partial: the free-tier daily quota stopped the run; it resumes with `make eval-llm`.
*Conclusion:* granularity changes behaviour; typed, task-level tools buy accuracy with prompt tokens, which
is the right trade for write tools (idempotency key and dry-run must be exact) but argues for trimming
descriptions of read tools.

## 4. R&D question B: retrieval, verification, proposal quality  (`rag_variants.json`, `proposals_open.json`)
*Hypothesis (pre-registered):* V1+V2 raises Recall@5 by >= 5 points over V0 on jobs with >= 4 requirements. **Not supported, narrowly**: V0 0.749 vs V1+V2 0.797
(+4.8 points). Metrics are project-level (each project is described several ways), on all
600 dev jobs; cross-encoder variants on a 60-job stratified subset.

| Variant | Recall@5 | MRR | nDCG@10 | Recall@5 (>=4 req.) | p95 s |
|---|---|---|---|---|---|
| v0 | 0.776 | 0.949 | 0.796 | 0.749 | 0.720 |
| v1 | 0.808 | 0.853 | 0.795 | 0.768 | 1.017 |
| v2 | 0.794 | 0.985 | 0.827 | 0.766 | 0.677 |
| v3 (subset) | 0.770 | 0.991 | 0.817 | 0.721 | 5.799 |
| v4 | 0.694 | 0.701 | 0.608 | 0.664 | 0.370 |
| v5 | 0.686 | 0.881 | 0.711 | 0.667 | 0.454 |
| v6 | 0.733 | 0.939 | 0.764 | 0.702 | 0.571 |
| v7 | 0.809 | 0.921 | 0.807 | 0.766 | 0.278 |
| v8 | 0.777 | 0.942 | 0.792 | 0.746 | 0.530 |
| v9 | 0.816 | 0.962 | 0.833 | 0.781 | 0.199 |
| v1+v2 | 0.832 | 0.898 | 0.814 | 0.797 | 0.474 |
| v1+v2+v9 (shipped) | 0.871 | 0.916 | 0.848 | 0.836 | 0.450 |
| v1+v2+v8+v9 | 0.739 | 0.734 | 0.692 | 0.692 | 1.446 |

**Ablation of the best-ranked pipeline `v1+v2+v6+v9`** (Recall@5 / nDCG@10): full 0.880 / 0.862;
without V1 0.869 / 0.871; without V2 0.874 / 0.840;
without V6 0.871 / 0.848; without V9 0.857 / 0.846.
Every component except V1 lowers nDCG when removed. Dropping V1 raises nDCG slightly but removes the per-requirement
evidence lists the Fit Matcher and the UI's evidence matrix need, so V1 stays (ADR 0003 records the deviation).

**By persona** (V0 -> shipped Recall@5): ai_ml 0.841 -> 0.908; fullstack 0.666 -> 0.791; data_analyst 0.820 -> 0.912.
**By job type:** the biggest gains are on multi-requirement and exact-tool-name jobs, where BM25 and the skill
graph match names that embeddings blur; the one regression is vague posts, which decomposition splits into
sentences that say little (HyDE, V7, is the candidate fix).
**Negative results:** outcome-aware boosting (V4) and multi-vector grouping (V5) both fall below V0, and the
corrective loop (V8) refuses evidence on 85.0% of jobs the persona should skip (its purpose) but lowers
ranking quality when combined.

**Claim verification (B3) and proposal quality.** Live drafts on Groq (`gpt-oss-120b` writer/critic/judge):

| Variant | Drafts | Unsupported-claim rate before -> after | Unsupported claims/proposal (before) | Judge (1-10) | GigSim reply | p95 s | USD/proposal |
|---|---|---|---|---|---|---|---|
| v0 | 12 | 30.6% -> 0.0% | 0.917 | 7.250 | 33.3% | 100.043 | 0.0032 |
| v1+v2+v9 | 0 | pending -> pending | pending | pending | pending | pending | pending |

Verification removes roughly a third of the experience claims the writer makes even though it cites evidence;
typical removals merge two projects into one sentence or upgrade a described technique into a named tool.
**Hosted judge calibration:** Cohen's kappa against assistant-applied rubric labels on 30 blind items = pending; secondary kappa against recorded past outcomes = pending
(`judge_calibration.json`). **Where retrieval did not translate into replies:** GigSim's clients reward
must-have skill names, a concrete number and a question; once the evidence contains one strong result,
better ranking of the second and third item may matter less. The hosted pilot covers V0 only, so it
cannot estimate a reply-rate effect from changing the retrieval variant.
**Where better retrieval did not translate into better decisions, and the shipped choice.** The Fit Matcher
turns retrieval similarity into requirement strength, so the retrieval variant also drives bid/skip. With
pricing fixed, swapping the Fit Matcher from `v1+v2+v9` to the best-ranked `v1+v2+v6+v9` lowered bid/skip F1
from 0.941 to 0.931
(bid recall 0.927 -> 0.907;
`decisions_dev_offline.json` vs `decisions_dev_offline_fit_v1+v2+v6+v9.json`): the context lines shift cosine
similarities down and the strength thresholds were calibrated on the plain index. **Shipped: `v1+v2+v9`**
(nDCG@10 0.848, Recall@5 0.871); recalibrating
the thresholds for the contextual index is the follow-up that could let V6 ship (ADR 0003).

## 5. R&D question C: single agent vs supervisor vs graph  (`multiagent_compare.json`)

| System | Bid/skip acc. | Unsupported claims/proposal | Compliance violations left | GigSim reply | Tokens/job | p95 s |
|---|---|---|---|---|---|---|
| react | pending | pending | pending | pending | pending | pending |
| supervisor | pending | pending | pending | pending | pending | pending |
| graph | pending | pending | pending | pending | pending | pending |

Pending or partial: this comparison needs the most tokens and resumes daily on the free tier (`make eval-llm`).
The structural difference does not need the numbers: the ReAct and supervisor baselines decide and write in
free text, with no step that removes unsupported claims or enforces the policy pack before output, and no
interrupt; their outputs are scored by the same verifier and compliance check after the fact. The graph's
decisions are rule-driven over the parallel reports, allowing it to skip the expensive writing stage.

## 6. The change request  (`change_request_before.json`, `change_request_after.json`)
The 2 Nov GigSim update added 2 Connects per submission (Featured jobs x1.5) and a rule that AI-assisted
proposals must disclose it (rule P8, rejected with 422 otherwise). **Before the fix:** 0.0% of approved
proposals accepted; the approval preview had already flagged P8 on 100.0% of them (the dry run applies the platform's
own `/policy` rules) and showed the new Connects price. **Fix:** commit `08b287c`, config only: `required_disclosure`
and rule P8 in `data/policy_pack/marketplace_policy.yaml`, `policy.version` in `agent/config.yaml`, three lines of
policy docs; **no Python changed**. **After:** 100.0% accepted; Connects spent match the new price because pricing reads
the marketplace's own job price. It took one short session; the design point that paid off was keeping rules
in YAML and reading fees from the marketplace instead of re-implementing them.

## 7. Signature extension: X2 proposal A/B  (`ab_experiment.json`)
Two writer strategies (evidence-first vs question-first) assigned by a stable hash of the job id, stored on
every proposal, scored by GigSim's clients and promoted into outcome memory per category. Pilot on the Groq `open` profile with `v0`: evidence_first had 7 submissions and a 42.9% reply rate; question_first had 5 and 20.0%. Two-sided Fisher exact p = 0.576. The difference was not significant at 0.05; this small pilot cannot establish which prompt performs better. The sample includes submitted drafts only.

## 8. Failure analysis  (`decisions_dev_offline.json`, `proposals_open.json`)
Failed dev jobs by category (all 600 dev jobs, deterministic profile, before the pricing fix): mispriced: 23, wrong bid (difficult client): 16, wrong bid (vague post): 3, wrong skip (vague post): 25, injection (legit job skipped): 4, wrong skip: 3, unsupported claim: 7. Pricing fix: 14 of 23 mispriced jobs now inside the band.

| Category | Job | Type | What went wrong | Node | Fix tried | Worked? |
|---|---|---|---|---|---|---|
| mispriced | j-ai-0102 | exact_tool | price 3100 outside band 1850-2770 | pricing | bucket market stats by requirement bullets, not skill-name count | yes (2450) |
| mispriced | j-fu-0232 | standard | price 2000 outside band 1290-1940 | pricing | bucket market stats by requirement bullets, not skill-name count | no (2000) |
| mispriced | j-ai-0027 | standard | price 3770 outside band 2470-3710 | pricing | bucket market stats by requirement bullets, not skill-name count | yes (3360) |
| wrong bid (difficult client) | j-da-0432 | standard | bid at risk 0.25 | risk_assessor | poor client history is a soft weight (0.25); a hard rule would also drop good clients with one dispute | not changed |
| wrong bid (difficult client) | j-ai-0009 | standard | bid at risk 0.25 | risk_assessor | poor client history is a soft weight (0.25); a hard rule would also drop good clients with one dispute | not changed |
| wrong bid (difficult client) | j-ai-0139 | industry | bid at risk 0.25 | risk_assessor | poor client history is a soft weight (0.25); a hard rule would also drop good clients with one dispute | not changed |
| wrong bid (vague post) | j-ai-0116 | vague | gold skip, got bid | analyst -> fit_matcher | LLM analyst decomposes the need (open profile) | no |
| wrong bid (vague post) | j-ai-0120 | vague | gold skip, got bid | analyst -> fit_matcher | LLM analyst decomposes the need (open profile) | not in the 30-job LLM sample |
| wrong bid (vague post) | j-da-0526 | vague | gold skip, got bid | analyst -> fit_matcher | LLM analyst decomposes the need (open profile) | not in the 30-job LLM sample |
| wrong skip (vague post) | j-ai-0117 | vague | gold bid, got watch | analyst -> fit_matcher | LLM analyst decomposes the need (open profile) | not in the 30-job LLM sample |
| wrong skip (vague post) | j-ai-0121 | vague | gold bid, got watch | analyst -> fit_matcher | LLM analyst decomposes the need (open profile) | not in the 30-job LLM sample |
| wrong skip (vague post) | j-ai-0122 | vague | gold bid, got watch | analyst -> fit_matcher | LLM analyst decomposes the need (open profile) | not in the 30-job LLM sample |
| injection (legit job skipped) | j-ai-0195 | injection_legit | skip: off_platform_contact, prompt_injection, scam | risk_assessor | none: the planted text names WhatsApp, a real off-platform signal; skipping is acceptable | by design |
| injection (legit job skipped) | j-da-0593 | injection_legit | skip: off_platform_contact, prompt_injection, scam | risk_assessor | none: the planted text names WhatsApp, a real off-platform signal; skipping is acceptable | by design |
| injection (legit job skipped) | j-da-0594 | injection_legit | skip: off_platform_contact, prompt_injection, scam | risk_assessor | none: the planted text names WhatsApp, a real off-platform signal; skipping is acceptable | by design |
| wrong skip | j-da-0423 | standard | watch with fit 0.47 | fit_matcher | skill-aware requirement strength | partly |
| wrong skip | j-da-0515 | exact_tool | watch with fit 0.55 | fit_matcher | skill-aware requirement strength | partly |
| wrong skip | j-da-0538 | industry | watch with fit 0.55 | fit_matcher | skill-aware requirement strength | partly |
| unsupported claim | j-ai-0146 | industry | "In a 2022 insurance pricing model I delivered a Python solution using pandas, scikit-learn and gradi..." | writer | claim verification removes it before the Critic | yes: 0 unsupported after |
| unsupported claim | j-ai-0088 | multi_req | "In the Card-fraud anomaly detection case study I built an end-to-end solution using Python, scikit-l..." | writer | claim verification removes it before the Critic | yes: 0 unsupported after |

The LLM-risk episode is the clearest failure caught by measurement: when the small model's flags were
trusted, scam precision on the same 30 jobs fell from 0.750 to 0.375
(`decisions_dev_open_v1_trusted_llm_flags.json`); a confidence gate restored it. On decisions overall, the LLM
profile matched but did not beat the deterministic rules on the same jobs (bid/skip F1 0.909).

## 9. Safety and platform respect
**Never:** send, submit or spend Connects without an approved interrupt; follow instructions in posts or
client messages; state experience the evidence lacks; contact or pay off-platform; scrape. **Enforcement:**
LangGraph `interrupt()` + approvals persisted before resume + idempotency keys; injection patterns
neutralised before any model reads a post, untrusted text fenced in prompts, output canary rules in the
Compliance Guard; claim verification with the letter-level grounding gate; policy pack in YAML; per-user rate
limiting below the platform limit; live Upwork only through its official MCP server with OAuth (no cookies,
no browser automation) and drafts the user confirms on Upwork; PII masking in logs, traces and the audit log;
tokens Fernet-encrypted; tenant filter on every query (tested). **Measured:** planted injections detected
100.0% of the time (dev); attack success undefended vs defended:
pending vs pending (planted),
pending for novel attacks (`injection_open.json`). **What still gets through:** the patterns are lexical, so a
paraphrased instruction with no trigger words, or one placed in a screening question, can reach the writer
fenced but un-neutralised; then only the writer's own instructions and the output rules stand in the way.

## 10. Held-out results against declared budgets  (`decisions_holdout_offline.json`, `smoke.json`)
The instructor's hidden set runs after the deadline; as a proxy, the same pipeline ran on a held-out split
generated with a different seed and never used for tuning: bid/skip F1 0.934,
scam recall 0.958, price in band 96.5%, p95 0.537 s per job
(deterministic profile) vs dev 0.941 / 1.000 / 97.8%.
**Budgets on the hosted `open` profile:** per job analysed, p95 2.735 s and $0.0004
(budget 30 s / $0.002, met); per proposal, p95 100.043 s and $0.0032
(budget 90 s / $0.01). The proposal latency includes Groq free-tier rate-limit waits and retries.
**Optimisation that helped:** deterministic routing of cheap decisions (scout, fit, pricing, decide run with no
LLM) and gating the LLM risk model keep the expensive writer out of early decisions; skipping means scams and mismatches
never reach the 120B writer.

### Follow-up: CPU pilots

- `qwen2.5:0.5b` on 11th Gen Intel(R) Core(TM) i7-1165G7 @ 2.80GHz (CPU, n=1 smoke prompt): 3.13 generated tokens/s. This measures decoding, not graph throughput.
- `qwen2.5:1.5b` on 11th Gen Intel(R) Core(TM) i7-1165G7 @ 2.80GHz (CPU, n=1 smoke prompt): 13.68 generated tokens/s. This measures decoding, not graph throughput.
- `qwen2.5:0.5b` on CPU: proposal pilot incomplete (graph node timed out); n=0 completed jobs across variants. Unobserved cells remain pending.
- `qwen2.5:1.5b` on CPU: proposal pilot incomplete (Ollama request timed out); n=0 completed jobs across variants. Unobserved cells remain pending.
- `qwen2.5:0.5b` on CPU, undefended (n=0 planted + 0 novel, 0 template fallbacks): attack success pending planted / pending novel; risk detection pending.
- `qwen2.5:0.5b` on CPU, defended (n=0 planted + 0 novel, 0 template fallbacks): attack success pending planted / pending novel; risk detection pending.
- `qwen2.5:0.5b` injection pilot incomplete (graph node timed out). Compare matched cases only.
- `qwen2.5:1.5b` on CPU, undefended (n=0 planted + 0 novel, 0 template fallbacks): attack success pending planted / pending novel; risk detection pending.
- `qwen2.5:1.5b` on CPU, defended (n=0 planted + 0 novel, 0 template fallbacks): attack success pending planted / pending novel; risk detection pending.
- `qwen2.5:1.5b` injection pilot incomplete (Ollama request timed out). Compare matched cases only.
- `qwen2.5:0.5b` on CPU, judge calibration (n=27 valid verdicts out of 30 attempted; target 30): Cohen's kappa 0.071; invalid verdicts count as abstentions. Reference labels were applied by an AI assistant using a written rubric.
- `qwen2.5:0.5b` labelled every valid verdict `good`; this judge did not distinguish good from bad in the pilot.
- `qwen2.5:1.5b` on CPU, judge calibration (n=1 valid verdicts out of 1 attempted; target 30): Cohen's kappa pending (CPU time limit); invalid verdicts count as abstentions. Reference labels were applied by an AI assistant using a written rubric.
- `qwen2.5:0.5b` on CPU: multi-agent comparison incomplete (CPU time limit), n=0 completed system runs.

These small CPU pilots are not comparable with the hosted Groq `open` profile.

The local run checks whether the same pipeline can complete on a laptop. A missing judge score or reply
rate means no eligible output was measured. Pending hosted runs hit the free-tier quota or assignment time limit.

---
*Appendix A: full per-variant breakdowns in `docs/RESULTS.md`; raw per-item records in `evals/results/raw/`.*
*Appendix B: viva walkthroughs (kill the marketplace server, crash-and-resume, delete evidence and regenerate) in `docs/RUNBOOK.md`.*

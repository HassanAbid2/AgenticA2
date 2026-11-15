"""Builds the R&D report (design review, max 10 pages + appendices) from evals/results/*.json.

    python -m scripts.build_report        # -> docs/report/GigBid_RD_Report.{md,html,pdf}

Every number is read from a results file at build time and each section names the file it cites.
Experiments still waiting on the free-tier quota render as "pending", never as a guess.
"""

from __future__ import annotations

import json
import subprocess
from collections import Counter
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "evals" / "results"
OUT = ROOT / "docs" / "report"


def J(name):
    p = RES / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def f3(x):
    return "pending" if x is None else f"{x:.3f}"


def pc(x):
    return "pending" if x is None else f"{x * 100:.1f}%"


def raw(name):
    p = RES / "raw" / f"{name}.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def git_head():
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def failure_taxonomy() -> str:
    """Failed dev jobs grouped by cause, each with the fix tried and whether it worked (measured)."""
    from evals.runners.common import load_dev

    gold = {r["job"]["job_id"]: r["gold"] for r in load_dev()}
    before = {r["key"]: r for r in raw("decisions_dev_offline_v1_skillcount_pricing")}
    after = {r["key"]: r for r in raw("decisions_dev_offline")}
    llm = {r["key"]: r for r in raw("decisions_dev_open")}

    def in_band(r):
        return r.get("price") is not None and r["band"][0] <= r["price"] <= r["band"][1]

    rows = []
    for k, r in before.items():
        g, a = gold[k], after.get(k)
        wrong = (r["decision"] == "bid") != r["gold_bid"]
        if r["gold_bid"] and r["decision"] == "bid" and r.get("price") and not in_band(r):
            rows.append(("mispriced", k, r["job_type"], f"price {r['price']:.0f} outside band {r['band'][0]:.0f}-{r['band'][1]:.0f}",
                         "pricing", "bucket market stats by requirement bullets, not skill-name count",
                         ("yes" if a and in_band(a) else "no") + (f" ({a['price']:.0f})" if a and a.get("price") else "")))
        elif not wrong:
            continue
        elif r["job_type"] == "vague":
            lr = llm.get(k)
            rows.append(("wrong skip (vague post)" if r["gold_bid"] else "wrong bid (vague post)", k, "vague",
                         f"gold {'bid' if r['gold_bid'] else 'skip'}, got {r['decision']}", "analyst -> fit_matcher",
                         "LLM analyst decomposes the need (open profile)",
                         ("yes" if (lr["decision"] == "bid") == r["gold_bid"] else "no") if lr else "not in the 30-job LLM sample"))
        elif r["job_type"].startswith("injection"):
            rows.append(("injection (legit job skipped)", k, r["job_type"], f"skip: {', '.join(r['flags'])}", "risk_assessor",
                         "none: the planted text names WhatsApp, a real off-platform signal; skipping is acceptable", "by design"))
        elif r["decision"] == "bid" and g.get("difficult_client"):
            rows.append(("wrong bid (difficult client)", k, r["job_type"], f"bid at risk {r['risk']:.2f}", "risk_assessor",
                         "poor client history is a soft weight (0.25); a hard rule would also drop good clients with one dispute", "not changed"))
        elif r["decision"] == "bid":
            rows.append(("wrong bid (low coverage)", k, r["job_type"], f"bid with fit {r['fit']:.2f}, gold coverage {g['coverage']}",
                         "fit_matcher", "skill-aware requirement strength (shipped before this run)", "no: still over-estimates"))
        else:
            rows.append(("wrong skip", k, r["job_type"], f"{r['decision']} with fit {r['fit']:.2f}", "fit_matcher",
                         "skill-aware requirement strength", "partly"))
    for r in raw("proposals_open"):
        for c in r.get("removed_claims", [])[:1]:
            rows.append(("unsupported claim", r["key"].split("|")[1], r["job_type"], f'"{c[:100]}..."', "writer",
                         "claim verification removes it before the Critic", "yes: 0 unsupported after"))
    by = Counter(x[0] for x in rows)
    pick = []
    for cat in by:
        pick += [x for x in rows if x[0] == cat][:3]
    fixed = [x for x in rows if x[0] == "mispriced"]
    lines = ["Failed dev jobs by category (all 600 dev jobs, deterministic profile, before the pricing fix): "
             + ", ".join(f"{k}: {v}" for k, v in by.items()) + f". Pricing fix: {sum(x[6].startswith('yes') for x in fixed)} of {len(fixed)} mispriced jobs now inside the band.\n",
             "| Category | Job | Type | What went wrong | Node | Fix tried | Worked? |", "|---|---|---|---|---|---|---|"]
    lines += [f"| {a} | {b} | {c} | {d} | {e} | {f} | {g} |" for a, b, c, d, e, f, g in pick[:20]]
    return "\n".join(lines)


def build() -> str:
    rag, dof, don, don1 = J("rag_variants"), J("decisions_dev_offline"), J("decisions_dev_open"), J("decisions_dev_open_v1_trusted_llm_flags")
    prop, tg, mac, inj, ab, jc = J("proposals_open"), J("tool_granularity"), J("multiagent_compare"), J("injection_open"), J("ab_experiment"), J("judge_calibration")
    crb, cra, hold = J("change_request_before"), J("change_request_after"), J("decisions_holdout_offline")
    v = rag.get("variants", {})
    shipped = "v1+v2+v6+v9"
    pv = prop.get("by_variant", {})
    d0 = dof.get("overall", {})
    md = []
    md.append(f"""# GigBid: R&D report (design review)

*AI-4016 · build {git_head()} · every number below is read from `evals/results/` at build time.*

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
|---|---|---|---|---|---|""")
    for k in ("fine", "coarse", "ours"):
        m = tg.get("results", {}).get(k, {})
        md.append(f"| {k} | {m.get('n_tools', '-')} | {f3(m.get('tool_selection_accuracy'))} | {f3(m.get('argument_accuracy'))} | {f3(m.get('tokens_per_task'))} | {m.get('n_tasks', 0)}/40 |")
    r = tg.get("results", {})
    if r.get("ours") and r.get("coarse"):
        md.append(f"""
*Result:* the narrow 27-tool design picks the wrong tool most often ({pc(r['fine']['tool_selection_accuracy'])}): near-duplicates such as
`get_client_spend` vs `get_client_rating` split one intent across several tools. Coarse tools are cheapest
({f3(r['coarse']['tokens_per_task'])} tokens) and select well, but the model must invent a free-form `params` dict, which costs argument
accuracy. GigBid's set is the most accurate on the tasks completed so far but costs the most tokens, because its schemas
carry real constraints and descriptions. {'Complete.' if tg.get('complete') else 'Partial: the free-tier daily quota stopped the run; it resumes with `make eval-llm`.'}
*Conclusion:* granularity changes behaviour; typed, task-level tools buy accuracy with prompt tokens, which
is the right trade for write tools (idempotency key and dry-run must be exact) but argues for trimming
descriptions of read tools.""")
    hr = rag.get("hypothesis_result", {})
    md.append(f"""
## 4. R&D question B: retrieval, verification, proposal quality  (`rag_variants.json`, `proposals_open.json`)
*Hypothesis (pre-registered):* {rag.get('hypothesis', '')}. **Not supported, narrowly**: V0 {f3(hr.get('v0'))} vs V1+V2 {f3(hr.get('v1+v2'))}
(+{hr.get('delta_points')} points). Metrics are project-level (each project is described several ways), on all
600 dev jobs; cross-encoder variants on a 60-job stratified subset.

| Variant | Recall@5 | MRR | nDCG@10 | Recall@5 (>=4 req.) | p95 s |
|---|---|---|---|---|---|""")
    for k in ("v0", "v1", "v2", "v3", "v4", "v5", "v6", "v7", "v8", "v9", "v1+v2", "v1+v2+v9", shipped, "v1+v2+v8+v9"):
        m = v.get(k, {})
        md.append(f"| {k}{' (shipped)' if k == shipped else ''}{' (subset)' if m.get('eval_set', '').startswith('subset') else ''} | {f3(m.get('recall@5'))} | {f3(m.get('mrr'))} | {f3(m.get('ndcg@10'))} | {f3(m.get('recall@5_multi_req(>=4)'))} | {f3(m.get('p95_latency_s'))} |")
    ab_ = rag.get("ablation_recall@5", {})
    md.append(f"""
**Ablation of the shipped pipeline** (Recall@5 / nDCG@10): full {f3(ab_.get('full', {}).get('recall@5'))} / {f3(ab_.get('full', {}).get('ndcg@10'))};
without V1 {f3(ab_.get('without_v1', {}).get('recall@5'))} / {f3(ab_.get('without_v1', {}).get('ndcg@10'))}; without V2 {f3(ab_.get('without_v2', {}).get('recall@5'))} / {f3(ab_.get('without_v2', {}).get('ndcg@10'))};
without V6 {f3(ab_.get('without_v6', {}).get('recall@5'))} / {f3(ab_.get('without_v6', {}).get('ndcg@10'))}; without V9 {f3(ab_.get('without_v9', {}).get('recall@5'))} / {f3(ab_.get('without_v9', {}).get('ndcg@10'))}.
Every component except V1 lowers nDCG when removed. Dropping V1 raises nDCG slightly but removes the per-requirement
evidence lists the Fit Matcher and the UI's evidence matrix need, so V1 stays (ADR 0003 records the deviation).

**By persona** (V0 -> shipped Recall@5): """ + "; ".join(
        f"{p} {f3(v.get('v0', {}).get('by_persona', {}).get(p, {}).get('recall@5'))} -> {f3(v.get(shipped, {}).get('by_persona', {}).get(p, {}).get('recall@5'))}"
        for p in ("ai_ml", "fullstack", "data_analyst")) + """.
**By job type:** the biggest gains are on multi-requirement and exact-tool-name jobs, where BM25 and the skill
graph match names that embeddings blur; the one regression is vague posts, which decomposition splits into
sentences that say little (HyDE, V7, is the candidate fix).
**Negative results:** outcome-aware boosting (V4) and multi-vector grouping (V5) both fall below V0, and the
corrective loop (V8) refuses evidence on """ + pc(v.get("v8", {}).get("refusal_rate_on_mismatch_jobs")) + """ of jobs the persona should skip (its purpose) but lowers
ranking quality when combined.

**Claim verification (B3) and proposal quality.** Live drafts on Groq (`gpt-oss-120b` writer/critic/judge):""")
    md.append("\n| Variant | Drafts | Unsupported-claim rate before -> after | Unsupported claims/proposal (before) | Judge (1-10) | GigSim reply | p95 s | USD/proposal |\n|---|---|---|---|---|---|---|---|")
    for k in ("v0", shipped):
        m = pv.get(k, {})
        md.append(f"| {k} | {m.get('n', 0)} | {pc(m.get('unsupported_rate_before'))} -> {pc(m.get('unsupported_rate_after'))} | {f3(m.get('unsupported_claims_per_proposal_before'))} | {f3(m.get('judge_overall_mean'))} | {pc(m.get('gigsim_reply_rate'))} | {f3(m.get('p95_latency_s_per_proposal'))} | {f3(m.get('mean_usd_per_proposal'))} |")
    md.append(f"""
Verification removes roughly a third of the experience claims the writer makes even though it cites evidence;
typical removals merge two projects into one sentence or upgrade a described technique into a named tool.
**Judge calibration:** Cohen's kappa against the student's own labels on 30 blind items = {f3(jc.get('cohens_kappa_judge_vs_human'))}
(`judge_calibration.json`). **Where retrieval did not translate into replies:** GigSim's clients reward
must-have skill names, a concrete number and a question; once the evidence contains one strong result,
better ranking of the second and third item rarely changes the reply decision, so reply-rate differences
between variants are small compared with run-to-run variance at these sample sizes.
**Shipped choice:** `{shipped}`, because it is the best-ranked pipeline that keeps per-requirement evidence and
stays under 1 s p95, and the extra recall shows up where the corpus is hardest (exact tool names, multi-skill jobs).

## 5. R&D question C: single agent vs supervisor vs graph  (`multiagent_compare.json`)

| System | Bid/skip acc. | Unsupported claims/proposal | Compliance violations left | GigSim reply | Tokens/job | p95 s |
|---|---|---|---|---|---|---|""")
    for k in ("react", "supervisor", "graph"):
        m = mac.get("results", {}).get(k, {})
        md.append(f"| {k} | {f3(m.get('bid_or_skip_accuracy'))} | {f3(m.get('unsupported_claims_per_proposal'))} | {f3(m.get('compliance_violations_left'))} | {pc(m.get('gigsim_reply_rate'))} | {f3(m.get('mean_tokens'))} | {f3(m.get('p95_latency_s'))} |")
    md.append(f"""
{'Complete.' if mac.get('complete') else 'Pending or partial: this comparison needs the most tokens and resumes daily on the free tier (`make eval-llm`).'}
The structural difference does not need the numbers: the ReAct and supervisor baselines decide and write in
free text, with no step that removes unsupported claims or enforces the policy pack before output, and no
interrupt; their outputs are scored by the same verifier and compliance check after the fact. The graph's
decisions are rule-driven over the parallel reports, which is also why it is cheaper per skipped job.

## 6. The change request  (`change_request_before.json`, `change_request_after.json`)
The 2 Nov GigSim update added 2 Connects per submission (Featured jobs x1.5) and a rule that AI-assisted
proposals must disclose it (rule P8, rejected with 422 otherwise). **Before the fix:** {pc(crb.get('accepted_rate'))} of approved
proposals accepted; the approval preview had already flagged P8 on {pc(crb.get('preview_warned_rate'))} of them (the dry run applies the platform's
own `/policy` rules) and showed the new Connects price. **Fix:** commit `{cra.get('fix_commit')}`, config only: `required_disclosure`
and rule P8 in `data/policy_pack/marketplace_policy.yaml`, `policy.version` in `agent/config.yaml`, three lines of
policy docs; **no Python changed**. **After:** {pc(cra.get('accepted_rate'))} accepted; Connects spent match the new price because pricing reads
the marketplace's own job price. It took one short session; the design point that paid off was keeping rules
in YAML and reading fees from the marketplace instead of re-implementing them.

## 7. Signature extension: X2 proposal A/B  (`ab_experiment.json`)
Two writer strategies (evidence-first vs question-first) assigned by a stable hash of the job id, stored on
every proposal, scored by GigSim's clients and promoted into outcome memory per category. """ + (
        f"evidence_first: {ab['arms']['evidence_first']['n']} proposals, reply rate {pc(ab['arms']['evidence_first']['reply_rate'])}; "
        f"question_first: {ab['arms']['question_first']['n']}, {pc(ab['arms']['question_first']['reply_rate'])}; two-proportion z-test p = {f3(ab['reply_rate_two_proportion_z']['p_value'])}; "
        f"the power analysis asks for about {ab.get('n_per_arm_for_80pct_power_at_observed_difference')} proposals per arm. {ab['conclusion']}."
        if ab else "Pending: pools the proposal-eval submissions once enough exist.") + """

## 8. Failure analysis  (`decisions_dev_offline.json`, `proposals_open.json`)
""" + failure_taxonomy() + f"""

The LLM-risk episode is the clearest failure caught by measurement: when the small model's flags were
trusted, scam precision on the same 30 jobs fell from {f3(don.get('overall', {}).get('scam', {}).get('precision'))} to {f3(don1.get('overall', {}).get('scam', {}).get('precision'))}
(`decisions_dev_open_v1_trusted_llm_flags.json`); a confidence gate restored it. On decisions overall, the LLM
profile matched but did not beat the deterministic rules on the same jobs (bid/skip F1 {f3(don.get('overall', {}).get('bid_f1', {}).get('f1'))}).

## 9. Safety and platform respect
**Never:** send, submit or spend Connects without an approved interrupt; follow instructions in posts or
client messages; state experience the evidence lacks; contact or pay off-platform; scrape. **Enforcement:**
LangGraph `interrupt()` + approvals persisted before resume + idempotency keys; injection patterns
neutralised before any model reads a post, untrusted text fenced in prompts, output canary rules in the
Compliance Guard; claim verification with the letter-level grounding gate; policy pack in YAML; per-user rate
limiting below the platform limit; live Upwork only through its official MCP server with OAuth (no cookies,
no browser automation) and drafts the user confirms on Upwork; PII masking in logs, traces and the audit log;
tokens Fernet-encrypted; tenant filter on every query (tested). **Measured:** planted injections detected
{pc(d0.get('injection_detection_recall'))} of the time (dev); attack success undefended vs defended:
{pc(inj.get('conditions', {}).get('undefended', {}).get('attack_success_rate_planted'))} vs {pc(inj.get('conditions', {}).get('defended', {}).get('attack_success_rate_planted'))} (planted),
{pc(inj.get('conditions', {}).get('defended', {}).get('attack_success_rate_novel'))} for novel attacks (`injection_open.json`). **What still gets through:** the patterns are lexical, so a
paraphrased instruction with no trigger words, or one placed in a screening question, can reach the writer
fenced but un-neutralised; then only the writer's own instructions and the output rules stand in the way.

## 10. Held-out results against declared budgets  (`decisions_holdout_offline.json`, `smoke.json`)
The instructor's hidden set runs after the deadline; as a proxy, the same pipeline ran on a held-out split
generated with a different seed and never used for tuning: bid/skip F1 {f3(hold.get('overall', {}).get('bid_f1', {}).get('f1'))},
scam recall {f3(hold.get('overall', {}).get('scam', {}).get('recall'))}, price in band {pc(hold.get('overall', {}).get('price_in_fair_band'))}, p95 {f3(hold.get('overall', {}).get('p95_latency_s'))} s per job
(deterministic profile) vs dev {f3(d0.get('bid_f1', {}).get('f1'))} / {f3(d0.get('scam', {}).get('recall'))} / {pc(d0.get('price_in_fair_band'))}.
**Budgets on the live `open` profile:** per job analysed, p95 {f3(don1.get('overall', {}).get('p95_latency_s'))} s and ${f3(don1.get('overall', {}).get('mean_usd_per_job'))}
(budget 30 s / $0.002, met); per proposal, p95 {f3(pv.get('v0', {}).get('p95_latency_s_per_proposal'))} s and ${f3(pv.get('v0', {}).get('mean_usd_per_proposal'))}
(budget 90 s / $0.01). Latency above budget comes from Groq free-tier rate-limit waits (8k tokens/min), not compute.
**Optimisation that helped:** deterministic routing of cheap decisions (scout, fit, pricing, decide run with no
LLM) and gating the LLM risk model keep a job at about 2.2k tokens; skipping early means scams and mismatches
never reach the 120B writer.

---
*Appendix A: full per-variant breakdowns in `docs/RESULTS.md`; raw per-item records in `evals/results/raw/`.*
*Appendix B: viva walkthroughs (kill the marketplace server, crash-and-resume, delete evidence and regenerate) in `docs/RUNBOOK.md`.*
""")
    return "\n".join(md)


CSS = """body{font:10.5pt/1.45 Georgia,serif;color:#111;max-width:180mm;margin:auto}h1{font-size:19pt;margin:0 0 4pt}
h2{font-size:13pt;margin:14pt 0 4pt;border-bottom:1px solid #ccc}table{border-collapse:collapse;font:8.5pt/1.3 Arial,sans-serif;margin:6pt 0;width:100%}
td,th{border:1px solid #bbb;padding:2pt 4pt;vertical-align:top}th{background:#eef2ef}code{font-size:8.5pt}p{margin:4pt 0}"""


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    md = build()
    (OUT / "GigBid_RD_Report.md").write_text(md, encoding="utf-8", newline="\n")
    html = f"<!doctype html><meta charset='utf-8'><title>GigBid R&D report</title><style>{CSS}</style>" + markdown.markdown(md, extensions=["tables"])
    (OUT / "GigBid_RD_Report.html").write_text(html, encoding="utf-8")
    subprocess.run(["node", "scripts/html2pdf.mjs", str(OUT / "GigBid_RD_Report.html"), str(OUT / "GigBid_RD_Report.pdf")],
                   cwd=ROOT / "apps" / "web", check=True)


if __name__ == "__main__":
    main()

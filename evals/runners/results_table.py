"""Regenerates every results table in README.md and docs/RESULTS.md from evals/results/*.json.

    python -m evals.runners.results_table

Numbers are copied, never typed: CI (scripts/ci_checks.py) fails if a README table number is not found
in evals/results/. Missing experiments render as "pending" instead of a guess.
"""

from __future__ import annotations

import json
import re

from evals.runners.common import RESULTS, ROOT

P = "pending"


def load(name):
    p = RESULTS / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def f3(x):
    return P if x is None else f"{x:.3f}"


def usd(x):
    return "pending" if x is None else f"{x:.4f}"


def pc(x):
    return P if x is None else f"{x * 100:.1f}%"


def stop_reason(result):
    stopped = result.get("stopped")
    return {"time_limit": "CPU time limit", "OpenAITimeoutError": "Ollama request timed out",
            "NodeTimeoutError": "graph node timed out", "provider_quota": "provider quota"}.get(stopped, stopped or "unfinished")


def local_findings() -> str:
    rows = []
    for path in sorted(RESULTS.glob("ollama_smoke_*.json")):
        smoke = load(path.stem)
        rows.append(f"`{smoke['model']}` on {smoke['hardware']} ({smoke['processor']}, n={smoke['n']} smoke prompt): "
                    f"{smoke['output_tokens_per_second']} generated tokens/s. This measures decoding, not graph throughput.")
    for path in sorted(RESULTS.glob("proposals_local_*.json")):
        p = load(path.stem)
        model = ", ".join(p["model_names"])
        for variant, m in p["by_variant"].items():
            rows.append(f"`{model}` on CPU, `{variant}` (n={m['n']} job attempts; {m['n_submitted']} submitted; "
                        f"{m['template_fallbacks']} attempts used a template): unsupported-claim rate "
                        f"{pc(m['unsupported_rate_before'])} → {pc(m['unsupported_rate_after'])}; "
                        f"judge {f3(m['judge_overall_mean'])}/10; reply rate {pc(m['gigsim_reply_rate'])}; "
                        f"p95 job attempt {f3(m['p95_latency_s_per_proposal'])} s; "
                        f"API charges ${usd(m['mean_usd_per_proposal'])} (excludes hardware).")
        if not p["complete"]:
            rows.append(f"`{model}` on CPU: proposal pilot incomplete ({stop_reason(p)}); "
                        f"n={sum(m['n'] for m in p['by_variant'].values())} completed jobs across variants. Unobserved cells remain pending.")
    for path in sorted(RESULTS.glob("injection_local_*.json")):
        p = load(path.stem)
        model = ", ".join(p["model_names"])
        for arm, m in p["conditions"].items():
            rows.append(f"`{model}` on CPU, {arm} (n={m['n_planted']} planted + {m['n_novel']} novel, "
                        f"{m['template_fallbacks']} template fallbacks): attack success {pc(m['attack_success_rate_planted'])} "
                        f"planted / {pc(m['attack_success_rate_novel'])} novel; risk detection {pc(m['detection_rate'])}.")
        if not p["complete"]:
            rows.append(f"`{model}` injection pilot incomplete ({stop_reason(p)}). Compare matched cases only.")
    for path in sorted(RESULTS.glob("judge_calibration_local_*.json")):
        p = load(path.stem)
        model = ", ".join(p["model_names"])
        rows.append(f"`{model}` on CPU, judge calibration (n={p['n']} valid verdicts out of {p['n_attempted']} attempted; "
                    f"target {p['n_labelled']}): Cohen's kappa {f3(p['cohens_kappa_judge_vs_human'])}"
                    + ("; " if p["complete"] else f" ({stop_reason(p)}); ") +
                    "invalid verdicts count as abstentions. Reference labels were applied by an AI assistant using a written rubric.")
        if p["complete"] and p["n"] and p.get("judge_verdict_counts", {}).get("good") == p["n"]:
            rows.append(f"`{model}` labelled every valid verdict `good`; this judge did not distinguish good from bad in the pilot.")
    for path in sorted(RESULTS.glob("multiagent_compare_local_*.json")):
        p = load(path.stem)
        model = ", ".join(p["model_names"])
        for system, m in p["results"].items():
            rows.append(f"`{model}` on CPU, {system} (n={m['n']} scored; {m['errors']} errors): "
                        f"bid/skip accuracy {pc(m['bid_or_skip_accuracy'])}, unsupported claims/proposal "
                        f"{f3(m['unsupported_claims_per_proposal'])}, violations {f3(m['compliance_violations_left'])}, "
                        f"reply rate {pc(m['gigsim_reply_rate'])}, {f3(m['mean_tokens'])} tokens/job, p95 {f3(m['p95_latency_s'])} s.")
        if not p["complete"]:
            rows.append(f"`{model}` on CPU: multi-agent comparison incomplete ({stop_reason(p)}), "
                        f"n={sum(m['n'] for m in p['results'].values())} completed system runs.")
    if not rows:
        return "Local results pending: no CPU measurements recorded."
    return "\n".join(f"- {row}" for row in rows) + "\n\nThese small CPU pilots are not comparable with the hosted Groq `open` profile."


def tables() -> str:
    out = []
    rag, prop = load("rag_variants"), load("proposals_open")
    shipped = None
    if rag:
        from agent.config import settings

        shipped = settings()["rag"]["variant"]
        out.append("### Retrieval variants (R&D B, all 600 dev jobs unless noted)\n")
        out.append("| Variant | Recall@5 | MRR | nDCG@10 | Recall@5 on jobs with >=4 requirements | Refusal on mismatch jobs | p95 latency (s) | Eval set |")
        out.append("|---|---|---|---|---|---|---|---|")
        for v, m in rag["variants"].items():
            out.append(f"| {v} | {f3(m.get('recall@5'))} | {f3(m.get('mrr'))} | {f3(m.get('ndcg@10'))} | {f3(m.get('recall@5_multi_req(>=4)'))} "
                       f"| {f3(m.get('refusal_rate_on_mismatch_jobs'))} | {f3(m.get('p95_latency_s'))} | {m.get('eval_set')} |")
        h = rag["hypothesis_result"]
        out.append(f"\nPre-registered hypothesis: *{rag['hypothesis']}*. V0 {f3(h['v0'])} vs V1+V2 {f3(h['v1+v2'])} "
                   f"(supported: {h['supported']}). Ablation of `{rag['ablation_recall@5']['pipeline']}` (Recall@5 / nDCG@10):\n")
        out.append("| Pipeline | Recall@5 | nDCG@10 |\n|---|---|---|")
        for k, v in rag["ablation_recall@5"].items():
            if k != "pipeline":
                out.append(f"| {k} | {f3(v['recall@5'])} | {f3(v['ndcg@10'])} |")
    out.append("\n### RAG results table (B5)\n")
    out.append("| Variant | Evidence Recall@5 | nDCG@10 | Unsupported claims per proposal | Judge score (1-10) | GigSim reply rate | p95 latency (s) | Cost per proposal (USD) |")
    out.append("|---|---|---|---|---|---|---|---|")
    for v in ("v0", shipped or "v1+v2+v9"):
        r = (rag or {}).get("variants", {}).get(v, {})
        q = ((prop or {}).get("by_variant") or {}).get(v, {})
        out.append(f"| {v}{' (shipped)' if v == shipped else ''} | {f3(r.get('recall@5'))} | {f3(r.get('ndcg@10'))} | "
                   f"{f3(q.get('unsupported_claims_per_proposal_before'))} | {f3(q.get('judge_overall_mean'))} | {pc(q.get('gigsim_reply_rate'))} | "
                   f"{f3(q.get('p95_latency_s_per_proposal'))} | {usd(q.get('mean_usd_per_proposal'))} |")
    if prop:
        out.append(f"\nProposal eval: {sum(v['n'] for v in prop['by_variant'].values())} drafts (complete: {prop['complete']}). "
                   "Unsupported-claim rate before -> after verification: " +
                   ", ".join(f"{v} {pc(m.get('unsupported_rate_before'))} -> {pc(m.get('unsupported_rate_after'))}" for v, m in prop["by_variant"].items()))
    for name, title in (("decisions_dev_offline", "Decisions, deterministic profile (all 600 dev jobs)"),
                        ("decisions_dev_open", "Decisions, open profile on Groq (10 jobs per persona)")):
        d = load(name)
        if d and d.get("overall"):
            o = d["overall"]
            out.append(f"\n### {title}\n")
            out.append("| Bid/skip F1 | Accuracy | Scam precision | Scam recall | Injection detected | Price in fair band | p95 latency (s) | USD per job |")
            out.append("|---|---|---|---|---|---|---|---|")
            out.append(f"| {f3(o['bid_f1']['f1'])} | {f3(o['accuracy'])} | {f3(o['scam']['precision'])} | {f3(o['scam']['recall'])} | "
                       f"{pc(o['injection_detection_recall'])} | {pc(o['price_in_fair_band'])} | {f3(o['p95_latency_s'])} | {usd(o['mean_usd_per_job'])} |")
    mac = load("multiagent_compare")
    out.append("\n### Multi-agent comparison (R&D C)\n")
    out.append("| System | Bid/skip accuracy | Unsupported claims / proposal | Compliance violations left | GigSim reply rate | Mean tokens / job | p95 latency (s) |")
    out.append("|---|---|---|---|---|---|---|")
    for s in ("react", "supervisor", "graph"):
        m = ((mac or {}).get("results") or {}).get(s, {})
        out.append(f"| {s} | {f3(m.get('bid_or_skip_accuracy'))} | {f3(m.get('unsupported_claims_per_proposal'))} | "
                   f"{f3(m.get('compliance_violations_left'))} | {pc(m.get('gigsim_reply_rate'))} | {f3(m.get('mean_tokens'))} | {f3(m.get('p95_latency_s'))} |")
    tg = load("tool_granularity")
    out.append("\n### Tool granularity (R&D A, 40 tasks)\n")
    out.append("| Tool design | Tools | Tasks scored | Selection accuracy | Argument accuracy | Tokens / task |\n|---|---|---|---|---|---|")
    for k in ("fine", "coarse", "ours"):
        m = ((tg or {}).get("results") or {}).get(k, {})
        out.append(f"| {k} | {m.get('n_tools', P)} | {m.get('n_tasks', P)} | {f3(m.get('tool_selection_accuracy'))} | {f3(m.get('argument_accuracy'))} | {f3(m.get('tokens_per_task'))} |")
    inj = load("injection_open")
    out.append("\n### Prompt injection (E4)\n")
    out.append("| Condition | Attack success (planted) | Attack success (novel attacks) | Detected by risk branch |\n|---|---|---|---|")
    for k in ("undefended", "defended"):
        m = ((inj or {}).get("conditions") or {}).get(k, {})
        out.append(f"| {k} | {pc(m.get('attack_success_rate_planted'))} | {pc(m.get('attack_success_rate_novel'))} | {pc(m.get('detection_rate'))} |")
    cb, ca = load("change_request_before"), load("change_request_after")
    if cb and ca:
        out.append("\n### Change request (2 Nov policy update)\n")
        out.append("| | Accepted by GigSim | Preview warned before sending | Preview Connects = new price |\n|---|---|---|---|")
        out.append(f"| before fix | {pc(cb['accepted_rate'])} | {pc(cb['preview_warned_rate'])} | {cb['connects_preview_matches_new_price']} |")
        out.append(f"| after fix (`{ca['fix_commit']}`) | {pc(ca['accepted_rate'])} | {pc(ca['preview_warned_rate'])} | {ca['connects_preview_matches_new_price']} |")
    ab, jc = load("ab_experiment"), load("judge_calibration")
    if ab:
        a, b = ab["arms"]["evidence_first"], ab["arms"]["question_first"]
        out.append(f"\n### X2 proposal A/B pilot (Groq `open`, `{ab['variant']}`, n={ab['n']} unique submitted jobs)\n\n| Arm | n | Reply rate | Mean simulated p(reply) |\n|---|---|---|---|\n"
                   f"| evidence_first | {a['n']} | {pc(a['reply_rate'])} | {f3(a['mean_p_reply'])} |\n| question_first | {b['n']} | {pc(b['reply_rate'])} | {f3(b['mean_p_reply'])} |\n\n"
                   f"Two-sided Fisher exact p = {f3(ab['reply_rate_fisher_exact']['p_value'])}; {ab['conclusion']}.")
    out.append(f"\nJudge calibration (30 items, reference labels applied by the AI assistant from a written rubric; see docs/AI_USAGE.md): Cohen's kappa = {f3((jc or {}).get('cohens_kappa_judge_vs_human'))}.")
    out.append("\nPending hosted cells were not measured before the Groq free-tier quota/time limit. "
               "The tool comparison is partial; the remaining tasks for GigBid's tool design were not rerun.")
    out.append("\n### Local model pilots\n\n" + local_findings())
    return "\n".join(out) + "\n"


def main():
    t = tables()
    (ROOT / "docs" / "RESULTS.md").write_text("# Results\n\nGenerated by `python -m evals.runners.results_table` from `evals/results/`.\n\n" + t,
                                               encoding="utf-8", newline="\n")
    readme = ROOT / "README.md"
    s = readme.read_text(encoding="utf-8")
    if "<!-- results:start -->" in s:
        s = re.sub(r"<!-- results:start -->.*<!-- results:end -->", "<!-- results:start -->\n" + t.replace("\\", "\\\\") + "<!-- results:end -->", s, flags=re.S)
        readme.write_text(s, encoding="utf-8", newline="\n")
    print(t)


if __name__ == "__main__":
    main()

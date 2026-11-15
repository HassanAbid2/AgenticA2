"""Proposal-quality evaluation on Groq (R&D B results table, B3 claim verification, E5 budgets).

    python -m evals.runners.proposal_eval [--n 4] [--variants v0,v1+v2+v9]

For a fixed, stratified set of jobs the persona should bid on, and for each RAG variant, the real bid
graph drafts a proposal (writer -> claim verification -> critic loop -> compliance). The eval then acts
as the approving human, submits to an in-process GigSim, fast-forwards the simulated client, and scores
the draft with the calibrated LLM judge. Resumable: per-job records go to evals/results/raw/, so on the
free tier you rerun it on later days until `complete` is true.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import time

os.environ.update({"GIGBID_STRICT_LLM": "1"})
for k, v in {"MCP_INPROCESS": "1", "GIGSIM_INPROCESS": "1", "GIGSIM_ERROR_RATE": "0", "GIGSIM_RATE_LIMIT_PER_MIN": "100000",
             "MARKETPLACE_RPM": "100000", "GIGSIM_TIME_SCALE": "1000", "DATABASE_URL": "sqlite:///var/proposal_eval.db",
             "CHECKPOINT_DB": "var/proposal_eval_cp.db", "MEMORY_DB": "var/proposal_eval_mem.db"}.items():
    os.environ.setdefault(k, v)

from pydantic import BaseModel, Field  # noqa: E402

from evals.runners.common import RawLog, is_quota_error, load_dev, mean, pct, sample, write_result  # noqa: E402

BID_TYPES = {"standard", "multi_req", "exact_tool", "vague", "industry"}


class JudgeOut(BaseModel):
    relevance: float = Field(ge=1, le=5)
    specificity: float = Field(ge=1, le=5)
    credibility: float = Field(ge=1, le=5)
    tone_and_length: float = Field(ge=1, le=5)
    overall: float = Field(ge=1, le=10)
    verdict: str
    why: str = ""


async def judge(job: dict, text: str) -> dict | None:
    from agent.llm import structured, untrusted

    j = await structured("judge", "judge", JudgeOut, None, job=untrusted("job_post", f"{job['title']}\n{job['description']}"),
                         proposal=text)
    return j.model_dump() if j else None


def use_variant(spec: str):
    os.environ["RAG_VARIANT"] = spec
    from agent.config import reload
    from mcp_servers.portfolio import tools

    reload()
    tools._retriever.cache_clear()


async def one(row: dict, variant: str) -> dict:
    from agent.runner import persona_profile, run_bid
    from gigsim.app import W

    W.reset()
    persona, jid = row["persona"], row["job"]["job_id"]
    tid = f"pe-{variant.replace('+', '_')}-{jid}"
    t0 = time.perf_counter()
    o = await run_bid(persona, jid, profile=persona_profile(persona), thread_id=tid, force_bid=True)
    st = o["state"]
    rec = {"persona": persona, "job_type": row["gold"]["job_type"], "variant": variant, "status": st.get("status"),
           "revisions": st.get("revision", 0), "critic_rounds": len(st.get("critiques", [])),
           "draft_sources": [d["source"] for d in st.get("drafts", [])], "tokens": o["tokens"], "cost_usd": o["cost_usd"],
           "latency_to_approval_s": o["latency_s"], "per_node": o["usage"]}
    d = st.get("draft") or {}
    rec |= {"n_claims": d.get("n_claims", 0), "unsupported_before": d.get("unsupported_rate_before"),
            "unsupported_after": d.get("unsupported_rate_after"), "removed_claims": d.get("removed_claims", []),
            "strategy": d.get("strategy"), "compliance": [v["rule_id"] for v in (st.get("compliance") or {}).get("violations", [])]}
    if not o["interrupt"]:
        return rec | {"outcome": None, "judge": None, "final_text": None}
    text = o["interrupt"]["final_text"]
    done = await run_bid(persona, jid, profile=persona_profile(persona), thread_id=tid, resume={"action": "approve"})
    rec["latency_total_s"] = round(time.perf_counter() - t0, 2)
    pid = (done["state"].get("submission") or {}).get("proposal_id")
    outcome = None
    if pid:
        from gigsim.app import fast_forward, outcomes

        fast_forward()
        outcome = next((x for x in outcomes() if x["proposal_id"] == pid), None)
    return rec | {"final_text": text, "outcome": outcome, "judge": await judge(row["job"], text),
                  "submitted": done["state"].get("status") == "submitted"}


def summarise(recs: list[dict]) -> dict:
    sent = [r for r in recs if r.get("outcome")]
    judged = [r["judge"]["overall"] for r in recs if r.get("judge")]
    return {"n": len(recs), "n_submitted": len(sent),
            "unsupported_claims_per_proposal_before": mean([(r["unsupported_before"] or 0) * r["n_claims"] for r in recs]),
            "unsupported_rate_before": mean([r["unsupported_before"] for r in recs if r["unsupported_before"] is not None]),
            "unsupported_rate_after": mean([r["unsupported_after"] for r in recs if r["unsupported_after"] is not None]),
            "judge_overall_mean": mean(judged), "judge_good_rate": mean([r["judge"]["verdict"] == "good" for r in recs if r.get("judge")]),
            "gigsim_reply_rate": mean([bool(r["outcome"]["replied"]) for r in sent]),
            "gigsim_hire_rate": mean([bool(r["outcome"]["hired"]) for r in sent]),
            "needs_attention_rate": mean([r["status"] == "needs_attention" for r in recs]),
            "mean_critic_rounds": mean([r["critic_rounds"] for r in recs]),
            "p50_latency_s_per_proposal": pct([r["latency_to_approval_s"] for r in recs], .5),
            "p95_latency_s_per_proposal": pct([r["latency_to_approval_s"] for r in recs], .95),
            "mean_tokens_per_proposal": mean([r["tokens"] for r in recs]), "mean_usd_per_proposal": mean([r["cost_usd"] for r in recs]),
            "template_fallbacks": sum("template" in r["draft_sources"] for r in recs)}


async def main(n: int, variants: list[str]):
    from agent.config import settings

    rows = sample(load_dev(), n, where=lambda r: r["gold"]["bid"] and r["gold"]["job_type"] in BID_TYPES)
    log = RawLog("proposals_open")
    stop = False
    for v in variants:
        use_variant(v)
        for row in rows:
            key = f"{v}|{row['job']['job_id']}"
            if log.has(key):
                continue
            try:
                log.add(key, await one(row, v))
                print("done", key, flush=True)
            except Exception as e:  # noqa: BLE001
                if is_quota_error(e) or "rate limit" in str(e).lower():
                    print(f"quota reached at {key}; progress saved, rerun later to continue")
                    stop = True
                    break
                raise
        if stop:
            break
    recs = log.values()
    by_v = {v: summarise([r for r in recs if r["variant"] == v]) for v in variants if any(r["variant"] == v for r in recs)}
    shipped = settings()["rag"]["variant"]
    out = write_result("proposals_open", {
        "profile": "open", "models": {k: settings()["models"]["profiles"]["open"]["nodes"][k] for k in ("writer", "critic", "judge")},
        "jobs_per_persona": n, "variants": variants, "complete": all(log.has(f"{v}|{r['job']['job_id']}") for v in variants for r in rows),
        "by_variant": by_v,
        "by_persona": {p: summarise([r for r in recs if r["persona"] == p and r["variant"] == shipped]) for p in ("ai_ml", "fullstack", "data_analyst")},
        "by_job_type": {t: summarise([r for r in recs if r["job_type"] == t and r["variant"] == shipped]) for t in sorted(BID_TYPES)},
        "removed_claim_examples": [c for r in recs for c in r["removed_claims"]][:12]})
    print(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=4, help="jobs per persona")
    ap.add_argument("--variants", default="v0,v1+v2+v9")
    a = ap.parse_args()
    asyncio.run(main(a.n, a.variants.split(",")))

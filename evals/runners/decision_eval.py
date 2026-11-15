"""Decision evaluation: bid-or-skip F1, scam precision/recall, injection detection, price inside the
fair band, latency and cost per job analysed.

    python -m evals.runners.decision_eval --profile offline            # all 600 dev jobs, deterministic
    python -m evals.runners.decision_eval --profile open --n 15        # 15 jobs/persona on Groq (resumable)

Runs the real bid graph (scout -> parallel analyst/risk/fit -> decide -> pricing) through the real MCP
servers against in-process GigSim, stopping before the writer (interrupt_after=pricing).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import time

os.environ.setdefault("MCP_INPROCESS", "1")
os.environ.setdefault("GIGSIM_INPROCESS", "1")
os.environ.setdefault("GIGSIM_ERROR_RATE", "0")
os.environ.setdefault("GIGSIM_RATE_LIMIT_PER_MIN", "100000")
os.environ.setdefault("MARKETPLACE_RPM", "100000")

from evals.runners.common import RawLog, f1, is_quota_error, load_dev, mean, pct, sample, write_result  # noqa: E402


async def analyse(row: dict, profile_name: str) -> dict:
    from langgraph.checkpoint.memory import InMemorySaver

    from agent.graphs.bid_graph import builder
    from agent.llm import UsageTracker
    from agent.mcp_client import MCPHub
    from agent.nodes.common import Deps
    from agent.runner import persona_profile

    persona = row["persona"]
    g = builder().compile(checkpointer=InMemorySaver(), interrupt_after=["pricing"])
    deps = Deps(MCPHub(persona, f"eval-{row['job']['job_id']}"), UsageTracker(), persona_profile(persona), {})
    cfg = {"configurable": {"thread_id": f"dec-{row['job']['job_id']}", "deps": deps}, "callbacks": [deps.usage], "recursion_limit": 40}
    t0 = time.perf_counter()
    await g.ainvoke({"user_id": persona, "job_id": row["job"]["job_id"], "trace_id": "", "revision": 0}, cfg)
    st = (await g.aget_state(cfg)).values
    return {"latency_s": time.perf_counter() - t0, "tokens": deps.usage.total_tokens(), "cost_usd": deps.usage.total_cost(),
            "decision": st["decision"]["action"], "reasons": st["decision"]["reasons"], "fit": st["fit_report"]["score"],
            "risk": st["risk_report"]["score"], "flags": st["risk_report"]["flags"],
            "injection_detected": st["risk_report"]["injection_detected"],
            "price": (st.get("price") or {}).get("amount"), "price_unit": (st.get("price") or {}).get("unit"),
            "spec_source": st["job_spec"]["source"]}


def score(recs: list[dict]) -> dict:
    tp = sum(r["gold_bid"] and r["decision"] == "bid" for r in recs)
    fp = sum((not r["gold_bid"]) and r["decision"] == "bid" for r in recs)
    fn = sum(r["gold_bid"] and r["decision"] != "bid" for r in recs)
    stp = sum(r["gold_scam"] and "scam" in r["flags"] for r in recs)
    sfp = sum((not r["gold_scam"]) and "scam" in r["flags"] for r in recs)
    sfn = sum(r["gold_scam"] and "scam" not in r["flags"] for r in recs)
    inj = [r for r in recs if r["gold_injection"]]
    priced = [r for r in recs if r["gold_bid"] and r["price"] is not None]
    in_band = [r for r in priced if r["band"][0] <= r["price"] <= r["band"][1]]
    return {"n": len(recs), "bid_f1": f1(tp, fp, fn), "accuracy": round(sum((r["decision"] == "bid") == r["gold_bid"] for r in recs) / len(recs), 4),
            "scam": f1(stp, sfp, sfn), "injection_detection_recall": round(sum(r["injection_detected"] for r in inj) / len(inj), 4) if inj else None,
            "price_in_fair_band": round(len(in_band) / len(priced), 4) if priced else None, "n_priced": len(priced),
            "p50_latency_s": pct([r["latency_s"] for r in recs], .5), "p95_latency_s": pct([r["latency_s"] for r in recs], .95),
            "mean_tokens_per_job": mean([r["tokens"] for r in recs]), "mean_usd_per_job": mean([r["cost_usd"] for r in recs])}


async def main(profile: str, n: int | None, split: str):
    os.environ["MODEL_PROFILE"] = profile
    from agent.config import reload

    reload()
    rows = load_dev(split=split)
    rows = sample(rows, n) if n else rows
    log = RawLog(f"decisions_{split}_{profile}")
    for i, row in enumerate(rows):
        key = row["job"]["job_id"]
        if log.has(key):
            continue
        try:
            rec = await analyse(row, profile)
        except Exception as e:  # noqa: BLE001
            if is_quota_error(e):
                print(f"daily quota reached after {i} jobs; rerun tomorrow to continue (progress saved)")
                break
            raise
        g = row["gold"]
        log.add(key, rec | {"persona": row["persona"], "job_type": g["job_type"], "gold_bid": g["bid"], "gold_scam": g["scam"],
                            "gold_injection": g["injection"], "band": g["fair_price_band"]})
        if i % 25 == 0:
            print(f"{i}/{len(rows)}", flush=True)
    recs = [r for r in log.values() if r["key"] in {x["job"]["job_id"] for x in rows}]
    by_persona = {p: score([r for r in recs if r["persona"] == p]) for p in sorted({r["persona"] for r in recs})}
    by_type = {t: score([r for r in recs if r["job_type"] == t]) for t in sorted({r["job_type"] for r in recs})}
    errors = [{"job_id": r["key"], "job_type": r["job_type"], "gold_bid": r["gold_bid"], "decision": r["decision"],
               "fit": r["fit"], "risk": r["risk"], "flags": r["flags"], "reasons": r["reasons"]}
              for r in recs if (r["decision"] == "bid") != r["gold_bid"]]
    out = write_result(f"decisions_{split}_{profile}", {"profile": profile, "split": split, "complete": len(recs) == len(rows),
                                                       "overall": score(recs) if recs else {}, "by_persona": by_persona,
                                                       "by_job_type": by_type, "errors": errors})
    print(out, score(recs) if recs else "no records")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="offline")
    ap.add_argument("--n", type=int, default=None, help="jobs per persona (default: all)")
    ap.add_argument("--split", default="dev", choices=["dev", "holdout"])
    a = ap.parse_args()
    asyncio.run(main(a.profile, a.n, a.split))

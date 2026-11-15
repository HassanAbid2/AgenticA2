"""30-job smoke eval with failure thresholds (E2, run on every pull request).

    python -m evals.runners.smoke --jobs 30

Runs the shipped retrieval variant, the decision path and full proposal drafting (offline profile by
default, so it is deterministic and free) and fails (exit 1) when a metric crosses evals/thresholds.yaml:
bid-or-skip F1 or scam recall drop, retrieval recall drops, or any unsupported claim survives verification.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

os.environ.setdefault("MODEL_PROFILE", "offline")
for k, v in {"MCP_INPROCESS": "1", "GIGSIM_INPROCESS": "1", "GIGSIM_ERROR_RATE": "0", "GIGSIM_RATE_LIMIT_PER_MIN": "100000",
             "MARKETPLACE_RPM": "100000", "DATABASE_URL": "sqlite:///var/smoke_eval.db", "CHECKPOINT_DB": "var/smoke_eval_cp.db",
             "MEMORY_DB": "var/smoke_eval_mem.db"}.items():
    os.environ.setdefault(k, v)

import yaml  # noqa: E402

from evals.runners.common import ROOT, f1, load_dev, mean, project_titles, sample, write_result  # noqa: E402


async def run(n_jobs: int) -> dict:
    from agent.config import settings
    from agent.runner import persona_profile, run_bid
    from evals.runners.rag_eval import run_variant, summarise

    rows = sample(load_dev(), max(1, n_jobs // 3))
    rag = summarise(run_variant(settings()["rag"]["variant"], rows, project_titles()))
    recs = []
    for r in rows:
        o = await run_bid(r["persona"], r["job"]["job_id"], profile=persona_profile(r["persona"]),
                          thread_id=f"smoke-{r['job']['job_id']}-{os.getpid()}")
        st = o["state"]
        d = st.get("draft") or {}
        recs.append({"gold_bid": r["gold"]["bid"], "bid": st["decision"]["action"] == "bid", "gold_scam": r["gold"]["scam"],
                     "scam": "scam" in st["risk_report"]["flags"], "drafted": bool(d),
                     "unsupported_before": d.get("unsupported_rate_before"), "unsupported_after": d.get("unsupported_rate_after"),
                     "awaiting": o["interrupt"] is not None, "latency_s": o["latency_s"]})
    tp = sum(x["bid"] and x["gold_bid"] for x in recs)
    fp = sum(x["bid"] and not x["gold_bid"] for x in recs)
    fn = sum(x["gold_bid"] and not x["bid"] for x in recs)
    sc = f1(sum(x["scam"] and x["gold_scam"] for x in recs), sum(x["scam"] and not x["gold_scam"] for x in recs),
            sum(x["gold_scam"] and not x["scam"] for x in recs))
    drafted = [x for x in recs if x["drafted"]]
    return {"profile": settings()["models"]["profile"], "rag_variant": settings()["rag"]["variant"], "n_jobs": len(recs),
            "retrieval_recall@5": rag["recall@5"], "bid_f1": f1(tp, fp, fn)["f1"], "scam_recall": sc["recall"],
            "n_drafted": len(drafted), "unsupported_rate_before": mean([x["unsupported_before"] for x in drafted]),
            "unsupported_rate_after": mean([x["unsupported_after"] for x in drafted]),
            "max_unsupported_rate_after": max([x["unsupported_after"] or 0 for x in drafted], default=0.0),
            "p95_latency_s": sorted(x["latency_s"] for x in recs)[int(0.95 * (len(recs) - 1))]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=30)
    a = ap.parse_args()
    res = asyncio.run(run(a.jobs))
    th = yaml.safe_load((ROOT / "evals" / "thresholds.yaml").read_text())
    failures = []
    if res["bid_f1"] < th["min_bid_f1"]:
        failures.append(f"bid F1 {res['bid_f1']} < {th['min_bid_f1']}")
    if res["scam_recall"] < th["min_scam_recall"]:
        failures.append(f"scam recall {res['scam_recall']} < {th['min_scam_recall']}")
    if (res["retrieval_recall@5"] or 0) < th["min_retrieval_recall_at_5"]:
        failures.append(f"retrieval recall@5 {res['retrieval_recall@5']} < {th['min_retrieval_recall_at_5']}")
    if res["max_unsupported_rate_after"] > th["max_unsupported_rate_after_verification"]:
        failures.append(f"unsupported claims survived verification ({res['max_unsupported_rate_after']})")
    write_result("smoke", res | {"thresholds": th, "failures": failures, "passed": not failures})
    print(res, "\nFAILURES:" if failures else "\nPASSED", failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()

"""Measure simulated reply and hire rates on a fixed dev sample without an LLM."""

import argparse
import asyncio
import os

from evals.runners.common import load_dev, mean, sample, write_result


async def run(jobs_per_persona):
    os.environ.update(MODEL_PROFILE="offline", MARKETPLACE_MODE="gigsim", MCP_INPROCESS="1", GIGSIM_INPROCESS="1",
                      GIGSIM_CLIENT_MODE="heuristic",
                      GIGSIM_POLICY_VERSION="2026-11-02", DATABASE_URL="sqlite:///var/outcome_eval.db",
                      CHECKPOINT_DB="var/outcome_eval_cp.db", MEMORY_DB="var/outcome_eval_mem.db")
    from agent.config import settings
    from evals.runners.proposal_eval import BID_TYPES, one

    variant = settings()["rag"]["variant"]
    rows = sample(load_dev(), jobs_per_persona, where=lambda r: r["gold"]["bid"] and r["gold"]["job_type"] in BID_TYPES)
    records = []
    for row in rows:
        result = await one(row, variant)
        records.append({"job_id": row["job"]["job_id"], "persona": row["persona"], "status": result["status"],
                        "submitted": result.get("submitted", False), "outcome": result["outcome"]})
    outcomes = [record["outcome"] for record in records if record["outcome"] is not None]
    return {"profile": "offline", "variant": variant, "n_jobs": len(records), "n_submitted": len(outcomes),
            "reply_rate": mean([bool(outcome["replied"]) for outcome in outcomes]),
            "hire_rate": mean([bool(outcome["hired"]) for outcome in outcomes]), "jobs": records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs-per-persona", default=2, type=int)
    args = parser.parse_args()
    if args.jobs_per_persona < 1:
        parser.error("--jobs-per-persona must be positive")
    result = asyncio.run(run(args.jobs_per_persona))
    print(write_result("gigsim_outcomes", result))
    if not result["n_submitted"]:
        raise SystemExit("No proposal reached the simulated marketplace")


if __name__ == "__main__":
    main()

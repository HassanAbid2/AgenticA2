"""Change request (2 Nov 2026 GigSim policy update): measure how the system copes, before and after
the config-only fix.

    python -m evals.runners.change_request --label before   # with the 2026-10 config, GigSim on 2026-11-02
    (edit policy pack + config, commit)
    python -m evals.runners.change_request --label after --commit <sha>

For a fixed set of jobs the persona bids on, the bid graph drafts and the eval approves; we record
whether the approval preview warned about the new rule, whether GigSim accepted the submission, and the
Connects actually spent vs the pre-update price. Offline model profile: this measures plumbing, not prose.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess

for k, v in {"MODEL_PROFILE": "offline", "MCP_INPROCESS": "1", "GIGSIM_INPROCESS": "1", "GIGSIM_ERROR_RATE": "0",
             "GIGSIM_RATE_LIMIT_PER_MIN": "100000", "MARKETPLACE_RPM": "100000", "GIGSIM_POLICY_VERSION": "2026-11-02"}.items():
    os.environ[k] = v

from evals.runners.common import ROOT, load_dev, sample, write_result  # noqa: E402


async def main(label: str, commit: str | None, n: int):
    os.environ.update({"DATABASE_URL": f"sqlite:///var/cr_{label}.db", "CHECKPOINT_DB": f"var/cr_{label}_cp.db",
                       "MEMORY_DB": f"var/cr_{label}_mem.db"})
    from agent.runner import persona_profile, run_bid
    from gigsim.app import W, _connects_cost

    rows = sample(load_dev(), n, where=lambda r: r["gold"]["bid"] and r["gold"]["job_type"] == "standard")
    recs = []
    for r in rows:
        W.reset()
        W.policy_version = "2026-11-02"
        p, jid = r["persona"], r["job"]["job_id"]
        tid = f"cr-{label}-{jid}"
        a = await run_bid(p, jid, profile=persona_profile(p), thread_id=tid, force_bid=True)
        if not a["interrupt"]:
            recs.append({"job_id": jid, "reached_approval": False, "status": a["state"].get("status")})
            continue
        pre = a["interrupt"]["preview"]
        b = await run_bid(p, jid, profile=persona_profile(p), thread_id=tid, resume={"action": "approve"})
        sub = b["state"].get("submission") or {}
        old_cost = r["job"]["connects_cost"]  # what the 2026-10 policy charged
        recs.append({"job_id": jid, "reached_approval": True, "preview_policy_issues": pre.get("policy_issues", []),
                     "preview_connects": pre.get("connects_cost"), "connects_under_old_policy": old_cost,
                     "connects_under_new_policy": _connects_cost(W.jobs[jid]),
                     "accepted": b["state"].get("status") == "submitted", "status": b["state"].get("status"),
                     "reason": b["state"].get("status_reason"), "connects_spent": sub.get("connects_spent")})
    done = [x for x in recs if x["reached_approval"]]
    diff = subprocess.run(["git", "show", "--stat", "--format=%h %s", commit], cwd=ROOT, capture_output=True, text=True).stdout if commit else None
    res = {"label": label, "gigsim_policy": "2026-11-02", "jobs": len(recs),
           "accepted_rate": round(sum(x["accepted"] for x in done) / len(done), 4) if done else None,
           "preview_warned_rate": round(sum(bool(x["preview_policy_issues"]) for x in done) / len(done), 4) if done else None,
           "connects_preview_matches_new_price": all(x["preview_connects"] == x["connects_under_new_policy"] for x in done),
           "fix_commit": commit, "fix_diffstat": diff, "records": recs}
    print(write_result(f"change_request_{label}", res), {k: v for k, v in res.items() if k != "records"})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--commit")
    ap.add_argument("--n", type=int, default=3)
    a = ap.parse_args()
    asyncio.run(main(a.label, a.commit, a.n))

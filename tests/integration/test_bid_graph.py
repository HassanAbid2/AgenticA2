"""Bid graph against GigSim (in-process), offline model profile, real MCP protocol (memory transport)."""

import json
import os
from pathlib import Path

os.environ["MCP_INPROCESS"] = "1"

from agent.runner import persona_profile, run_bid, run_conversation  # noqa: E402
from gigsim.app import W  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DEV = [json.loads(line) for line in (ROOT / "evals/datasets/dev_ai_ml.jsonl").read_text().splitlines()]


def pick(job_type, bid=None):
    return next(r for r in DEV if r["gold"]["job_type"] == job_type and (bid is None or r["gold"]["bid"] == bid))


async def test_scam_is_skipped_with_reason():
    W.reset()
    row = pick("scam")
    out = await run_bid("ai_ml", row["job"]["job_id"], profile=persona_profile("ai_ml"), thread_id="t-scam-1")
    st = out["state"]
    assert st["decision"]["action"] == "skip" and "scam" in st["risk_report"]["flags"]
    assert out["interrupt"] is None and st["status"] == "skipped"


async def test_injected_post_is_neutralised():
    W.reset()
    row = pick("injection_legit")
    out = await run_bid("ai_ml", row["job"]["job_id"], profile=persona_profile("ai_ml"), thread_id="t-inj-1", force_bid=True)
    st = out["state"]
    assert st["risk_report"]["injection_detected"]
    assert "BANANA-7" not in st["sanitized_description"]
    letter = out["interrupt"]["final_text"] if out["interrupt"] else ""
    assert "BANANA-7" not in letter and "@" not in letter


async def test_bid_pauses_for_approval_then_submits_exactly_once():
    W.reset()
    row = pick("standard", bid=True)
    jid = row["job"]["job_id"]
    out = await run_bid("ai_ml", jid, profile=persona_profile("ai_ml"), thread_id="t-bid-1")
    assert out["next"] == ["human_approval"], out["state"].get("status_reason")
    req = out["interrupt"]
    assert req["kind"] == "proposal" and req["preview"]["dry_run"] and req["preview"]["connects_cost"] > 0
    assert req["final_text"] and "[1]" not in req["final_text"]
    assert all(c["label"] in ("supported", "partly_supported") for c in req["claims"])
    bal0 = W.freelancers["gigsim-dev-token-ai_ml"]["connects_balance"]
    done = await run_bid("ai_ml", jid, profile=persona_profile("ai_ml"), thread_id="t-bid-1", resume={"action": "approve"})
    assert done["state"]["status"] == "submitted"
    pid = done["state"]["submission"]["proposal_id"]
    # crash-and-resume simulation: run the submit node again from the checkpoint history -> replayed
    again = await run_bid("ai_ml", jid, profile=persona_profile("ai_ml"), thread_id="t-bid-1", cont=True)
    assert again["state"]["submission"]["proposal_id"] == pid
    subs = [p for p in W.proposals.values() if p["job_id"] == jid and p["status"] != "draft"]
    assert len(subs) == 1
    assert W.freelancers["gigsim-dev-token-ai_ml"]["connects_balance"] == bal0 - row["job"]["connects_cost"]


async def test_reject_and_edit_paths():
    W.reset()
    rows = [r for r in DEV if r["gold"]["job_type"] == "standard" and r["gold"]["bid"]][1:3]
    a = await run_bid("ai_ml", rows[0]["job"]["job_id"], profile=persona_profile("ai_ml"), thread_id="t-rej", force_bid=True)
    r = await run_bid("ai_ml", rows[0]["job"]["job_id"], profile=persona_profile("ai_ml"), thread_id="t-rej",
                      resume={"action": "reject", "reason": "too generic"})
    assert a["interrupt"] and r["state"]["status"] == "rejected"
    b = await run_bid("ai_ml", rows[1]["job"]["job_id"], profile=persona_profile("ai_ml"), thread_id="t-edit", force_bid=True)
    edited = b["interrupt"]["final_text"] + " Contact me at me@example.com for details."
    e = await run_bid("ai_ml", rows[1]["job"]["job_id"], profile=persona_profile("ai_ml"), thread_id="t-edit",
                      resume={"action": "edit", "edited_text": edited})
    assert e["state"]["status"] == "submitted"
    assert "@" not in e["state"]["submission"]["final_text"]  # compliance re-check removed it


async def test_conversation_graph_drafts_reply_and_waits():
    W.reset()
    row = pick("standard", bid=True)
    jid = row["job"]["job_id"]
    await run_bid("ai_ml", jid, profile=persona_profile("ai_ml"), thread_id="t-conv-bid")
    await run_bid("ai_ml", jid, profile=persona_profile("ai_ml"), thread_id="t-conv-bid", resume={"action": "approve"})
    pid = next(p["proposal_id"] for p in W.proposals.values() if p["job_id"] == jid and p["status"] != "draft")
    # Replace the scheduled simulator outcome with a fixed reply, even on a slow test host.
    W.pending = [(due, event) for due, event in W.pending if event["proposal_id"] != pid]
    W.threads["t-" + pid] = {"thread_id": "t-" + pid, "proposal_id": pid, "job_id": jid, "client_id": row["job"]["client_id"],
                            "freelancer_id": "fl-ai_ml", "messages": [{"message_id": "m1", "sender": "client",
                            "text": "Thanks! Could we schedule a 30-minute call this week?", "sent_at": "now"}]}
    W.proposals[pid]["status"] = "replied"
    c = await run_conversation("ai_ml", "t-" + pid, profile=persona_profile("ai_ml"), graph_thread_id="g-conv-1")
    assert c["interrupt"]["kind"] == "message" and c["interrupt"]["intent"]["intent"] == "interview_request"
    assert c["interrupt"]["slots"]
    s = await run_conversation("ai_ml", "t-" + pid, profile=persona_profile("ai_ml"), graph_thread_id="g-conv-1",
                               resume={"action": "approve"})
    assert s["state"]["status"] == "sent" and s["state"]["sent"]["holds"] >= 1


async def test_continue_without_checkpoint_starts_fresh():
    """A job parked before its first checkpoint (e.g. a crash in setup) is retried with cont=True."""
    W.reset()
    row = pick("scam")
    out = await run_bid("ai_ml", row["job"]["job_id"], profile=persona_profile("ai_ml"), thread_id="t-never-ran",
                        job=row["job"], cont=True)
    assert out["state"]["status"] == "skipped"

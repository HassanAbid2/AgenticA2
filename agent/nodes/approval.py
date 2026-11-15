"""Human-in-the-loop (C5) and the only marketplace writes in the bid graph.

prepare_approval -> human_approval [interrupt()] -> submit | compliance_recheck | END
- The interrupt payload carries the draft, the evidence behind every claim, the risk report, the price
  rationale and the marketplace dry_run preview (exact payload, Connects cost, balance after).
- Edits are diffed, the raw edit goes to the ("edits", user) staging namespace, the style promotion
  rule runs, and the edited text is re-checked by the Compliance Guard before anything is sent.
- submit uses idempotency keys derived from the thread id, so a crash/retry/resume never submits twice.
"""

from __future__ import annotations

import hashlib
import time

from langgraph.config import get_store
from langgraph.types import interrupt

from agent.handoffs import ApprovalDecision
from agent.mcp_client import MarketplaceRejected
from agent.memory import promotion_rules as pr
from agent.memory.store import STYLE
from agent.nodes.common import deps, node
from agent.nodes.compliance import guard
from rag.verify import strip_citations


def idem(thread_id: str, kind: str, *parts) -> str:
    h = hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:12]
    return f"{thread_id}:{kind}:{h}".replace("/", "_")[:118]


def payload_for(state) -> dict:
    d = state["draft"]
    return {"job_id": state["job"]["job_id"], "cover_letter": strip_citations(d["cover_letter"]),
            "screening_answers": [strip_citations(a) for a in d.get("screening_answers", [])],
            "bid_amount": float(state["price"]["amount"]), "bid_type": state["price"]["unit"]}


@node("prepare_approval")
async def prepare_approval(state, config):
    d = deps(config)
    pay = payload_for(state)
    preview = await d.market("approval").preview_proposal(pay, idem(state["trace_id"] or state["job_id"], "preview", pay["cover_letter"]))
    return {"preview": preview, "status": "awaiting_approval",
            "_summary": {"connects_cost": preview.get("connects_cost"), "policy_issues": preview.get("policy_issues")}}


def approval_request(state) -> dict:
    d = state["draft"]
    by_id = {e["evidence_id"]: e for e in d.get("evidence", [])}
    return {
        "kind": "proposal", "job": {k: state["job"].get(k) for k in ("job_id", "title", "category", "budget", "client_id", "connects_cost")},
        "draft_with_citations": d["cover_letter"], "final_text": strip_citations(d["cover_letter"]),
        "screening_questions": state["job"].get("screening_questions", []),
        "screening_answers": [strip_citations(a) for a in d.get("screening_answers", [])],
        "claims": [c | {"evidence": [{"evidence_id": i, "title": by_id.get(i, {}).get("title"),
                                       "snippet": (by_id.get(i, {}).get("snippet") or "")[:400]} for i in c["evidence_ids"]]}
                   for c in d.get("claims", []) if c["label"] != "unsupported"],
        "removed_claims": d.get("removed_claims", []), "evidence": d.get("evidence", []),
        "unsupported_rate_before": d.get("unsupported_rate_before"), "unsupported_rate_after": d.get("unsupported_rate_after"),
        "risk_report": state.get("risk_report"), "fit_report": state.get("fit_report"), "price": state.get("price"),
        "decision": state.get("decision"), "critiques": state.get("critiques", []), "compliance": state.get("compliance"),
        "preview": state.get("preview"), "strategy": d.get("strategy"),
    }


@node("human_approval")
async def human_approval(state, config):
    raw = interrupt(approval_request(state))  # pauses here; resumed by the UI with Command(resume=...)
    dec = ApprovalDecision.model_validate(raw)
    rec = dec.model_dump() | {"at": time.time()}
    if dec.action == "reject":
        return {"approvals": [rec], "status": "rejected", "status_reason": dec.reason or "rejected by user",
                "_summary": {"action": "reject", "reason": dec.reason}}
    if dec.action == "edit":
        before = strip_citations(state["draft"]["cover_letter"])
        after = dec.edited_text or before
        rec["diff"] = pr.diff_text(before, after)
        await _learn_from_edit(config, state["job"]["job_id"], before, after)
        draft = state["draft"] | {"cover_letter": after, "screening_answers": dec.edited_answers or state["draft"].get("screening_answers", [])}
        price = state["price"] | ({"amount": dec.bid_amount} if dec.bid_amount else {})
        return {"approvals": [rec], "draft": draft, "price": price, "_summary": {"action": "edit", "diff_lines": rec["diff"].count("\n")}}
    price = state["price"] | ({"amount": dec.bid_amount} if dec.bid_amount else {})
    return {"approvals": [rec], "price": price, "status": "approved", "_summary": {"action": "approve"}}


async def _learn_from_edit(config, job_id: str, before: str, after: str):
    """Raw edit -> staging namespace; promotion rule decides what becomes style memory."""
    store = get_store()
    uid = deps(config).hub.user_id
    pats = pr.extract_patterns(before, after)
    eid = f"{int(time.time() * 1000)}-{job_id}"
    await store.aput(("edits", uid), eid, {"id": eid, "job_id": job_id, "after": after.lower(), "patterns": pats, "ts": time.time()})
    edits = sorted((i.value for i in await store.asearch(("edits", uid), limit=200)), key=lambda e: e["ts"])
    for rule in pr.promote_style(edits):
        await store.aput((STYLE, uid), rule["id"], rule | {"promoted_at": time.time()})


@node("compliance_recheck")
async def compliance_recheck(state, config):
    d = state["draft"]
    v = await guard(d["cover_letter"], d.get("screening_answers", []), config)
    ok = v.status != "block"
    upd = {"compliance": v.model_dump(), "_summary": {"status": v.status}}
    if ok:
        upd["draft"] = d | {"cover_letter": v.cleaned_text, "screening_answers": v.cleaned_answers}
        upd["status"] = "approved"
    return upd


@node("submit")
async def submit(state, config):
    """Exactly-once: same thread -> same idempotency keys -> marketplace replays the first result."""
    d = deps(config)
    m = d.market("approval")
    pay = payload_for(state)
    tid = state.get("trace_id") or state["job_id"]
    base = config["configurable"].get("thread_id", tid)
    try:
        draft = await m.create_proposal_draft(pay, idem(base, "draft", pay["cover_letter"], pay["bid_amount"]))
        pid = draft["result"]["proposal_id"]
        res = await m.submit_proposal(pid, idem(base, "submit", pid))
    except MarketplaceRejected as e:  # policy violation, insufficient Connects, already applied: a human decision
        reason = str(e).split("MARKETPLACE_REJECTED:", 1)[-1].strip()[:300]
        return {"status": "needs_attention", "status_reason": f"marketplace refused the submission: {reason}",
                "submission": {"error": reason}, "_summary": {"rejected": reason}}
    status = res["result"].get("status", "submitted")
    return {"submission": {"proposal_id": pid, "status": status, "connects_spent": res.get("connects_cost"),
                           "replayed": res.get("idempotent_replay", False), "final_text": pay["cover_letter"],
                           "bid_amount": pay["bid_amount"]},
            "status": "submitted", "_summary": {"proposal_id": pid, "status": status, "replayed": res.get("idempotent_replay")}}


@node("needs_attention")
async def needs_attention(state, config):
    from agent.nodes.common import over_budget

    reason = over_budget(state) or ("no grounded draft after the maximum number of revisions; the portfolio may not "
                                     "support this job" if state.get("critiques") else state.get("status_reason", ""))
    return {"status": "needs_attention", "status_reason": reason, "_summary": {"reason": reason}}


@node("recall_memory")
async def recall_memory(state, config):
    from agent.memory.store import load_memory

    store = get_store()
    mem = await load_memory(store, deps(config).hub.user_id, state["job"].get("category")) if store else {}
    return {"memory_context": mem, "_summary": {"style_rules": len(mem.get("style_rules", [])), "outcome": bool(mem.get("outcome"))}}

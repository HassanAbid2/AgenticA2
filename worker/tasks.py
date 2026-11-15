"""Background work (E1): scouting, graph runs, approval resumes, marketplace event polling,
conversation drafting, degraded-mode recovery and outcome-memory promotion.

Run by the Arq worker (worker/main.py) on Redis; the API can also run them inline (TASK_MODE=inline)
for single-process dev and the Playwright suite. Every task is idempotent:
- analyse_job skips jobs already analysed (unless forced) and Arq dedups by job id;
- resume_approval only resumes an approval once (status -> resumed) and the marketplace write uses
  idempotency keys, so a worker crash between approval and submission still submits exactly once.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import UTC, datetime, timedelta

from agent.config import settings
from agent.marketplace_port import MCPMarketplace
from agent.mcp_client import MarketplaceUnavailable, MCPHub
from agent.runner import bid_thread_id, persona_profile, run_bid, run_conversation
from shared.db import Approval, Conversation, Job, Proposal, Run, RunEvent, SavedSearch, User, session
from shared.security import mask_pii

log = logging.getLogger("gigbid.worker")
DONE = {"skipped", "watch", "awaiting_approval", "submitted", "rejected", "blocked", "approved"}
MAX_ATTEMPTS = 3


# ----------------------------------------------------------------------------- helpers
def user_profile(u: User) -> tuple[dict, dict]:
    base = persona_profile(u.persona) if u.persona in ("ai_ml", "fullstack", "data_analyst") else {
        "name": u.name or "Freelancer", "headline": u.settings.get("headline", ""), "hourly_rate": 30, "floor_hourly": 20, "min_fixed": 150}
    s = dict(u.settings or {})
    base = base | {k: s[k] for k in ("hourly_rate", "floor_hourly", "min_fixed", "headline") if s.get(k) not in (None, "")}
    if u.name:
        base["name"] = u.name if u.persona == "own" else base.get("name", u.name)
    week_ago = datetime.now(UTC) - timedelta(days=7)
    with session() as db:
        spent = sum(p.connects_spent for p in db.query(Proposal).filter(Proposal.user_id == u.id, Proposal.updated_at >= week_ago))
    s["connects_spent_this_week"] = spent
    return base, s


def _event_writer(run_id: int, user_id: int):
    def on_event(mode, chunk):
        rows = []
        if mode == "custom" and isinstance(chunk, dict):
            rows.append(RunEvent(run_id=run_id, user_id=user_id, node=chunk.get("node", "?"), kind=chunk.get("kind", "custom"),
                                 payload=mask_pii({k: v for k, v in chunk.items() if k not in ("node", "kind")})))
        elif mode == "updates" and isinstance(chunk, dict):
            for node, _upd in chunk.items():
                if node == "__interrupt__":
                    rows.append(RunEvent(run_id=run_id, user_id=user_id, node="human_approval", kind="interrupt", payload={}))
        if rows:
            with session() as db:
                db.add_all(rows)
    return on_event


def _snapshot(st: dict) -> dict:
    """What the inbox / job detail need, without the whole state."""
    keep = ("job_spec", "risk_report", "fit_report", "decision", "price", "compliance", "status_reason", "duplicate_of")
    snap = {k: st.get(k) for k in keep if st.get(k) is not None}
    if st.get("draft"):
        snap["draft"] = {k: st["draft"].get(k) for k in ("cover_letter", "unsupported_rate_before", "unsupported_rate_after",
                                                          "removed_claims", "strategy", "revision", "n_claims")}
    snap["critiques"] = st.get("critiques", [])[-3:]
    snap["revisions"] = st.get("revision", 0)
    return snap


def _finish_run(run_id: int, out: dict | None, status: str, error: str | None = None):
    with session() as db:
        r = db.get(Run, run_id)
        r.status = status
        r.ended_at = datetime.now(UTC)
        r.error = error
        if out:
            r.tokens, r.cost_usd, r.latency_s = out["tokens"], out["cost_usd"], out["latency_s"]
            r.per_node = out["usage"]
            r.steps = out["state"].get("steps", 0)
        db.add(RunEvent(run_id=run_id, user_id=r.user_id, node="run", kind="done", payload={"status": status, "error": error}))


def _new_run(user_id: int, thread_id: str, graph: str, job_id: str | None, trace_id: str) -> int:
    with session() as db:
        r = Run(user_id=user_id, thread_id=thread_id, graph=graph, job_id=job_id, trace_id=trace_id)
        db.add(r)
        db.flush()
        db.add(RunEvent(run_id=r.id, user_id=user_id, node="run", kind="start", payload={"graph": graph, "job_id": job_id}))
        return r.id


def _apply_bid_result(user_id: int, job_id: str, thread_id: str, out: dict, run_id: int):
    st = out["state"]
    status = st.get("status") or "running"
    if out["interrupt"]:
        status = "awaiting_approval"
    with session() as db:
        j = db.query(Job).filter_by(user_id=user_id, job_id=job_id).one()
        j.status = status if status != "running" else j.status
        j.thread_id = thread_id
        j.decision = (st.get("decision") or {}).get("action")
        j.fit_score = (st.get("fit_report") or {}).get("score")
        j.risk_score = (st.get("risk_report") or {}).get("score")
        j.risk_flags = (st.get("risk_report") or {}).get("flags", [])
        j.price = (st.get("price") or {}).get("amount")
        j.connects_cost = j.job.get("connects_cost")
        j.summary = _snapshot(st) | {"run_id": run_id}
        prop = db.query(Proposal).filter_by(user_id=user_id, thread_id=thread_id).one_or_none()
        if out["interrupt"]:
            exists = db.query(Approval).filter_by(user_id=user_id, thread_id=thread_id, status="pending").first()
            if not exists:
                db.add(Approval(user_id=user_id, thread_id=thread_id, graph="bid", kind="proposal", payload=out["interrupt"]))
            if not prop:
                prop = Proposal(user_id=user_id, job_id=job_id, thread_id=thread_id, category=j.job.get("category", ""))
                db.add(prop)
            prop.status = "drafted"
            prop.draft = {"cover_letter": out["interrupt"]["final_text"], "claims": len(out["interrupt"]["claims"]),
                          "evidence": [{"project": e.get("project"), "evidence_id": e.get("evidence_id")}
                                       for e in out["interrupt"].get("evidence", [])]}
            prop.bid_amount = (st.get("price") or {}).get("amount")
            prop.strategy = (st.get("draft") or {}).get("strategy", "default")
        if prop:
            prop.cost_usd = (prop.cost_usd or 0) + out["cost_usd"]
            prop.latency_s = (prop.latency_s or 0) + out["latency_s"]
            if (st.get("submission") or {}).get("error"):
                prop.status, prop.reject_reason = "blocked", st["submission"]["error"]
            elif st.get("submission"):
                sub = st["submission"]
                prop.status = "submitted" if sub["status"] in ("submitted",) else sub["status"]
                prop.marketplace_proposal_id = sub["proposal_id"]
                prop.connects_spent = sub.get("connects_spent") or 0
                prop.final_text = sub["final_text"]
                prop.bid_amount = sub["bid_amount"]
            elif status == "rejected":
                prop.status = "rejected"
                prop.reject_reason = st.get("status_reason")
            elif status == "blocked":
                prop.status = "blocked"


# ----------------------------------------------------------------------------- tasks
async def analyse_job(ctx, user_id: int, job_id: str, force_bid: bool = False, trace_id: str | None = None, cont: bool = False):
    with session() as db:
        u = db.get(User, user_id)
        j = db.query(Job).filter_by(user_id=user_id, job_id=job_id).one_or_none()
        if not u or not j:
            return {"skipped": "unknown user/job"}
        if j.status in DONE and not force_bid and not cont:
            return {"skipped": f"already {j.status}"}
        j.status = "analysing"
        job, dup = j.job, j.duplicate_of
        thread_id = j.thread_id if cont and j.thread_id else bid_thread_id(str(user_id), job_id, f"-f{int(time.time())}" if force_bid else "")
    profile, us = user_profile(u)
    trace_id = trace_id or uuid.uuid4().hex
    run_id = _new_run(user_id, thread_id, "bid", job_id, trace_id)
    try:
        out = await run_bid(str(user_id), job_id, profile=profile, user_settings=us, job=None if cont else job, duplicate_of=dup,
                            force_bid=force_bid, cont=cont, thread_id=thread_id, trace_id=trace_id, on_event=_event_writer(run_id, user_id))
    except MarketplaceUnavailable as e:  # degraded mode: park, show banner, recover later
        with session() as db:
            jj = db.query(Job).filter_by(user_id=user_id, job_id=job_id).one()
            jj.status, jj.thread_id = "marketplace_unavailable", thread_id
        _finish_run(run_id, None, "failed", f"marketplace unavailable: {e}")
        return {"parked": job_id}
    except Exception as e:  # noqa: BLE001 - dead-letter after bounded attempts
        log.exception("analyse_job failed")
        with session() as db:
            jj = db.query(Job).filter_by(user_id=user_id, job_id=job_id).one()
            jj.attempts += 1
            jj.thread_id = thread_id
            jj.status = "dead_letter" if jj.attempts >= MAX_ATTEMPTS else "queued"
            jj.summary = (jj.summary or {}) | {"last_error": f"{type(e).__name__}: {str(e)[:300]}"}
        _finish_run(run_id, None, "dead_letter" if jj.attempts >= MAX_ATTEMPTS else "failed", f"{type(e).__name__}: {str(e)[:500]}")
        return {"error": str(e)[:200]}
    _apply_bid_result(user_id, job_id, thread_id, out, run_id)
    st = out["state"].get("status")
    _finish_run(run_id, out, "interrupted" if out["interrupt"] else ("needs_attention" if st == "needs_attention" else "completed"))
    return {"job_id": job_id, "status": st, "interrupt": bool(out["interrupt"])}


async def resume_approval(ctx, approval_id: int, trace_id: str | None = None):
    with session() as db:
        a = db.get(Approval, approval_id)
        if not a or a.status in ("pending", "resumed"):
            return {"skipped": a.status if a else "missing"}
        decision = {"action": "edit" if a.status == "edited" else "approve" if a.status == "approved" else "reject",
                    "edited_text": a.edited_text, "reason": a.reason, "bid_amount": (a.payload or {}).get("bid_override")}
        u = db.get(User, a.user_id)
        user_id, thread_id, graph, _kind = a.user_id, a.thread_id, a.graph, a.kind
        job_id = (a.payload or {}).get("job", {}).get("job_id") or (a.payload or {}).get("job_id")
    profile, us = user_profile(u)
    trace_id = trace_id or uuid.uuid4().hex
    run_id = _new_run(user_id, thread_id, graph, job_id, trace_id)
    try:
        if graph == "bid":
            out = await run_bid(str(user_id), job_id, profile=profile, user_settings=us, resume=decision, thread_id=thread_id,
                                trace_id=trace_id, on_event=_event_writer(run_id, user_id))
        else:
            with session() as db:
                conv = db.query(Conversation).filter_by(user_id=user_id, graph_thread_id=thread_id).one()
                mt = conv.marketplace_thread_id
            out = await run_conversation(str(user_id), mt, profile=profile, user_settings=us, resume=decision,
                                         graph_thread_id=thread_id, trace_id=trace_id, on_event=_event_writer(run_id, user_id))
    except MarketplaceUnavailable as e:
        _finish_run(run_id, None, "failed", f"marketplace unavailable: {e}")
        with session() as db:
            if job_id:
                for jj in db.query(Job).filter_by(user_id=user_id, job_id=job_id):
                    jj.status = "marketplace_unavailable"
        return {"parked": approval_id}  # approval stays decided; retry_parked resumes the same thread (idempotent)
    with session() as db:
        db.get(Approval, approval_id).status = "resumed"
    if graph == "bid":
        _apply_bid_result(user_id, job_id, thread_id, out, run_id)
    else:
        _apply_conversation_result(user_id, thread_id, out)
    _finish_run(run_id, out, "interrupted" if out["interrupt"] else "completed")
    return {"approval_id": approval_id, "status": out["state"].get("status")}


def _apply_conversation_result(user_id: int, graph_thread_id: str, out: dict):
    st = out["state"]
    with session() as db:
        conv = db.query(Conversation).filter_by(user_id=user_id, graph_thread_id=graph_thread_id).one_or_none()
        if conv:
            conv.intent = (st.get("intent") or {}).get("intent", conv.intent)
            conv.messages = st.get("messages", conv.messages)
            conv.status = st.get("status", conv.status)
            if st.get("new_message"):
                conv.last_seen_message = st["new_message"]["message_id"]
        if out["interrupt"] and not db.query(Approval).filter_by(user_id=user_id, thread_id=graph_thread_id, status="pending").first():
            db.add(Approval(user_id=user_id, thread_id=graph_thread_id, graph="conversation", kind="message", payload=out["interrupt"]))


async def draft_reply(ctx, user_id: int, marketplace_thread_id: str, trace_id: str | None = None):
    with session() as db:
        u = db.get(User, user_id)
        conv = db.query(Conversation).filter_by(user_id=user_id, marketplace_thread_id=marketplace_thread_id).one()
        if db.query(Approval).filter_by(user_id=user_id, graph="conversation", status="pending").filter(
                Approval.thread_id.like(f"conv-{user_id}-{marketplace_thread_id}-%")).first():
            return {"skipped": "reply already awaiting approval"}
        gtid = f"conv-{user_id}-{marketplace_thread_id}-{int(time.time())}"
        conv.graph_thread_id = gtid
        prop = db.query(Proposal).filter_by(user_id=user_id, marketplace_proposal_id=conv.proposal_id).one_or_none()
        last_bid = prop.bid_amount if prop else None
    profile, us = user_profile(u)
    us["last_bid_amount"] = last_bid
    trace_id = trace_id or uuid.uuid4().hex
    run_id = _new_run(user_id, gtid, "conversation", conv.job_id, trace_id)
    try:
        out = await run_conversation(str(user_id), marketplace_thread_id, profile=profile, user_settings=us, graph_thread_id=gtid,
                                     trace_id=trace_id, on_event=_event_writer(run_id, user_id))
    except MarketplaceUnavailable as e:
        _finish_run(run_id, None, "failed", str(e))
        return {"parked": marketplace_thread_id}
    _apply_conversation_result(user_id, gtid, out)
    _finish_run(run_id, out, "interrupted" if out["interrupt"] else "completed")
    return {"thread": marketplace_thread_id, "intent": (out["state"].get("intent") or {}).get("intent")}


async def scout_user(ctx, user_id: int, force: bool = False):
    """Run due saved searches for one user; queue genuinely new jobs (dedup by id and near-duplicate)."""
    from agent.nodes.scout import run_saved_searches

    interval_floor = settings()["marketplace"]["live_poll_minutes"] if settings()["marketplace"]["mode"] == "upwork_live" else 0
    now = datetime.now(UTC)
    with session() as db:
        searches = [s for s in db.query(SavedSearch).filter_by(user_id=user_id, enabled=True)
                    if force or not s.last_run_at or now - s.last_run_at.replace(tzinfo=UTC) >= timedelta(minutes=max(s.interval_minutes, interval_floor))]
        if not searches:
            return {"due": 0}
        known = [j.job for j in db.query(Job).filter_by(user_id=user_id).order_by(Job.id.desc()).limit(500)]
        payload = [{"query": s.query, "skills": s.skills, "category": s.category, "min_budget": s.min_budget} for s in searches]
        for s in searches:
            s.last_run_at = now
        autonomy = (db.get(User, user_id).settings or {}).get("autonomy", "suggest")
    market = MCPMarketplace(MCPHub(str(user_id), uuid.uuid4().hex), "scout")
    try:
        new = await run_saved_searches(market, payload, known)
    except MarketplaceUnavailable:
        return {"marketplace": "unavailable"}
    from agent.nodes.scout import dedup_key

    queued = []
    with session() as db:
        for jb in new:
            if db.query(Job).filter_by(user_id=user_id, job_id=jb["job_id"]).first():
                continue
            dup = jb.pop("duplicate_of", None)
            db.add(Job(user_id=user_id, job_id=jb["job_id"], job=jb, dedup_key=dedup_key(jb), duplicate_of=dup,
                       status="skipped" if dup else "queued", decision="skip" if dup else None,
                       summary={"status_reason": f"duplicate of {dup}"} if dup else {}))
            if not dup:
                queued.append(jb["job_id"])
    for jid in queued:
        await enqueue("analyse_job", user_id=user_id, job_id=jid)
    return {"new": len(new), "queued": len(queued), "autonomy": autonomy}


async def poll_events(ctx, user_id: int):
    """Pipeline board + outcome feedback: marketplace events -> proposal statuses, new client replies
    -> conversations (and a drafted reply awaiting approval)."""
    from shared.db import KV

    hub = MCPHub(str(user_id), uuid.uuid4().hex)
    market = MCPMarketplace(hub, "pipeline")
    with session() as db:
        cur = db.get(KV, (user_id, "events_seq"))
        since = (cur.value or {}).get("seq", 0) if cur else 0
    try:
        events = await market.get_events(since)
    except MarketplaceUnavailable:
        return {"marketplace": "unavailable"}
    order = {"submitted": 0, "viewed": 1, "replied": 2, "interview": 3, "hired": 4, "lost": 4}
    threads_to_check = set()
    with session() as db:
        for e in events:
            p = db.query(Proposal).filter_by(user_id=user_id, marketplace_proposal_id=e.get("proposal_id")).one_or_none()
            if p and order.get(e["type"], -1) >= order.get(p.status, -1):
                p.status = e["type"]
                for j in db.query(Job).filter_by(user_id=user_id, job_id=p.job_id):
                    j.summary = (j.summary or {}) | {"pipeline": e["type"]}
            if e["type"] in ("replied", "interview", "hired") and e.get("thread_id"):
                threads_to_check.add((e["thread_id"], e.get("job_id"), e.get("proposal_id")))
        if events:
            row = db.get(KV, (user_id, "events_seq"))
            if row:
                row.value = {"seq": max(e["seq"] for e in events)}
            else:
                db.add(KV(user_id=user_id, key="events_seq", value={"seq": max(e["seq"] for e in events)}))
    to_draft = []
    for tid, jid, pid in threads_to_check:
        th = (await market.list_messages(tid))[0]
        msgs = th["messages"]
        with session() as db:
            conv = db.query(Conversation).filter_by(user_id=user_id, marketplace_thread_id=tid).one_or_none()
            if not conv:
                conv = Conversation(user_id=user_id, marketplace_thread_id=tid, job_id=jid or th.get("job_id"), proposal_id=pid)
                db.add(conv)
            conv.messages = msgs
            if msgs and msgs[-1]["sender"] == "client" and conv.last_seen_message != msgs[-1]["message_id"]:
                conv.status = "needs_reply"
                to_draft.append(tid)
    for tid in to_draft:
        await enqueue("draft_reply", user_id=user_id, marketplace_thread_id=tid)
    if events:
        await promote_outcomes(ctx, user_id)
    return {"events": len(events), "replies": len(to_draft)}


async def promote_outcomes(ctx, user_id: int):
    from agent.memory.promotion_rules import promote_outcomes as rule
    from agent.memory.store import OUTCOME, open_store

    with session() as db:
        rows = [{"category": p.category, "status": p.status, "strategy": p.strategy,
                 "projects": [c.get("project") for c in (p.draft or {}).get("evidence", []) if c.get("project")]}
                for p in db.query(Proposal).filter_by(user_id=user_id)
                if p.status in ("submitted", "viewed", "replied", "interview", "hired", "lost")]
    promoted = rule(rows)
    async with open_store() as st:
        for cat, stats in promoted.items():
            await st.aput((OUTCOME, str(user_id)), cat, stats | {"promoted_at": time.time()})
    return {"categories": len(promoted)}


async def retry_parked(ctx):
    """Degraded-mode recovery: when the marketplace is back, resume parked jobs and approvals."""
    with session() as db:
        parked = [(j.user_id, j.job_id, j.thread_id) for j in db.query(Job).filter(Job.status.in_(["marketplace_unavailable", "queued"]))]
        decided = [a.id for a in db.query(Approval).filter(Approval.status.in_(["approved", "edited", "rejected"]))]
    if not parked and not decided:
        return {"parked": 0}
    if parked:
        try:
            h = await MCPMarketplace(MCPHub(str(parked[0][0]), ""), "pipeline").health()
            if not h.get("marketplace_ok"):
                return {"marketplace": "still unavailable", "parked": len(parked)}
        except MarketplaceUnavailable:
            return {"marketplace": "still unavailable", "parked": len(parked)}
    for aid in decided:
        await enqueue("resume_approval", approval_id=aid)
    for uid, jid, tid in parked:
        await enqueue("analyse_job", user_id=uid, job_id=jid, cont=bool(tid))
    return {"requeued": len(parked), "resumed": len(decided)}


async def tick(ctx):
    """Cron entry (every minute): scouting for every onboarded user, event polling, recovery."""
    with session() as db:
        users = [u.id for u in db.query(User).filter_by(onboarded=True)]
    for uid in users:
        await enqueue("scout_user", user_id=uid)
        await enqueue("poll_events", user_id=uid)
    await enqueue("retry_parked")
    return {"users": len(users)}


# ----------------------------------------------------------------------------- queue abstraction
TASKS = {f.__name__: f for f in (analyse_job, resume_approval, draft_reply, scout_user, poll_events, promote_outcomes, retry_parked, tick)}
_inline_running: set[str] = set()
_inline_lock: asyncio.Semaphore | None = None  # ponytail: SQLite checkpoints allow one writer; Postgres + worker for concurrency
_pool = None


def _job_key(name: str, kw: dict) -> str:
    return name + ":" + ":".join(f"{k}={v}" for k, v in sorted(kw.items()) if k != "trace_id")


async def enqueue(name: str, **kw):
    """Arq on Redis when available; otherwise an in-process task (same dedup semantics)."""
    import os

    global _pool
    key = _job_key(name, kw)
    if os.getenv("REDIS_URL") and os.getenv("TASK_MODE", "worker") == "worker":
        from arq import create_pool
        from arq.connections import RedisSettings

        if _pool is None:
            _pool = await create_pool(RedisSettings.from_dsn(os.environ["REDIS_URL"]))
        return await _pool.enqueue_job(name, _job_id=key, **kw)
    if key in _inline_running:
        return None
    _inline_running.add(key)

    global _inline_lock
    if _inline_lock is None:
        _inline_lock = asyncio.Semaphore(int(os.getenv("INLINE_CONCURRENCY", "1")))

    async def _go():
        try:
            async with _inline_lock:
                await TASKS[name]({}, **kw)
        except Exception:  # noqa: BLE001
            log.exception("inline task %s failed", name)
        finally:
            _inline_running.discard(key)

    return asyncio.get_running_loop().create_task(_go())

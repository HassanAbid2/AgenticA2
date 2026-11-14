"""Agent run viewer: runs, node-by-node events, per-node tokens/cost, audit rows for the trace id,
checkpoint history and replay-from-any-node."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from apps.api.auth.users import current_user
from apps.api.schemas import Queued, RunDetail, RunEventOut, RunOut
from shared.db import AuditLog, Run, RunEvent, User, session
from shared.tracing import trace_url

router = APIRouter(prefix="/api", tags=["runs"])


def r_out(r: Run) -> RunOut:
    return RunOut(id=r.id, thread_id=r.thread_id, graph=r.graph, job_id=r.job_id, status=r.status, trace_id=r.trace_id,
                  trace_url=trace_url(r.trace_id), tokens=r.tokens, cost_usd=r.cost_usd, latency_s=r.latency_s, steps=r.steps,
                  per_node=r.per_node or {}, error=r.error, started_at=r.started_at, ended_at=r.ended_at)


@router.get("/runs", response_model=list[RunOut])
def runs(limit: int = 50, u: User = Depends(current_user)):
    with session() as db:
        return [r_out(r) for r in db.query(Run).filter_by(user_id=u.id).order_by(Run.id.desc()).limit(min(limit, 200))]


@router.get("/runs/{run_id}", response_model=RunDetail)
def run_detail(run_id: int, u: User = Depends(current_user)):
    with session() as db:
        r = db.query(Run).filter_by(user_id=u.id, id=run_id).one_or_none()
        if not r:
            raise HTTPException(404, "run not found")
        ev = db.query(RunEvent).filter_by(run_id=run_id).order_by(RunEvent.id).all()
        audit = db.query(AuditLog).filter(AuditLog.trace_id == r.trace_id, AuditLog.user_id == str(u.id)).order_by(AuditLog.id).all()
        return RunDetail(run=r_out(r), events=[RunEventOut(id=e.id, node=e.node, kind=e.kind, payload=e.payload, ts=e.ts) for e in ev],
                         audit=[{"id": a.id, "ts": a.ts.isoformat(), "server": a.server, "tool": a.tool, "args": a.args,
                                 "status": a.status} for a in audit])


@router.get("/runs/{run_id}/history")
async def history(run_id: int, u: User = Depends(current_user)) -> list[dict]:
    from agent.runner import history as hist

    with session() as db:
        r = db.query(Run).filter_by(user_id=u.id, id=run_id).one_or_none()
        if not r:
            raise HTTPException(404, "run not found")
        graph, tid = r.graph, r.thread_id
    return [h | {"created_at": str(h["created_at"])} for h in await hist(graph, tid)]


@router.post("/runs/{run_id}/replay/{checkpoint_id}", response_model=Queued)
async def replay(run_id: int, checkpoint_id: str, request: Request, u: User = Depends(current_user)):
    """Re-run a job from any checkpoint (C6). Runs in-process; writes a new Run with its own events."""
    import asyncio

    from agent.llm import UsageTracker
    from agent.mcp_client import MCPHub
    from agent.nodes.common import Deps
    from agent.runner import replay_from
    from worker.tasks import _event_writer, _finish_run, _new_run, user_profile

    with session() as db:
        r = db.query(Run).filter_by(user_id=u.id, id=run_id).one_or_none()
        if not r:
            raise HTTPException(404, "run not found")
        graph, tid, jid = r.graph, r.thread_id, r.job_id
        user = db.get(User, u.id)
    profile, us = user_profile(user)
    new_id = _new_run(u.id, tid, graph, jid, request.state.trace_id)

    async def go():
        deps = Deps(MCPHub(str(u.id), request.state.trace_id), UsageTracker(), profile, us)
        try:
            await replay_from(graph, tid, checkpoint_id, deps, request.state.trace_id, _event_writer(new_id, u.id))
            _finish_run(new_id, None, "completed")
        except Exception as e:  # noqa: BLE001
            _finish_run(new_id, None, "failed", str(e)[:300])

    asyncio.get_running_loop().create_task(go())
    return Queued(queued=True, detail=f"replaying from {checkpoint_id} as run {new_id}")

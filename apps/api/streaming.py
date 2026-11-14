"""SSE bridge to LangGraph streams.

The worker consumes `graph.astream(stream_mode=["updates", "custom"])` and persists each node event
(node_start / node_end with latency, tokens, tool calls, interrupts) as run_events rows. These
endpoints relay them to the browser as Server-Sent Events, so the stream survives the API and the
worker being different processes (or either restarting): the client resumes from the last event id.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from apps.api.auth.users import current_user
from shared.db import Approval, Job, Run, RunEvent, User, session

router = APIRouter(prefix="/api/stream", tags=["stream"])
TERMINAL = {"completed", "interrupted", "failed", "dead_letter", "needs_attention"}


def _events_after(run_id: int | None, user_id: int, after: int) -> list[RunEvent]:
    with session() as db:
        q = db.query(RunEvent).filter(RunEvent.user_id == user_id, RunEvent.id > after)
        if run_id is not None:
            q = q.filter(RunEvent.run_id == run_id)
        return q.order_by(RunEvent.id).limit(200).all()


@router.get("/runs/{run_id}")
async def run_stream(run_id: int, request: Request, u: User = Depends(current_user), last_event_id: str | None = Header(default=None)):
    with session() as db:
        if not db.query(Run).filter_by(user_id=u.id, id=run_id).first():
            raise HTTPException(404, "run not found")

    async def gen():
        after = int(last_event_id or 0)
        idle = 0
        while not await request.is_disconnected():
            evs = _events_after(run_id, u.id, after)
            for e in evs:
                after = e.id
                yield {"id": str(e.id), "event": e.kind, "data": json.dumps({"node": e.node, "kind": e.kind, "payload": e.payload,
                                                                            "ts": e.ts.isoformat()})}
            with session() as db:
                done = db.get(Run, run_id).status in TERMINAL
            idle = 0 if evs else idle + 1
            if done and not evs:
                yield {"event": "end", "data": "{}"}
                return
            await asyncio.sleep(0.4 if idle < 20 else 1.5)

    return EventSourceResponse(gen(), ping=10)


@router.get("/inbox")
async def inbox_stream(request: Request, u: User = Depends(current_user), last_event_id: str | None = Header(default=None)):
    """User-wide feed: every node event plus a compact summary (job statuses, pending approvals) so the
    inbox, pipeline board and banners update live."""

    async def gen():
        after = int(last_event_id or 0)
        if not after:
            with session() as db:
                last = db.query(RunEvent).filter_by(user_id=u.id).order_by(RunEvent.id.desc()).first()
                after = last.id if last else 0
        while not await request.is_disconnected():
            evs = _events_after(None, u.id, after)
            if evs:
                after = evs[-1].id
                with session() as db:
                    counts: dict[str, int] = {}
                    for (st,) in db.query(Job.status).filter_by(user_id=u.id):
                        counts[st] = counts.get(st, 0) + 1
                    pending = db.query(Approval).filter_by(user_id=u.id, status="pending").count()
                yield {"id": str(after), "event": "update", "data": json.dumps({
                    "events": [{"run_id": e.run_id, "node": e.node, "kind": e.kind} for e in evs[-20:]],
                    "counts": counts, "pending_approvals": pending})}
            await asyncio.sleep(1.0)

    return EventSourceResponse(gen(), ping=15)

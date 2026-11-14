"""Client threads with suggested replies (approved through the same approval endpoint)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from apps.api.auth.users import current_user
from apps.api.routers.approvals import a_out
from apps.api.schemas import Queued, ThreadOut
from shared.db import Approval, Conversation, Job, User, session
from worker.tasks import enqueue

router = APIRouter(prefix="/api", tags=["messages"])


@router.get("/threads", response_model=list[ThreadOut])
def threads(u: User = Depends(current_user)):
    out = []
    with session() as db:
        jobs = {j.job_id: j.job.get("title", "") for j in db.query(Job).filter_by(user_id=u.id)}
        pend = [a for a in db.query(Approval).filter_by(user_id=u.id, graph="conversation", status="pending")]
        for c in db.query(Conversation).filter_by(user_id=u.id).order_by(Conversation.updated_at.desc()):
            a = next((x for x in pend if x.thread_id == c.graph_thread_id), None)
            out.append(ThreadOut(id=c.id, marketplace_thread_id=c.marketplace_thread_id, job_id=c.job_id, title=jobs.get(c.job_id, c.job_id),
                                 status=c.status, intent=c.intent, messages=c.messages or [], approval=a_out(a) if a else None))
    return out


@router.post("/threads/{marketplace_thread_id}/draft", response_model=Queued)
async def draft(marketplace_thread_id: str, request: Request, u: User = Depends(current_user)):
    with session() as db:
        if not db.query(Conversation).filter_by(user_id=u.id, marketplace_thread_id=marketplace_thread_id).first():
            raise HTTPException(404, "thread not found")
    await enqueue("draft_reply", user_id=u.id, marketplace_thread_id=marketplace_thread_id, trace_id=request.state.trace_id)
    return Queued(queued=True, detail="drafting a reply")

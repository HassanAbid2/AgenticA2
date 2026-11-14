"""Approvals (proposal studio + message approvals) and the pipeline board.

A decision is persisted first (so a refresh or an API crash never loses it), then the worker resumes
the interrupted LangGraph thread with Command(resume=decision)."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request

from apps.api.auth.users import current_user
from apps.api.schemas import (
    ApprovalOut,
    DecisionIn,
    Pipeline,
    ProposalCard,
    Queued,
    RegenerateIn,
    RegenerateOut,
)
from shared.db import Approval, Job, Proposal, User, session
from worker.tasks import enqueue

router = APIRouter(prefix="/api", tags=["approvals"])
COLUMNS = ["drafted", "submitted", "viewed", "replied", "interview", "hired", "lost"]


def a_out(a: Approval) -> ApprovalOut:
    return ApprovalOut(id=a.id, thread_id=a.thread_id, graph=a.graph, kind=a.kind, status=a.status, payload=a.payload,
                       created_at=a.created_at, reason=a.reason)


@router.get("/approvals", response_model=list[ApprovalOut])
def pending(u: User = Depends(current_user)):
    with session() as db:
        return [a_out(a) for a in db.query(Approval).filter_by(user_id=u.id, status="pending").order_by(Approval.id.desc())]


@router.get("/approvals/{aid}", response_model=ApprovalOut)
def get_approval(aid: int, u: User = Depends(current_user)):
    with session() as db:
        a = db.query(Approval).filter_by(user_id=u.id, id=aid).one_or_none()
        if not a:
            raise HTTPException(404, "approval not found")
        return a_out(a)


@router.post("/approvals/{aid}/decide", response_model=Queued)
async def decide(aid: int, body: DecisionIn, request: Request, u: User = Depends(current_user)):
    if body.action == "reject" and not (body.reason or "").strip():
        raise HTTPException(422, "a reason is required to reject")
    if body.action == "edit" and not (body.edited_text or "").strip():
        raise HTTPException(422, "edited_text is required for edit")
    with session() as db:
        a = db.query(Approval).filter_by(user_id=u.id, id=aid).one_or_none()
        if not a:
            raise HTTPException(404, "approval not found")
        if a.status != "pending":
            raise HTTPException(409, f"already {a.status}")
        a.status = {"approve": "approved", "edit": "edited", "reject": "rejected"}[body.action]
        a.reason, a.edited_text, a.decided_at = body.reason, body.edited_text, datetime.now(UTC)
        if body.bid_amount:
            a.payload = (a.payload or {}) | {"bid_override": body.bid_amount}
        if a.kind == "proposal":
            for j in db.query(Job).filter_by(user_id=u.id, thread_id=a.thread_id):
                j.status = "approved" if body.action != "reject" else "rejected"
    await enqueue("resume_approval", approval_id=aid, trace_id=request.state.trace_id)
    return Queued(queued=True, detail=f"{body.action} recorded; resuming the agent")


@router.post("/approvals/{aid}/regenerate", response_model=RegenerateOut)
async def regenerate_paragraph(aid: int, body: RegenerateIn, u: User = Depends(current_user)):
    """Rewrite one paragraph with the same evidence, then re-verify its claims and re-run compliance."""
    from agent.llm import text as llm_text
    from agent.nodes.compliance import guard
    from agent.nodes.writer import evidence_block
    from rag.verify import strip_citations, strip_unsupported, verify_claims

    with session() as db:
        a = db.query(Approval).filter_by(user_id=u.id, id=aid, kind="proposal").one_or_none()
        if not a:
            raise HTTPException(404, "approval not found")
        payload = a.payload
    paras = [p for p in re.split(r"\n\s*\n", body.text) if p.strip()] or [body.text]
    i = min(body.paragraph_index, len(paras) - 1)
    ev = payload.get("evidence", [])
    new = await llm_text("writer", "regenerate_paragraph", paragraph=paras[i], instruction=body.instruction or "make it more specific",
                         evidence=evidence_block(ev), job_title=payload.get("job", {}).get("title", ""))
    if not new:  # offline: tighten by dropping clichés and keeping grounded sentences
        new = re.sub(r"\b(very|really|passionate|hardworking)\b\s*", "", paras[i])
    claims = verify_claims(new, ev)
    new = strip_citations(strip_unsupported(new, claims))
    v = await guard(new, [])
    paras[i] = v.cleaned_text
    return RegenerateOut(text="\n\n".join(paras), paragraph=v.cleaned_text, claims=[c.to_dict() for c in claims],
                         violations=[x.model_dump() for x in v.violations])


@router.get("/pipeline", response_model=Pipeline)
def pipeline(u: User = Depends(current_user)):
    cols: dict[str, list[ProposalCard]] = {c: [] for c in COLUMNS}
    with session() as db:
        jobs = {j.job_id: j for j in db.query(Job).filter_by(user_id=u.id)}
        pend = {a.thread_id: a.id for a in db.query(Approval).filter_by(user_id=u.id, status="pending")}
        for p in db.query(Proposal).filter_by(user_id=u.id).order_by(Proposal.updated_at.desc()):
            col = p.status if p.status in cols else ("lost" if p.status in ("rejected", "blocked") else "drafted")
            cols[col].append(ProposalCard(id=p.id, job_id=p.job_id, title=jobs[p.job_id].job.get("title", "") if p.job_id in jobs else p.job_id,
                                          status=p.status, bid_amount=p.bid_amount, connects_spent=p.connects_spent, category=p.category,
                                          strategy=p.strategy, updated_at=p.updated_at, approval_id=pend.get(p.thread_id)))
    return Pipeline(columns=cols)

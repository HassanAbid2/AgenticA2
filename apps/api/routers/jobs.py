"""Job inbox and job detail. Analysis runs in the worker; these endpoints only read or enqueue."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from apps.api.auth.users import current_user
from apps.api.schemas import AnalyseIn, JobDetail, JobList, JobRow, Queued
from shared.db import Approval, Job, Run, User, session
from worker.tasks import enqueue

router = APIRouter(prefix="/api", tags=["jobs"])


def row(j: Job) -> JobRow:
    s = j.summary or {}
    return JobRow(job_id=j.job_id, title=j.job.get("title", ""), category=j.job.get("category", ""), status=j.status,
                  decision=j.decision, fit_score=j.fit_score, risk_score=j.risk_score, risk_flags=j.risk_flags or [],
                  price=j.price, price_unit=(s.get("price") or {}).get("unit"), connects_cost=j.job.get("connects_cost"),
                  budget=j.job.get("budget") or {}, posted_at=j.job.get("posted_at", ""), duplicate_of=j.duplicate_of,
                  reason=s.get("status_reason") or "; ".join((s.get("decision") or {}).get("reasons", [])) or s.get("last_error"),
                  pipeline=s.get("pipeline"))


@router.get("/jobs", response_model=JobList)
def inbox(status: str | None = None, decision: str | None = None, min_fit: float = 0, q: str = "", u: User = Depends(current_user)):
    with session() as db:
        jobs = db.query(Job).filter_by(user_id=u.id).all()
    counts: dict[str, int] = {}
    for j in jobs:
        counts[j.status] = counts.get(j.status, 0) + 1
    sel = [j for j in jobs if (not status or j.status == status) and (not decision or j.decision == decision)
           and (j.fit_score or 0) >= min_fit and (not q or q.lower() in (j.job.get("title", "") + j.job.get("description", "")).lower())]
    rank = {"awaiting_approval": 0, "watch": 2, "analysing": 3, "queued": 4}
    sel.sort(key=lambda j: (rank.get(j.status, 1 if j.decision == "bid" else 5), -(j.fit_score or 0)))
    return JobList(jobs=[row(j) for j in sel], counts=counts)


@router.get("/jobs/{job_id}", response_model=JobDetail)
def detail(job_id: str, u: User = Depends(current_user)):
    with session() as db:
        j = db.query(Job).filter_by(user_id=u.id, job_id=job_id).one_or_none()
        if not j:
            raise HTTPException(404, "job not in your inbox")
        a = db.query(Approval).filter_by(user_id=u.id, status="pending").filter(Approval.thread_id == j.thread_id).first() if j.thread_id else None
        runs = db.query(Run).filter_by(user_id=u.id, job_id=job_id).order_by(Run.id.desc()).limit(10).all()
        return JobDetail(job=j.job, row=row(j), analysis=j.summary or {}, approval_id=a.id if a else None,
                         run_id=runs[0].id if runs else None,
                         runs=[{"id": r.id, "status": r.status, "graph": r.graph, "started_at": r.started_at.isoformat(),
                                "trace_id": r.trace_id} for r in runs])


@router.post("/jobs/{job_id}/analyse", response_model=Queued)
async def analyse(job_id: str, body: AnalyseIn, request: Request, u: User = Depends(current_user)):
    with session() as db:
        j = db.query(Job).filter_by(user_id=u.id, job_id=job_id).one_or_none()
        if not j:
            raise HTTPException(404, "job not in your inbox")
        j.status = "queued"
    await enqueue("analyse_job", user_id=u.id, job_id=job_id, force_bid=body.force_bid, trace_id=request.state.trace_id)
    return Queued(queued=True, detail="bid anyway" if body.force_bid else "analysis queued")


@router.post("/jobs/{job_id}/skip", response_model=Queued)
def skip(job_id: str, u: User = Depends(current_user)):
    with session() as db:
        j = db.query(Job).filter_by(user_id=u.id, job_id=job_id).one_or_none()
        if not j:
            raise HTTPException(404, "job not in your inbox")
        j.status, j.decision = "skipped", "skip"
        j.summary = (j.summary or {}) | {"status_reason": "skipped by you"}
        for a in db.query(Approval).filter_by(user_id=u.id, thread_id=j.thread_id, status="pending"):
            a.status, a.reason = "rejected", "job skipped by user"
    return Queued(queued=False, detail="skipped")


@router.post("/scout/run", response_model=Queued)
async def scout_now(request: Request, u: User = Depends(current_user)):
    await enqueue("scout_user", user_id=u.id, force=True)
    await enqueue("poll_events", user_id=u.id)
    return Queued(queued=True, detail="saved searches running")

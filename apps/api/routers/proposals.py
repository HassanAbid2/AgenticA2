"""Tenant-scoped proposal pipeline."""

from fastapi import APIRouter, Depends

from apps.api.auth.users import current_user
from apps.api.schemas import Pipeline, ProposalCard
from shared.db import Approval, Job, Proposal, User, session

# Keep the existing OpenAPI tag and operation ID for generated clients.
router = APIRouter(prefix="/api", tags=["approvals"])
COLUMNS = ["drafted", "submitted", "viewed", "replied", "interview", "hired", "lost"]


@router.get("/pipeline", response_model=Pipeline)
def pipeline(u: User = Depends(current_user)):
    cols: dict[str, list[ProposalCard]] = {column: [] for column in COLUMNS}
    with session() as db:
        jobs = {j.job_id: j.job for j in db.query(Job).filter_by(user_id=u.id)}
        pending = {a.thread_id: a.id for a in db.query(Approval).filter_by(user_id=u.id, status="pending")}
        for proposal in db.query(Proposal).filter_by(user_id=u.id).order_by(Proposal.updated_at.desc()):
            column = proposal.status
            if column not in cols:
                column = "lost" if proposal.status in ("rejected", "blocked") else "drafted"
            job = jobs.get(proposal.job_id)
            cols[column].append(ProposalCard(
                id=proposal.id, job_id=proposal.job_id, title=job.get("title", "") if job is not None else proposal.job_id,
                status=proposal.status, bid_amount=proposal.bid_amount,
                bid_unit=(job.get("budget") or {}).get("type", "fixed") if job is not None else "fixed",
                connects_spent=proposal.connects_spent, category=proposal.category, strategy=proposal.strategy,
                updated_at=proposal.updated_at, approval_id=pending.get(proposal.thread_id),
            ))
    return Pipeline(columns=cols)

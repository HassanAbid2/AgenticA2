"""Analytics: reply and hire rate by category, Connects spent vs outcomes, cost and latency per proposal
(p50/p95 against declared budgets), top rejection reasons."""

from __future__ import annotations

from collections import Counter, defaultdict

from fastapi import APIRouter, Depends

from agent.config import settings
from apps.api.auth.users import current_user
from apps.api.schemas import Analytics
from shared.db import Job, Proposal, Run, User, session

router = APIRouter(prefix="/api", tags=["analytics"])
SENT = {"submitted", "viewed", "replied", "interview", "hired", "lost"}
POS = {"replied", "interview", "hired"}


def pct(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))], 3)


@router.get("/analytics", response_model=Analytics)
def analytics(u: User = Depends(current_user)):
    with session() as db:
        props = db.query(Proposal).filter_by(user_id=u.id).all()
        runs = db.query(Run).filter_by(user_id=u.id).all()
        jobs = db.query(Job).filter_by(user_id=u.id).all()
    cats = defaultdict(lambda: {"sent": 0, "replied": 0, "hired": 0, "connects": 0})
    for p in props:
        if p.status in SENT:
            c = cats[p.category or "uncategorised"]
            c["sent"] += 1
            c["replied"] += p.status in POS
            c["hired"] += p.status == "hired"
            c["connects"] += p.connects_spent
    by_cat = [{"category": k, **v, "reply_rate": round(v["replied"] / v["sent"], 3) if v["sent"] else 0,
               "hire_rate": round(v["hired"] / v["sent"], 3) if v["sent"] else 0} for k, v in sorted(cats.items())]
    sent = [p for p in props if p.status in SENT]
    spent = sum(p.connects_spent for p in sent)
    replies = sum(p.status in POS for p in sent)
    bid_runs = [r for r in runs if r.graph == "bid" and r.status in ("completed", "interrupted")]
    per_job = [r.latency_s for r in bid_runs]
    cost_job = [r.cost_usd for r in bid_runs]
    per_prop = [p.latency_s for p in props if p.latency_s]
    cost_prop = [p.cost_usd for p in props if p.latency_s]
    b = settings()["budgets"]
    reasons = Counter((p.reject_reason or "").strip().lower()[:80] for p in props if p.status == "rejected" and p.reject_reason)
    funnel = {"jobs_seen": len(jobs), "analysed": sum(1 for j in jobs if j.decision), "recommended_bid": sum(1 for j in jobs if j.decision == "bid"),
              "scams_flagged": sum(1 for j in jobs if "scam" in (j.risk_flags or [])), "submitted": len(sent),
              "viewed": sum(p.status in ("viewed", "replied", "interview", "hired") for p in sent), "replied": replies,
              "interview": sum(p.status in ("interview", "hired") for p in sent), "hired": sum(p.status == "hired" for p in sent)}
    return Analytics(
        by_category=by_cat, funnel=funnel,
        connects={"spent": spent, "replies": replies, "connects_per_reply": round(spent / replies, 1) if replies else None,
                  "by_outcome": {s: sum(p.connects_spent for p in sent if p.status == s) for s in SENT}},
        cost_latency={"jobs_analysed": len(bid_runs), "p50_latency_s_per_job": pct(per_job, .5), "p95_latency_s_per_job": pct(per_job, .95),
                      "p95_latency_s_per_proposal": pct(per_prop, .95), "usd_per_job_mean": round(sum(cost_job) / len(cost_job), 5) if cost_job else None,
                      "usd_per_proposal_mean": round(sum(cost_prop) / len(cost_prop), 5) if cost_prop else None,
                      "tokens_total": sum(r.tokens for r in runs)},
        rejection_reasons=[{"reason": r, "count": n} for r, n in reasons.most_common(8)],
        budgets={k: b[k] for k in ("p95_latency_s_per_job", "p95_latency_s_per_proposal", "usd_per_job", "usd_per_proposal")})

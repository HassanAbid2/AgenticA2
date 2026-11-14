"""Bid-or-skip decision node: explicit, configurable rules over the three parallel reports."""

from __future__ import annotations

from agent.handoffs import BidDecision
from agent.nodes.common import deps, node, thresholds


def decide(job: dict, risk: dict, fit: dict, profile: dict, autonomy: str = "suggest", force: bool = False,
           duplicate_of: str | None = None) -> BidDecision:
    t = thresholds()
    if force:
        return BidDecision(action="bid", reasons=["user asked to bid anyway"], confidence=1.0)
    reasons = []
    if duplicate_of:
        return BidDecision(action="skip", reasons=[f"duplicate of job {duplicate_of}"], confidence=0.9)
    if "scam" in risk.get("flags", []) or risk.get("score", 0) >= t["maximum_risk_score"]:
        return BidDecision(action="skip", reasons=[f"high risk ({risk.get('score')}): {', '.join(risk.get('flags', []))}"],
                           confidence=0.9)
    b = job.get("budget") or {}
    if b.get("type") == "fixed" and b.get("max") and b["max"] < profile.get("min_fixed", 0):
        return BidDecision(action="skip", reasons=[f"budget ${b['max']} below your minimum ${profile.get('min_fixed')}"], confidence=0.85)
    if b.get("type") == "hourly" and b.get("max") and b["max"] < profile.get("floor_hourly", 0):
        return BidDecision(action="skip", reasons=[f"hourly max ${b['max']} below your floor ${profile.get('floor_hourly')}"], confidence=0.85)
    f = fit.get("score", 0)
    if fit.get("missing_skills"):
        reasons.append("missing evidence for " + ", ".join(fit["missing_skills"][:4]))
    if f < t["watch_fit_score"]:
        return BidDecision(action="skip", reasons=reasons + [f"low fit {f:.2f} < {t['watch_fit_score']}"], confidence=0.75,
                           auto=autonomy == "auto_skip_low_fit")
    if f < t["minimum_fit_score"]:
        return BidDecision(action="watch", reasons=reasons + [f"borderline fit {f:.2f}"], confidence=0.5)
    return BidDecision(action="bid", reasons=reasons + [f"fit {f:.2f}, risk {risk.get('score', 0):.2f}"],
                       confidence=round(min(1.0, 0.5 + f / 2), 2))


@node("decide")
async def decision_node(state, config):
    d = deps(config)
    dec = decide(state["job"], state.get("risk_report", {}), state.get("fit_report", {}), d.profile | d.user_settings,
                 d.setting("autonomy", "suggest"), state.get("force_bid", False), state.get("duplicate_of"))
    status = {"bid": "running", "watch": "watch", "skip": "skipped"}[dec.action]
    return {"decision": dec.model_dump(), "status": status, "status_reason": "; ".join(dec.reasons),
            "_summary": {"action": dec.action, "reasons": dec.reasons}}

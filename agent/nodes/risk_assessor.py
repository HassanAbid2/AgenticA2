"""Risk Assessor: client quality from marketplace history + scam / unpaid-work / off-platform /
injection detection on the post. Produces the sanitised description every later LLM sees."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from agent.guardrails import neutralise, scam_signals
from agent.handoffs import RiskReport
from agent.llm import structured, untrusted
from agent.nodes.common import deps, node, thresholds

WEIGHTS = {"unpaid_work": 0.55, "off_platform_payment": 0.65, "off_platform_contact": 0.45, "personal_info_request": 0.65,
           "overpayment_scheme": 0.85, "prompt_injection": 0.30, "unverified_payment": 0.15, "new_client": 0.10,
           "poor_client_history": 0.25, "low_budget": 0.10, "duplicate": 0.05}


class LLMRisk(BaseModel):
    scam_probability: float = Field(ge=0, le=1)
    flags: list[str] = []
    explanation: str = ""


def client_quality(c: dict) -> tuple[float, list[str]]:
    flags, q = [], 0.5
    if not c.get("payment_verified"):
        flags.append("unverified_payment")
        q -= 0.2
    hires = c.get("hires", 0) or 0
    q += min(0.25, hires * 0.02)
    q += min(0.15, (c.get("total_spent_usd", 0) or 0) / 100_000)
    try:
        if hires == 0 and (date.today() - date.fromisoformat(c.get("member_since", "2000-01-01")[:10])).days < 60:
            flags.append("new_client")
            q -= 0.15
    except ValueError:
        pass
    rating = c.get("avg_rating_given")
    fb = " ".join(c.get("feedback_from_freelancers") or []).lower()
    if (rating is not None and rating < thresholds()["min_client_rating"]) or "disput" in fb or "changed scope" in fb:
        flags.append("poor_client_history")
        q -= 0.25
    return max(0.0, min(1.0, q)), flags


def rule_score(flags: list[str]) -> float:
    p = 1.0
    for f in set(flags):
        p *= 1 - WEIGHTS.get(f, 0)
    return round(1 - p, 3)


@node("risk_assessor")
async def risk_assessor(state, config):
    job = state["job"]
    d = deps(config)
    text = f"{job.get('title', '')}\n{job.get('description', '')}"
    clean, spans = neutralise(job.get("description", ""))
    signals = scam_signals(text)
    flags = list(signals)
    try:
        client = await d.market("risk_assessor").get_client_history(job["client_id"])
    except Exception as e:  # noqa: BLE001 - unknown client is itself a signal, not a crash
        client = {"error": str(e)[:100]}
    q, cflags = client_quality(client) if "error" not in client else (0.3, ["new_client"])
    flags += cflags
    if spans:
        flags.append("prompt_injection")
    b = job.get("budget") or {}
    if b.get("type") == "fixed" and (b.get("max") or 0) < 50:
        flags.append("low_budget")
    if state.get("duplicate_of"):
        flags.append("duplicate")
    score = rule_score(flags)
    expl = [f"{k}: '{v[0]}'" for k, v in signals.items()]
    llm = await structured("risk_assessor", "risk_assessor", LLMRisk, config, client=client, rule_flags=flags,
                           job_post=untrusted("job_post", f"{job.get('title', '')}\n{clean}"))
    if llm:
        # The small model over-flags (dev eval: scam precision 0.75 -> 0.38 when its flags were trusted), so it may
        # only escalate with confidence, never add 'scam' itself; the combined score decides that below.
        if llm.scam_probability >= thresholds()["llm_flag_min_confidence"]:
            flags += [f for f in llm.flags if f in WEIGHTS and f not in flags]
        score = round(max(score, 0.5 * score + 0.5 * llm.scam_probability), 3)
        expl.append(llm.explanation)
    if score >= thresholds()["maximum_risk_score"] or {"overpayment_scheme", "personal_info_request", "off_platform_payment"} & set(flags):
        flags.append("scam")
        score = max(score, thresholds()["maximum_risk_score"])
    rep = RiskReport(score=min(1.0, score), client_quality=round(q, 3), flags=list(dict.fromkeys(flags)),
                     injection_detected=bool(spans), injected_spans=spans,
                     explanation="; ".join(e for e in expl if e) or f"No red flags; client quality {q:.2f}.")
    return {"risk_report": rep.model_dump(), "sanitized_description": clean,
            "analyses": {"risk": {"score": rep.score, "flags": rep.flags}},
            "_summary": {"score": rep.score, "flags": rep.flags, "injection": rep.injection_detected}}

"""Fit Matcher: every requirement -> portfolio evidence (via the Portfolio MCP server), fit score with reasons."""

from __future__ import annotations

from agent.config import settings
from agent.guardrails import neutralise
from agent.handoffs import FitReport, RequirementEvidence
from agent.nodes.common import deps, node
from rag.skills import GENERIC, canonical, extract_skills

STRENGTH = {"strong": 1.0, "partial": 0.5, "none": 0.0}


def strength(cos: float, req: str = "", evidence_skills: set[str] | None = None, portfolio_skills: set[str] | None = None) -> str:
    """Named tools are judged by whether the evidence actually carries that skill (embeddings blur short
    tool names); descriptive requirements by cosine similarity."""
    f = settings()["fit"]
    named = set(extract_skills(req))
    if named and evidence_skills is not None:
        if named <= evidence_skills:
            return "strong"
        if named & (portfolio_skills or set()):
            return "partial"
        if cos < f["strong_cos"]:
            return "none"
    return "strong" if cos >= f["strong_cos"] else "partial" if cos >= f["partial_cos"] else "none"


def score_fit(matrix: list[RequirementEvidence], job_skills: list[str], portfolio_skills: set[str]) -> tuple[float, list[str], list[str]]:
    req_cov = sum(STRENGTH[m.strength] for m in matrix) / max(1, len(matrix))
    core = [s for s in job_skills if s not in GENERIC] or job_skills
    matched = [s for s in core if s in portfolio_skills]
    missing = [s for s in core if s not in portfolio_skills]
    if not core:
        return round(req_cov, 3), matched, missing
    skill_cov = len(matched) / len(core)
    return round(0.55 * req_cov + 0.45 * skill_cov, 3), matched, missing


@node("fit_matcher")
async def fit_matcher(state, config):
    job = state["job"]
    d = deps(config)
    clean, _ = neutralise(job.get("description", ""))
    res = await d.hub.call("fit_matcher", "match_job_requirements",
                           {"job_title": job.get("title", ""), "job_description": clean, "requirements": [], "k": 8})
    skills = await d.hub.call("fit_matcher", "list_skills", {})
    portfolio_skills = {s["skill"] for s in skills["skills"]}
    matrix = [RequirementEvidence(requirement=m["requirement"], evidence_ids=[e["evidence_id"] for e in m["evidence"]],
                                  titles=[e["title"] for e in m["evidence"]], best_score=round(m["best_score"], 3),
                                  strength=strength(m["best_score"], m["requirement"],
                                                    {s for e in m["evidence"] for s in e.get("skills", [])}, portfolio_skills))
              for m in res["requirements"]]
    job_skills = sorted({canonical(s) for s in job.get("skills") or []} | set(extract_skills(clean)))
    score, matched, missing = score_fit(matrix, job_skills, portfolio_skills)
    reasons = [f"'{m.requirement}': {m.strength} ({m.titles[0] if m.titles else 'no evidence'})" for m in matrix]
    if missing:
        reasons.append("No portfolio evidence for: " + ", ".join(missing))
    rep = FitReport(score=score, matched_skills=matched, missing_skills=missing,
                    evidence_ids=[i["evidence_id"] for i in res["ranked"]], matrix=matrix, reasons=reasons,
                    insufficient_evidence=res["insufficient_evidence"])
    evidence = [{k: i.get(k) for k in ("evidence_id", "type", "title", "project", "date", "outcome", "client_industry",
                                       "skills", "snippet", "source")} for i in res["ranked"]]
    return {"fit_report": rep.model_dump(), "evidence": evidence, "analyses": {"fit": {"score": score}},
            "_summary": {"score": score, "matched": matched[:6], "missing": missing[:6], "variant": res["variant"]}}

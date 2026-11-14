"""Job Analyst: job post -> JobSpec (LLM on the delimited, neutralised post; rules as fallback/merge)."""

from __future__ import annotations

import re

from agent.guardrails import neutralise
from agent.handoffs import JobSpec
from agent.llm import structured, untrusted
from agent.nodes.common import node
from rag.requirements import extract_requirements
from rag.skills import canonical, extract_skills


def rules_jobspec(job: dict) -> JobSpec:
    desc = job.get("description", "")
    deliv = re.search(r"Deliverables:\s*\n((?:\s*[-*].*\n?)+)", desc)
    industry = re.search(r"we are an? (?:\w+ )?([\w &]+?) (company|business|startup|agency)", desc, re.I)
    hidden = []
    if re.search(r"not technical|plain language", desc, re.I):
        hidden.append("plain-language explanations and a simple handover")
    if not re.search(r"document", desc, re.I):
        hidden.append("handover documentation")
    b = job.get("budget") or {}
    return JobSpec(
        job_id=job["job_id"], title=job.get("title", ""), category=job.get("category", ""),
        deliverables=[d.strip(" -*") for d in deliv.group(1).splitlines() if d.strip()] if deliv else [],
        required_skills=sorted({canonical(s) for s in (job.get("skills") or [])} | set(extract_skills(desc))),
        requirements=extract_requirements(job), budget_type=b.get("type", "fixed"), budget_min=b.get("min"),
        budget_max=b.get("max"), timeline_days=job.get("duration_days"), hours_per_week=job.get("hours_per_week"),
        screening_questions=job.get("screening_questions") or [], hidden_needs=hidden,
        client_industry=industry.group(1).strip() if industry else None, source="rules")


def merge(llm: JobSpec | None, rules: JobSpec) -> JobSpec:
    if llm is None:
        return rules
    # facts from the listing win over the model; the model adds decomposition and hidden needs
    reqs = list(dict.fromkeys([*rules.requirements[: len(rules.required_skills)], *llm.requirements]))[:10]
    return rules.model_copy(update={
        "requirements": reqs or rules.requirements,
        "required_skills": sorted(set(rules.required_skills) | {canonical(s) for s in llm.required_skills}),
        "nice_to_have": llm.nice_to_have, "hidden_needs": llm.hidden_needs or rules.hidden_needs,
        "deliverables": llm.deliverables or rules.deliverables,
        "client_industry": rules.client_industry or llm.client_industry, "source": "llm"})


@node("analyst")
async def analyst(state, config):
    job = state["job"]
    clean, _ = neutralise(job.get("description", ""))
    rules = rules_jobspec(job)
    llm = await structured("analyst", "analyst", JobSpec, config, job_id=job["job_id"], category=job.get("category", ""),
                           skills=job.get("skills", []), budget=job.get("budget"), screening=job.get("screening_questions", []),
                           job_post=untrusted("job_post", f"{job.get('title', '')}\n{clean}"))
    spec = merge(llm, rules)
    return {"job_spec": spec.model_dump(), "analyses": {"analyst": {"requirements": len(spec.requirements), "source": spec.source}},
            "_summary": {"requirements": spec.requirements[:6], "skills": spec.required_skills[:8], "source": spec.source}}

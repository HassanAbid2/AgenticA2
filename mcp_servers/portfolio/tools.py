"""Portfolio tools (read-only). Every tool is scoped to the caller's own portfolio (tenant)."""

from __future__ import annotations

import os
from collections import Counter
from functools import lru_cache
from typing import Literal

from mcp.server.fastmcp import Context
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from mcp_servers.common import audit, caller, trace_id

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
PERSONAS = {"ai_ml", "fullstack", "data_analyst"}
EvidenceType = Literal["case_study", "blog_post", "readme", "code", "review", "proposal", "cv", "upload"]


class EvidenceFilters(BaseModel):
    type: list[EvidenceType] | None = Field(None, description="Only these evidence types")
    outcome: list[Literal["won", "replied", "ignored"]] | None = Field(None, description="Past-proposal outcomes")
    project: str | None = Field(None, description="Exact project title")
    skills: list[str] | None = Field(None, description="Evidence tagged with any of these skills")


class EvidenceItem(BaseModel):
    evidence_id: str
    type: str
    title: str
    project: str | None = None
    source: str
    date: str | None = None
    outcome: str | None = None
    client_industry: str | None = None
    skills: list[str] = []
    snippet: str
    score: float
    matched_requirements: list[str] = []


class SearchResult(BaseModel):
    query: str
    items: list[EvidenceItem]


class RequirementMatch(BaseModel):
    requirement: str
    evidence: list[EvidenceItem]
    best_score: float


class MatchResult(BaseModel):
    requirements: list[RequirementMatch]
    ranked: list[EvidenceItem]
    insufficient_evidence: bool
    variant: str


class CaseStudy(BaseModel):
    evidence_id: str
    type: str
    title: str
    project: str | None
    date: str | None
    client_industry: str | None
    outcome: str | None
    skills: list[str]
    source: str
    text: str


class SkillCount(BaseModel):
    skill: str
    evidence_items: int
    projects: int


class SkillList(BaseModel):
    skills: list[SkillCount]


class ProjectHit(BaseModel):
    project: str
    score: float
    evidence_ids: list[str]


class ProjectList(BaseModel):
    projects: list[ProjectHit]


def owners_for(user: str) -> list[str]:
    """Tenants whose evidence this caller may read."""
    if user == "local":
        return [os.getenv("PORTFOLIO_OWNER", "local")]
    if user in PERSONAS:
        return [user]
    from shared.db import User, session

    with session() as s:
        u = s.get(User, int(user)) if user.isdigit() else None
    if not u:
        return []
    return [o for o in (u.persona if u.persona in PERSONAS else None, f"user-{u.id}") if o]


@lru_cache
def _retriever():
    from agent.config import settings
    from rag.retriever import build

    return build(settings()["rag"]["variant"])


def _index():
    from agent.config import settings
    from rag.index.store import get_index
    from rag.retriever import variant_config

    return get_index(variant_config(settings()["rag"]["variant"])["scheme"])


def _item(d: dict) -> EvidenceItem:
    return EvidenceItem(**{k: d.get(k) for k in ("evidence_id", "type", "title", "project", "source", "date", "outcome",
                                                 "client_industry", "score")},
                        skills=d.get("skills") or [], snippet=d.get("text", "")[:1200],
                        matched_requirements=d.get("matched_requirements") or [])


def register(mcp):
    @mcp.tool(annotations=READ, structured_output=True)
    def search_evidence(requirement: str = Field(min_length=2, max_length=2000, description="A job requirement or question, e.g. 'Celery background jobs'"),
                        k: int = Field(5, ge=1, le=20, description="How many evidence items"),
                        filters: EvidenceFilters | None = None, ctx: Context = None) -> SearchResult:
        """Find portfolio evidence (case studies, repos, code, reviews, past proposals with outcomes) that
        proves the freelancer can meet ONE requirement. Returns items with type, source, date and outcome."""
        user = caller(ctx)
        res = _retriever()(requirement, owners_for(user), k=k, filters=(filters.model_dump(exclude_none=True) if filters else None),
                           queries=[requirement])
        out = SearchResult(query=requirement, items=[_item(i) for i in res.items])
        audit("portfolio", user, "search_evidence", {"requirement": requirement, "k": k}, {"n": len(out.items)}, "ok", trace_id(ctx))
        return out

    @mcp.tool(annotations=READ, structured_output=True)
    def match_job_requirements(job_title: str = Field(max_length=500), job_description: str = Field(max_length=12000),
                               requirements: list[str] = Field(default_factory=list, max_length=12,
                                                               description="Extracted requirements; empty = extract automatically"),
                               k: int = Field(8, ge=1, le=20), ctx: Context = None) -> MatchResult:
        """Map every requirement of a job to the portfolio evidence that proves it (requirement-to-evidence
        matrix) using the deployed retrieval variant, plus an overall ranked evidence list."""
        from agent.config import settings

        user = caller(ctx)
        job = {"title": job_title, "description": job_description}
        res = _retriever()(job, owners_for(user), k=k, requirements=requirements or None)
        per = []
        by_id = {i["evidence_id"]: i for i in res.items}
        for q in res.requirements:
            ids = res.per_requirement.get(q, [])
            ev = [by_id[i] for i in ids if i in by_id][:3]
            if not ev:  # pull the requirement's own best hits even if they fell outside the overall top-k
                ev = _retriever()(q, owners_for(user), k=2, queries=[q]).items
            per.append(RequirementMatch(requirement=q, evidence=[_item(e) for e in ev],
                                        best_score=max([e.get("score", 0) for e in ev], default=0.0)))
        out = MatchResult(requirements=per, ranked=[_item(i) for i in res.items],
                          insufficient_evidence=bool(res.insufficient), variant=settings()["rag"]["variant"])
        audit("portfolio", user, "match_job_requirements", {"job_title": job_title, "n_requirements": len(requirements)},
              {"n": len(out.ranked)}, "ok", trace_id(ctx))
        return out

    @mcp.tool(annotations=READ, structured_output=True)
    def get_case_study(id: str = Field(min_length=2, max_length=200, description="evidence_id from search_evidence"),
                       ctx: Context = None) -> CaseStudy:
        """Full text and metadata of one evidence item (case study, README, code file, review or past proposal)."""
        user = caller(ctx)
        chunks = [c for c in _index().docs_for(owners_for(user)) if c.evidence_id == id]
        if not chunks:
            raise ValueError(f"no evidence item {id!r} in your portfolio")
        c = chunks[0]
        text = "\n\n".join(x.text for x in chunks)
        audit("portfolio", user, "get_case_study", {"id": id}, {"chars": len(text)}, "ok", trace_id(ctx))
        return CaseStudy(evidence_id=id, type=c.type, title=c.title, project=c.project, date=c.date,
                         client_industry=c.client_industry, outcome=c.outcome, skills=c.skills, source=c.source, text=text)

    @mcp.tool(annotations=READ, structured_output=True)
    def list_skills(ctx: Context = None) -> SkillList:
        """Every skill evidenced in the portfolio, with how many evidence items and projects support it."""
        user = caller(ctx)
        items, projects = Counter(), {}
        seen = set()
        for c in _index().docs_for(owners_for(user)):
            if c.evidence_id in seen:
                continue
            seen.add(c.evidence_id)
            for s in c.skills:
                items[s] += 1
                if c.project:
                    projects.setdefault(s, set()).add(c.project)
        return SkillList(skills=[SkillCount(skill=s, evidence_items=n, projects=len(projects.get(s, ())))
                                 for s, n in items.most_common()])

    @mcp.tool(annotations=READ, structured_output=True)
    def find_projects(skill: str | None = Field(None, max_length=100), industry: str | None = Field(None, max_length=100),
                      ctx: Context = None) -> ProjectList:
        """Answer 'have I done <skill> for a client in <industry>?' from the portfolio skill graph."""
        from rag.skills import canonical
        from rag.variants.v9_skill_graph import ask

        user = caller(ctx)
        hits = ask(_index(), owners_for(user), canonical(skill) if skill else None, industry)
        return ProjectList(projects=[ProjectHit(**h) for h in hits])

    return mcp

"""V9 skill graph (GraphRAG-lite): projects, skills, industries and proposal outcomes as a graph.

Answers "have I done X for a client in industry Y?" directly, and contributes a project ranking that
the pipeline fuses with dense/hybrid results.
"""

from __future__ import annotations

import math
import re

import networkx as nx

from rag.requirements import requirement_skills

CONFIG = {"graph": True}
TYPE_PRIORITY = {"case_study": 0, "code": 1, "readme": 2, "review": 3, "blog_post": 4, "proposal": 5, "cv": 6}


def build_graph(chunks) -> nx.Graph:
    g = nx.Graph()
    for c in chunks:
        if not c.project:
            continue
        p = ("project", c.project)
        g.add_node(p, kind="project")
        for s in c.skills:
            g.add_edge(p, ("skill", s))
        if c.client_industry:
            g.add_edge(p, ("industry", c.client_industry.lower()))
        if c.type == "proposal" and c.outcome in ("won", "replied"):
            g.nodes[p]["wins"] = g.nodes[p].get("wins", 0) + (1 if c.outcome == "won" else 0.5)
        g.add_edge(p, ("evidence", c.evidence_id), chunk=c)
    return g


_CACHE: dict[tuple, nx.Graph] = {}


def graph_for(index, owners):
    key = (id(index), tuple(sorted(owners)), index._mtime)  # rebuilt when the chunk store changes
    if key not in _CACHE:
        _CACHE[key] = build_graph(index.docs_for(owners))
    return _CACHE[key]


def project_scores(g: nx.Graph, skills: list[str], industry: str | None = None) -> dict[str, float]:
    projects = [n for n, d in g.nodes(data=True) if d.get("kind") == "project"]
    n = max(1, len(projects))
    scores = {}
    for p in projects:
        nbrs = set(g.neighbors(p))
        s = 0.0
        for sk in skills:
            if ("skill", sk) in nbrs:
                df = g.degree(("skill", sk))
                s += math.log(1 + n / max(1, df))
        if industry and ("industry", industry.lower()) in nbrs:
            s += 1.5
        if s > 0:
            s += 0.2 * g.nodes[p].get("wins", 0)
            scores[p[1]] = s
    return scores


def _industry(text: str, g: nx.Graph) -> str | None:
    inds = [n[1] for n in g.nodes if n[0] == "industry"]
    low = text.lower()
    hits = [i for i in inds if re.search(rf"\b{re.escape(i)}\b", low)]
    return max(hits, key=len) if hits else None


def graph_ranking(index, owners, job, queries):
    g = graph_for(index, owners)
    text = (job.get("title", "") + " " + job.get("description", "")) if isinstance(job, dict) else str(job)
    skills = sorted(set(requirement_skills(list(queries))) | set(job.get("skills", []) if isinstance(job, dict) else []))
    m = re.search(r"experience working with ([\w &]+?) clients", text, re.I)
    scores = project_scores(g, skills, m.group(1) if m else _industry(text, g))
    out = []
    for proj, s in sorted(scores.items(), key=lambda x: -x[1]):
        chunks = [d["chunk"] for _, _, d in g.edges(("project", proj), data=True) if "chunk" in d]
        chunks.sort(key=lambda c: TYPE_PRIORITY.get(c.type, 9))
        seen = set()
        for c in chunks:
            if c.evidence_id not in seen:
                seen.add(c.evidence_id)
                out.append((c, s))
    return out


def ask(index, owners, skill: str | None = None, industry: str | None = None) -> list[dict]:
    """'Have I done <skill> for a client in <industry>?' -> matching projects with evidence ids."""
    g = graph_for(index, owners)
    scores = project_scores(g, [skill] if skill else [], industry)
    res = []
    for proj, s in sorted(scores.items(), key=lambda x: -x[1]):
        nb = set(g.neighbors(("project", proj)))
        if skill and ("skill", skill) not in nb:
            continue
        if industry and ("industry", industry.lower()) not in nb:
            continue
        res.append({"project": proj, "score": round(s, 3),
                    "evidence_ids": sorted({n[1] for n in nb if n[0] == "evidence"})})
    return res

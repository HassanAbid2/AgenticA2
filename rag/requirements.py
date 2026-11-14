"""Deterministic requirement extraction from a job post (used by V1 and as the analyst's fallback)."""

from __future__ import annotations

import re

from rag.skills import canonical, extract_skills

FILLER = re.compile(r"^(strong |proven |hands-on |solid )?(experience (with|in) |knowledge of )?", re.I)
TAIL = re.compile(r"\s*\((must have|required|nice to have)\)\s*$|\s+work$", re.I)


def clean_requirement(line: str) -> str:
    line = line.strip().lstrip("-*• ").strip()
    line = TAIL.sub("", FILLER.sub("", line)).strip()
    return line


def job_text(job: dict) -> str:
    return f"{job.get('title', '')}\n{job.get('description', '')}"


def extract_requirements(job: dict, max_n: int = 8) -> list[str]:
    desc = job.get("description", "")
    reqs: list[str] = []
    m = re.search(r"Requirements:\s*\n((?:\s*[-*•].*\n?)+)", desc)
    if m:
        reqs += [clean_requirement(line) for line in m.group(1).splitlines() if line.strip()]
    for s in job.get("skills", []) or []:
        if canonical(s).lower() not in {canonical(r).lower() for r in reqs}:
            reqs.append(s)
    need = re.search(r"\bWe (?:need|are looking for) (.+?)(?:\.|\n|$)", desc, re.I)
    if need:
        reqs.append(need.group(1).strip())
    ind = re.search(r"experience working with ([\w &]+?) clients", desc, re.I)
    if ind:
        reqs.append(f"projects for {ind.group(1)} clients")
    if not reqs:  # vague post: use its sentences as requirements
        reqs = [s.strip() for s in re.split(r"(?<=[.!?])\s+", desc) if len(s.split()) > 4][:3]
    seen, out = set(), []
    for r in reqs:
        if r and r.lower() not in seen:
            seen.add(r.lower())
            out.append(r)
    return out[:max_n]


def requirement_skills(reqs: list[str]) -> list[str]:
    return sorted({s for r in reqs for s in extract_skills(r)})

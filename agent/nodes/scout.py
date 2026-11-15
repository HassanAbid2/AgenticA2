"""Scout: run saved searches, deduplicate, queue new jobs; and the bid graph's intake node.

Dedup: exact job id, then near-duplicates (same client, word-shingle Jaccard >= 0.8 on the normalised
title + description) so reposts like "... (reposted)" are linked to the original instead of analysed twice.
"""

from __future__ import annotations

import hashlib
import re

from agent.config import settings
from agent.nodes.common import deps, node

NEAR_DUP = 0.8


def normalise(job: dict) -> str:
    t = f"{job.get('title', '')} {job.get('description', '')}".lower()
    t = re.sub(r"\((re)?posted\)|\burgent\b|we are looking for|we need", " ", t)
    return re.sub(r"[^a-z ]+", " ", t)


def shingles(text: str, n: int = 5) -> set[str]:
    w = text.split()
    return {" ".join(w[i:i + n]) for i in range(max(1, len(w) - n + 1))}


def dedup_key(job: dict) -> str:
    return hashlib.sha1((job.get("client_id", "") + "|" + " ".join(normalise(job).split())[:400]).encode()).hexdigest()


def find_duplicate(job: dict, known: list[dict]) -> str | None:
    """known: previously seen jobs (dicts with job_id, client_id, title, description)."""
    sh = shingles(normalise(job))
    key = dedup_key(job)
    for k in known:
        if k["job_id"] == job["job_id"]:
            continue
        if dedup_key(k) == key:
            return k["job_id"]
        if k.get("client_id") == job.get("client_id"):
            o = shingles(normalise(k))
            if len(sh & o) / max(1, len(sh | o)) >= NEAR_DUP:
                return k["job_id"]
    return None


async def run_saved_searches(market, searches: list[dict], known: list[dict], posted_after: str = "") -> list[dict]:
    """Returns new jobs (not seen before), each annotated with duplicate_of when it is a repost."""
    seen = {k["job_id"] for k in known}
    out: list[dict] = []
    for s in searches:
        jobs = await market.search_jobs(query=s.get("query", ""), skills=s.get("skills") or [], category=s.get("category", ""),
                                        min_budget=s.get("min_budget", 0), posted_after=posted_after,
                                        limit=int(s.get("limit") or settings()["marketplace"]["max_jobs_per_search"]))
        for j in jobs:
            if j["job_id"] in seen:
                continue
            seen.add(j["job_id"])
            j["duplicate_of"] = find_duplicate(j, known + out)
            out.append(j)
    return out


@node("scout")
async def intake(state, config):
    """Scout hands a job in: load the full post through the marketplace port."""
    job = state.get("job") or await deps(config).market("scout").get_job(state["job_id"])
    return {"job": job, "job_id": job["job_id"], "status": "running",
            "_summary": {"title": job["title"], "duplicate_of": state.get("duplicate_of")}}

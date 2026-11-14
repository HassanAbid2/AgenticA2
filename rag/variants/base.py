"""Composable retrieval pipeline. Each variant file (v0_naive.py ... v9_skill_graph.py) contributes a
config fragment; `rag.retriever.build("v1+v2+v3")` merges them, so ablations drop one component.
"""

from __future__ import annotations

import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from rag.index.store import MODELS_DIR, Chunk, get_index
from rag.requirements import extract_requirements, job_text

DEFAULTS: dict[str, Any] = {
    "scheme": "structured",  # naive | structured | contextual
    "query": "whole",  # whole | decompose | hyde
    "retrieval": "dense",  # dense | hybrid
    "graph": False,  # V9 skill graph fused in
    "rerank": False,  # V3 cross-encoder
    "reranker_model": "Xenova/ms-marco-MiniLM-L-6-v2",
    "outcome_boost": False,  # V4
    "multivector": False,  # V5 group parts by project
    "corrective": False,  # V8 loop (wraps the pipeline)
    "candidates": 30,
    "rrf_k": 60,
}
OUTCOME_FACTOR = {"won": 1.5, "replied": 1.2, "ignored": 0.6}


@lru_cache
def cross_encoder(model: str):
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    return TextCrossEncoder(model, cache_dir=MODELS_DIR)


def rrf(lists: list[list[tuple[Chunk, float]]], k: int = 60) -> list[tuple[Chunk, float]]:
    score: dict[str, float] = defaultdict(float)
    by_id: dict[str, Chunk] = {}
    for lst in lists:
        for rank, (c, _) in enumerate(lst):
            score[c.chunk_id] += 1.0 / (k + rank + 1)
            by_id[c.chunk_id] = c
    return sorted(((by_id[i], s) for i, s in score.items()), key=lambda x: -x[1])


@dataclass
class RetrievalResult:
    items: list[dict]
    per_requirement: dict[str, list[str]] = field(default_factory=dict)
    requirements: list[str] = field(default_factory=list)
    strength: float = 0.0  # mean over queries of the best dense cosine
    insufficient: bool = False
    best_cos: dict[str, float] = field(default_factory=dict)  # per query: best dense cosine (absolute strength)
    trace: list[dict] = field(default_factory=list)
    latency_s: float = 0.0


class Pipeline:
    def __init__(self, cfg: dict, hyde_fn=None, rewrite_fn=None):
        self.cfg = DEFAULTS | cfg
        self.hyde_fn = hyde_fn
        self.rewrite_fn = rewrite_fn
        self.index = get_index(self.cfg["scheme"])

    # -- one query -> ranked chunk list
    def _search(self, q: str, owners, filters, trace) -> tuple[list[tuple[Chunk, float]], float]:
        C = self.cfg["candidates"]
        dense = self.index.dense(q, C, owners, filters)
        best_cos = dense[0][1] if dense else 0.0
        lists = [dense]
        if self.cfg["retrieval"] == "hybrid":
            lists.append(self.index.lexical(q, C, owners, filters))
        ranked = rrf(lists, self.cfg["rrf_k"]) if len(lists) > 1 else dense
        if self.cfg["rerank"] and ranked:
            ce = cross_encoder(self.cfg["reranker_model"])
            pool = ranked[:C]
            scores = list(ce.rerank(q, [c.text[:1200] for c, _ in pool]))
            ranked = sorted(((c, 1 / (1 + math.exp(-s))) for (c, _), s in zip(pool, scores, strict=True)), key=lambda x: -x[1])
        trace.append({"query": q[:120], "n": len(ranked), "best_cos": round(best_cos, 3)})
        return ranked, best_cos

    def queries(self, job: dict | str, requirements: list[str] | None) -> list[str]:
        if isinstance(job, str):
            job = {"title": "", "description": job}
        mode = self.cfg["query"]
        if mode == "decompose":
            return requirements or extract_requirements(job)
        if mode == "hyde":
            hypo = self.hyde_fn(job) if self.hyde_fn else None
            return [hypo or job_text(job)]
        return [job_text(job)]

    def retrieve(self, job: dict | str, owners, k: int = 10, filters=None,
                 requirements: list[str] | None = None, queries: list[str] | None = None) -> RetrievalResult:
        t0 = time.perf_counter()
        trace: list[dict] = []
        qs = queries or self.queries(job, requirements)
        lists, per_req, cos = [], {}, []
        for q in qs:
            ranked, best = self._search(q, owners, filters, trace)
            lists.append(ranked)
            cos.append(best)
            per_req[q] = list(dict.fromkeys(c.evidence_id for c, _ in ranked[:5]))
        if self.cfg["graph"]:
            from rag.variants.v9_skill_graph import graph_ranking

            lists.append(graph_ranking(self.index, owners, job, qs))
        fused = lists[0] if len(lists) == 1 else rrf(lists, self.cfg["rrf_k"])

        # evidence items: best chunk per evidence id
        best: dict[str, tuple[Chunk, float]] = {}
        for c, s in fused:
            if c.evidence_id not in best or s > best[c.evidence_id][1]:
                best[c.evidence_id] = (c, s)
        scored = list(best.values())
        if self.cfg["outcome_boost"]:
            scored = self._outcome_boost(scored, job, owners)
        scored.sort(key=lambda x: -x[1])
        if self.cfg["multivector"]:
            scored = self._group_by_project(scored)
        items = [self._item(c, s, qs, per_req) for c, s in scored[:k]]
        return RetrievalResult(items, per_req, qs, round(sum(cos) / max(1, len(cos)), 4), False,
                               {q: round(c, 4) for q, c in zip(qs, cos, strict=True)}, trace, round(time.perf_counter() - t0, 3))

    # -- V4
    def _outcome_boost(self, scored, job, owners):
        cat = job.get("category") if isinstance(job, dict) else None
        winners = defaultdict(float)
        for c in self.index.docs_for(owners):
            if c.type == "proposal" and c.project and c.outcome in ("won", "replied"):
                same = 1.0 if cat and cat.lower() in c.title.lower() else 0.5
                winners[c.project] += (1.0 if c.outcome == "won" else 0.5) * same
        out = []
        for c, s in scored:
            f = OUTCOME_FACTOR.get(c.outcome, 1.0) if c.type == "proposal" else 1.0
            if c.type != "proposal" and c.project and winners.get(c.project):
                f *= 1.0 + min(0.3, 0.1 * winners[c.project])
            out.append((c, s * f))
        return out

    # -- V5
    @staticmethod
    def _group_by_project(scored):
        groups: dict[str, list] = defaultdict(list)
        order: list[str] = []
        for c, s in scored:
            key = c.project or c.evidence_id
            if key not in groups:
                order.append(key)
            groups[key].append((c, s))
        pscore = {key: g[0][1] + 0.15 * sum(s for _, s in g[1:3]) for key, g in groups.items()}
        out = []
        for key in sorted(order, key=lambda k: -pscore[k]):
            out.extend(groups[key])
        return out

    @staticmethod
    def _item(c: Chunk, s: float, qs, per_req) -> dict:
        matched = [q for q in qs if c.evidence_id in per_req.get(q, [])]
        return {"evidence_id": c.evidence_id, "chunk_id": c.chunk_id, "type": c.type, "title": c.title,
                "project": c.project, "date": c.date, "outcome": c.outcome, "source": c.source,
                "client_industry": c.client_industry, "skills": c.skills, "text": c.text,
                "score": round(float(s), 5), "matched_requirements": matched}

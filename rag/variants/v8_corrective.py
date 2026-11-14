"""V8 corrective RAG as a small LangGraph loop: retrieve -> grade -> (rewrite -> retrieve)* -> finish.

Grading uses the best dense cosine per query (cheap, no LLM). Weak evidence triggers a query
rewrite (LLM if configured, alias expansion otherwise), at most `max_rewrites` times. If evidence is
still weak the result is marked insufficient and items below the floor are dropped: the writer is
told to make no claim rather than stretch weak evidence.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from rag.skills import extract_skills, lexicon

CONFIG = {"corrective": True}
THRESHOLD = 0.78  # per-query best cosine counted as "supported" (calibrated on dev, see evals)
FLOOR = 0.72  # below this an item is not shown to the writer at all
MIN_COVERAGE = 0.5


class CState(TypedDict, total=False):
    job: Any
    owners: list[str]
    k: int
    queries: list[str]
    attempt: int
    result: Any
    coverage: float


def alias_rewrite(queries: list[str]) -> list[str]:
    out = []
    for q in queries:
        extra = [a for s in extract_skills(q) for a in lexicon()[s].get("aliases", [])[:2]]
        out.append(f"built and delivered {q} {' '.join(extra)}".strip())
    return out


def make_corrective(pipeline, rewrite_fn=None, max_rewrites: int = 2):
    def retrieve(s: CState):
        r = pipeline.retrieve(s["job"], s["owners"], s["k"], queries=s.get("queries"))
        good = [t for t in r.trace if t["best_cos"] >= THRESHOLD]
        cov = len(good) / max(1, len(r.trace))
        return {"result": r, "queries": r.requirements, "coverage": cov}

    def grade(s: CState):
        if s["coverage"] >= MIN_COVERAGE or s.get("attempt", 0) >= max_rewrites:
            return "finish"
        return "rewrite"

    def rewrite(s: CState):
        weak = [t["query"] for t in s["result"].trace if t["best_cos"] < THRESHOLD]
        strong = [q for q in s["queries"] if q[:120] not in weak]
        fn = rewrite_fn or alias_rewrite
        try:
            new = fn([q for q in s["queries"] if q[:120] in weak])
        except Exception:  # noqa: BLE001
            new = alias_rewrite([q for q in s["queries"] if q[:120] in weak])
        return {"queries": strong + new, "attempt": s.get("attempt", 0) + 1}

    def finish(s: CState):
        r = s["result"]
        r.trace.append({"corrective_attempts": s.get("attempt", 0), "coverage": round(s["coverage"], 3)})
        if s["coverage"] < MIN_COVERAGE:
            r.insufficient = True
            if r.strength < FLOOR:
                r.items = []  # refuse to claim: nothing is strong enough to cite
        return {"result": r}

    g = StateGraph(CState)
    g.add_node("retrieve", retrieve)
    g.add_node("rewrite", rewrite)
    g.add_node("finish", finish)
    g.add_edge(START, "retrieve")
    g.add_conditional_edges("retrieve", grade, {"rewrite": "rewrite", "finish": "finish"})
    g.add_edge("rewrite", "retrieve")
    g.add_edge("finish", END)
    graph = g.compile()

    def run(job, owners, k=10, filters=None, requirements=None, queries=None):
        return graph.invoke({"job": job, "owners": list(owners), "k": k, "queries": queries or requirements,
                             "attempt": 0})["result"]

    return run

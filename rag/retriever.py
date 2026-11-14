"""Retriever factory: the deployed variant is chosen by config (agent/config.yaml -> rag.variant),
which in turn was chosen by the evaluation in evals/results/rag_variants.json.

    build("v1+v2+v3")  -> callable(job, owners, k=10, filters=None, requirements=None) -> RetrievalResult
"""

from __future__ import annotations

import importlib

from rag.variants.base import DEFAULTS, Pipeline

MODULES = {
    "v0": "v0_naive", "v1": "v1_decompose", "v2": "v2_hybrid", "v3": "v3_rerank", "v4": "v4_outcome",
    "v5": "v5_multivector", "v6": "v6_contextual", "v7": "v7_hyde", "v8": "v8_corrective", "v9": "v9_skill_graph",
}


def variant_config(spec: str) -> dict:
    cfg = dict(DEFAULTS)
    for part in [p.strip().lower() for p in spec.split("+") if p.strip()]:
        if part not in MODULES:
            raise ValueError(f"unknown RAG variant {part!r}; expected one of {sorted(MODULES)}")
        cfg |= importlib.import_module(f"rag.variants.{MODULES[part]}").CONFIG
    return cfg


def build(spec: str, llm_text=None, overrides: dict | None = None):
    cfg = variant_config(spec) | (overrides or {})
    hyde_fn = rewrite_fn = None
    if cfg["query"] == "hyde":
        from rag.variants.v7_hyde import make_hyde_fn, template_hypothesis

        hyde_fn = make_hyde_fn(llm_text) if llm_text else template_hypothesis
    if llm_text:
        def rewrite_fn(qs):
            out = llm_text("query_rewrite", requirements="\n".join(f"- {q}" for q in qs))
            return [line.lstrip("-* ").strip() for line in out.splitlines() if line.strip()][: len(qs) + 2] or qs
    pipe = Pipeline(cfg, hyde_fn=hyde_fn)
    if cfg["corrective"]:
        from rag.variants.v8_corrective import make_corrective

        return make_corrective(pipe, rewrite_fn)
    return pipe.retrieve


def default_retriever(llm_text=None):
    from agent.config import settings

    return build(settings()["rag"]["variant"], llm_text)

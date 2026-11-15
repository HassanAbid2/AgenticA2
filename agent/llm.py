"""Model routing, prompts, structured output, usage/cost accounting and response caching.

Every node's model comes from agent/config.yaml (profile -> nodes); every prompt comes from
agent/prompts/<name>.md. Profile `offline` (or a missing API key) returns no model and nodes use
their deterministic implementations.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from string import Template
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from pydantic import BaseModel

from agent.config import ROOT, settings

log = logging.getLogger("gigbid.llm")
PROMPTS = ROOT / "agent" / "prompts"


# ----------------------------------------------------------------------------- prompts
@lru_cache
def _prompt_file(name: str) -> tuple[str, str]:
    text = (PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    text = re.sub(r"<!--.*?-->\s*", "", text, count=1, flags=re.S)  # version header
    if "## user" in text:
        sys_part, user_part = text.split("## user", 1)
        return sys_part.replace("## system", "", 1).strip(), user_part.strip()
    return "", text.strip()


def render(name: str, **vars) -> tuple[str, str]:
    s, u = _prompt_file(name)
    v = {k: (x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)) for k, x in vars.items()}
    return Template(s).safe_substitute(v), Template(u).safe_substitute(v)


def untrusted(label: str, text: str, limit: int = 6000) -> str:
    """Delimit untrusted marketplace text. Tag-like sequences inside are neutralised so a post cannot
    close the block and speak as the system."""
    body = (text or "")[:limit].replace("<", "‹").replace(">", "›")
    return f"<untrusted_{label}>\n{body}\n</untrusted_{label}>"


# ----------------------------------------------------------------------------- usage tracking
class UsageTracker(BaseCallbackHandler):
    """Collects tokens, USD and latency per node for one run (thread-safe; shared by parallel branches)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.per_node: dict[str, dict[str, float]] = defaultdict(lambda: {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "llm_calls": 0, "llm_s": 0.0})
        self._t0: dict[Any, float] = {}
        self._node: dict[Any, str] = {}

    def _start(self, run_id, kw):
        md = kw.get("metadata") or {}
        self._t0[run_id] = time.perf_counter()
        self._node[run_id] = md.get("gigbid_node") or md.get("langgraph_node") or "other"

    def on_chat_model_start(self, serialized, messages, *, run_id, **kw):
        self._start(run_id, kw)

    def on_llm_start(self, serialized, prompts, *, run_id, **kw):
        self._start(run_id, kw)

    def on_llm_end(self, response, *, run_id, **kw):
        node = self._node.pop(run_id, None) or (kw.get("metadata") or {}).get("gigbid_node") or "other"
        inp = out = 0
        model = ""
        for gens in response.generations:
            for g in gens:
                um = getattr(getattr(g, "message", None), "usage_metadata", None) or {}
                inp += um.get("input_tokens", 0)
                out += um.get("output_tokens", 0)
                model = (getattr(getattr(g, "message", None), "response_metadata", {}) or {}).get("model_name", model)
        if not (inp or out) and response.llm_output:
            tu = response.llm_output.get("token_usage", {}) or {}
            inp, out = tu.get("prompt_tokens", 0), tu.get("completion_tokens", 0)
            model = response.llm_output.get("model_name", model)
        price = settings()["models"]["pricing"].get(model) or settings()["models"]["pricing"].get(model.split("/")[-1], [0, 0])
        with self.lock:
            d = self.per_node[node]
            d["input_tokens"] += inp
            d["output_tokens"] += out
            d["cost_usd"] += (inp * price[0] + out * price[1]) / 1e6
            d["llm_calls"] += 1
            d["llm_s"] += time.perf_counter() - self._t0.pop(run_id, time.perf_counter())

    def total_tokens(self) -> int:
        with self.lock:
            return int(sum(d["input_tokens"] + d["output_tokens"] for d in self.per_node.values()))

    def total_cost(self) -> float:
        with self.lock:
            return round(sum(d["cost_usd"] for d in self.per_node.values()), 6)

    def snapshot(self) -> dict:
        with self.lock:
            return {k: dict(v) for k, v in self.per_node.items()}


# ----------------------------------------------------------------------------- models
_cache_ready = False


class SQLiteLLMCache:
    """Minimal persistent LLM cache (prompt + model params -> generations) so evals rerun for free.
    ponytail: single-file SQLite; fine for one machine, swap for Redis if workers share it."""

    def __init__(self, path: Path):
        import sqlite3

        self.db = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
        self.db.execute("CREATE TABLE IF NOT EXISTS c (k TEXT PRIMARY KEY, v TEXT)")
        self.lock = threading.Lock()

    @staticmethod
    def _k(prompt, llm_string):
        import hashlib

        return hashlib.sha256((prompt + "|" + llm_string).encode()).hexdigest()

    def lookup(self, prompt, llm_string):
        from langchain_core.load import loads

        with self.lock:
            row = self.db.execute("SELECT v FROM c WHERE k=?", (self._k(prompt, llm_string),)).fetchone()
        return [loads(g) for g in json.loads(row[0])] if row else None

    def update(self, prompt, llm_string, return_val):
        from langchain_core.load import dumps

        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO c VALUES (?, ?)", (self._k(prompt, llm_string), json.dumps([dumps(g) for g in return_val])))
            self.db.commit()

    async def alookup(self, prompt, llm_string):
        return self.lookup(prompt, llm_string)

    async def aupdate(self, prompt, llm_string, return_val):
        self.update(prompt, llm_string, return_val)

    def clear(self, **kw):
        with self.lock:
            self.db.execute("DELETE FROM c")
            self.db.commit()


def _setup_cache():
    global _cache_ready
    if _cache_ready or not settings()["models"].get("cache"):
        return
    from langchain_core.caches import BaseCache
    from langchain_core.globals import set_llm_cache

    (ROOT / "var").mkdir(exist_ok=True)
    BaseCache.register(SQLiteLLMCache)
    set_llm_cache(SQLiteLLMCache(ROOT / "var" / "llm_cache.db"))
    _cache_ready = True


def model_name(node: str) -> str | None:
    prof = settings()["models"]["profiles"][settings()["models"]["profile"]]
    nodes = prof.get("nodes") or {}
    return nodes.get(node) or nodes.get("default")


@lru_cache(maxsize=64)
def _chat(model: str, base_url: str, key_env: str, temperature: float, fallback: str | None):
    from langchain_openai import ChatOpenAI

    m = settings()["models"]
    key = os.getenv(key_env) or ("ollama" if "11434" in base_url else None)
    if not key:
        return None
    mk = lambda name: ChatOpenAI(model=name, base_url=base_url, api_key=key, temperature=temperature,  # noqa: E731
                                 timeout=m["timeout_s"], max_retries=m["max_retries"])
    llm = mk(model)
    return llm.with_fallbacks([mk(fallback)]) if fallback and fallback != model else llm


def get_chat(node: str, temperature: float | None = None):
    """The node's chat model, or None when running offline / without credentials."""
    prof_name = settings()["models"]["profile"]
    if prof_name == "offline":
        return None
    prof = settings()["models"]["profiles"][prof_name]
    name = model_name(node)
    if not name:
        return None
    try:
        _setup_cache()
    except Exception as e:  # noqa: BLE001 - cache is an optimisation
        log.debug("llm cache disabled: %s", e)
    cheap = node not in ("writer", "critic", "liaison", "judge", "baseline")
    return _chat(name, prof["base_url"], prof["api_key_env"],
                 settings()["models"]["temperature"] if temperature is None else temperature,
                 prof.get("fallback") if cheap else None)


def llm_available(node: str = "writer") -> bool:
    return get_chat(node) is not None


def _json_from(text: str) -> Any:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
    if start < 0:
        raise ValueError("no JSON in model output")
    end = max(text.rfind("}"), text.rfind("]"))
    return json.loads(text[start: end + 1])


async def structured(node: str, prompt: str, schema: type[BaseModel], config=None, **vars) -> BaseModel | None:
    """Prompt -> JSON -> validated Pydantic object. Returns None when no model is configured or the
    model fails twice; callers then use their deterministic path."""
    llm = get_chat(node)
    if llm is None:
        return None
    sys_p, user_p = render(prompt, **vars, schema=json.dumps(schema.model_json_schema()))
    msgs = ([("system", sys_p)] if sys_p else []) + [("user", user_p)]
    cfg = {"metadata": {"gigbid_node": node}, "tags": [node]}
    if config:
        cfg["callbacks"] = config.get("callbacks")
    last = None
    for attempt in range(2):
        try:
            retry = [("user", render("json_retry", error=last)[1])] if attempt else []
            res = await llm.ainvoke(msgs + retry, config=cfg)
            return schema.model_validate(_json_from(res.content))
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {str(e)[:200]}"
            log.warning("structured(%s) attempt %d failed: %s", node, attempt + 1, last)
            # production degrades to the deterministic path; evals must not silently mix the two
            if os.getenv("GIGBID_STRICT_LLM") == "1" and not isinstance(e, ValueError | json.JSONDecodeError):
                raise
    return None


async def text(node: str, prompt: str, config=None, **vars) -> str | None:
    llm = get_chat(node)
    if llm is None:
        return None
    sys_p, user_p = render(prompt, **vars)
    msgs = ([("system", sys_p)] if sys_p else []) + [("user", user_p)]
    cfg = {"metadata": {"gigbid_node": node}, "tags": [node]} | ({"callbacks": config.get("callbacks")} if config else {})
    res = await llm.ainvoke(msgs, config=cfg)
    return re.sub(r"<think>.*?</think>", "", res.content, flags=re.S).strip()


def sync_text(node: str, prompt: str, **vars) -> str:
    """Sync helper for RAG components (HyDE, query rewrite) that run outside the event loop."""
    llm = get_chat(node)
    if llm is None:
        raise RuntimeError("no model")
    sys_p, user_p = render(prompt, **vars)
    msgs = ([("system", sys_p)] if sys_p else []) + [("user", user_p)]
    return re.sub(r"<think>.*?</think>", "", llm.invoke(msgs, config={"metadata": {"gigbid_node": node}}).content, flags=re.S).strip()


def prompt_path(name: str) -> Path:
    return PROMPTS / f"{name}.md"

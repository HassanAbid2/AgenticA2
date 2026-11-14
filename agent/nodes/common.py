"""Per-run dependencies and the node wrapper shared by every agent node."""

from __future__ import annotations

import functools
import time
from dataclasses import dataclass, field
from typing import Any

from langgraph.config import get_stream_writer

from agent.config import settings
from agent.llm import UsageTracker
from agent.marketplace_port import MCPMarketplace
from agent.mcp_client import MCPHub


@dataclass
class Deps:
    hub: MCPHub
    usage: UsageTracker
    profile: dict  # freelancer profile: name, headline, rates, floors, persona
    user_settings: dict = field(default_factory=dict)
    store: Any = None  # LangGraph BaseStore (long-term memory)
    strategy: str | None = None  # X2 arm override (experiments)

    def market(self, node: str) -> MCPMarketplace:
        return MCPMarketplace(self.hub, node)

    def setting(self, key: str, default=None):
        return self.user_settings.get(key, self.profile.get(key, default))


def deps(config) -> Deps:
    return config["configurable"]["deps"]


def thresholds() -> dict:
    return settings()["thresholds"]


def emit(event: dict):
    try:
        get_stream_writer()(event)
    except Exception:  # noqa: BLE001 - outside a streaming run
        pass


def node(name: str):
    """Wraps a node: streams start/end events, counts a step, attributes tokens, and moves the MCP
    calls made during the node into the execution trace."""

    def deco(fn):
        @functools.wraps(fn)
        async def wrapped(state, config):
            d = deps(config)
            before = d.usage.total_tokens()
            t0 = time.perf_counter()
            emit({"node": name, "kind": "node_start"})
            out = await fn(state, config) or {}
            dt = round(time.perf_counter() - t0, 3)
            calls = d.hub.drain()
            used = d.usage.total_tokens() - before
            summary = out.pop("_summary", None)
            entry = {"node": name, "kind": "node", "latency_s": dt, "tokens": used, "summary": summary, "ts": time.time()}
            out["trace"] = calls + [entry] + out.get("trace", [])
            out["steps"] = 1
            out["tokens"] = used
            emit({"node": name, "kind": "node_end", "latency_s": dt, "tokens": used, "summary": summary,
                  "tool_calls": [{"tool": c["tool"], "ms": c["ms"], "error": c["error"]} for c in calls]})
            return out

        wrapped.__gigbid_node__ = name
        return wrapped

    return deco


def over_budget(state) -> str | None:
    b = settings()["budgets"]
    if state.get("steps", 0) >= b["max_graph_steps"]:
        return f"step budget exceeded ({state.get('steps')} >= {b['max_graph_steps']})"
    if state.get("tokens", 0) >= b["max_tokens_per_job"]:
        return f"token budget exceeded ({state.get('tokens')} >= {b['max_tokens_per_job']})"
    return None

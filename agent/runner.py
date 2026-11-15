"""Graph runner used by the worker, the API and the evals: opens the durable checkpointer + memory
store, wires per-run deps (MCP hub, usage tracker, profile), streams node events and returns the
resulting state, pending interrupt and usage."""

from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from langgraph.types import Command

from agent.config import ROOT
from agent.graphs.bid_graph import build_bid_graph
from agent.graphs.conversation_graph import build_conversation_graph
from agent.llm import UsageTracker
from agent.mcp_client import MCPHub
from agent.memory.store import open_checkpointer, open_store
from agent.nodes.common import Deps
from shared.tracing import setup_tracing

PERSONAS = ("ai_ml", "fullstack", "data_analyst")


def persona_profile(persona: str) -> dict:
    p = ROOT / "data" / "personas" / persona / "profile.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"name": "Freelancer", "headline": "",
                                                                          "hourly_rate": 30, "floor_hourly": 20, "min_fixed": 150}


@contextmanager
def _span(name: str, trace_id: str | None, attrs: dict):
    """Run span that joins the caller's trace id (passed across processes as a hex string)."""
    from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, set_span_in_context

    tracer = setup_tracing("gigbid-agent")
    ctx = None
    if trace_id and len(trace_id) == 32:
        parent = SpanContext(trace_id=int(trace_id, 16), span_id=uuid.uuid4().int & ((1 << 64) - 1), is_remote=True,
                             trace_flags=TraceFlags(TraceFlags.SAMPLED))
        ctx = set_span_in_context(NonRecordingSpan(parent))
    with tracer.start_as_current_span(name, context=ctx, attributes=attrs) as span:
        yield span


async def _run(graph_builder, thread_id: str, inp: Any, deps: Deps, trace_id: str, on_event=None, meta=None) -> dict:
    t0 = time.perf_counter()
    async with open_checkpointer() as cp, open_store() as store:
        deps.store = store
        graph = graph_builder(cp, store)
        cfg = {"configurable": {"thread_id": thread_id, "deps": deps}, "callbacks": [deps.usage],
               "metadata": {"trace_id": trace_id, "user_id": deps.hub.user_id, **(meta or {})}, "recursion_limit": 80}
        with _span(f"{graph.name}:{thread_id}", trace_id, {"gigbid.thread_id": thread_id, "gigbid.user_id": deps.hub.user_id}):
            async for mode, chunk in graph.astream(inp, cfg, stream_mode=["updates", "custom"]):
                if on_event:
                    on_event(mode, chunk)
        snap = await graph.aget_state(cfg)
    interrupts = [i.value for t in snap.tasks for i in (t.interrupts or ())]
    return {"thread_id": thread_id, "state": snap.values, "next": list(snap.next), "interrupt": interrupts[0] if interrupts else None,
            "usage": deps.usage.snapshot(), "tokens": deps.usage.total_tokens(), "cost_usd": deps.usage.total_cost(),
            "latency_s": round(time.perf_counter() - t0, 3)}


def bid_thread_id(user_id: str, job_id: str, suffix: str = "") -> str:
    return f"bid-{user_id}-{job_id}{suffix}"


async def _has_checkpoint(thread_id: str) -> bool:
    async with open_checkpointer() as cp:
        return await cp.aget_tuple({"configurable": {"thread_id": thread_id}}) is not None


async def run_bid(user_id: str, job_id: str, *, profile: dict, user_settings: dict | None = None, owners=None,
                  job: dict | None = None, duplicate_of: str | None = None, force_bid: bool = False, resume: dict | None = None,
                  cont: bool = False, thread_id: str | None = None, trace_id: str | None = None, on_event=None,
                  strategy: str | None = None) -> dict:
    """start (default) | resume=<approval decision> | cont=True (re-run a failed node from the checkpoint)."""
    trace_id = trace_id or uuid.uuid4().hex
    thread_id = thread_id or bid_thread_id(user_id, job_id)
    deps = Deps(MCPHub(user_id, trace_id), UsageTracker(), profile, user_settings or {}, strategy=strategy)
    if resume is not None:
        inp = Command(resume=resume)
    elif cont and await _has_checkpoint(thread_id):
        inp = None
    else:  # fresh start, also for a parked job whose first run failed before any checkpoint was written
        inp = {"user_id": str(user_id), "job_id": job_id, "trace_id": trace_id, "force_bid": force_bid,
               "duplicate_of": duplicate_of, "revision": 0, "owners": owners or []} | ({"job": job} if job else {})
    return await _run(build_bid_graph, thread_id, inp, deps, trace_id, on_event, {"job_id": job_id})


async def run_conversation(user_id: str, marketplace_thread_id: str, *, profile: dict, user_settings: dict | None = None,
                           resume: dict | None = None, graph_thread_id: str | None = None, trace_id: str | None = None,
                           on_event=None) -> dict:
    trace_id = trace_id or uuid.uuid4().hex
    deps = Deps(MCPHub(user_id, trace_id), UsageTracker(), profile, user_settings or {})
    tid = graph_thread_id or f"conv-{user_id}-{marketplace_thread_id}-{int(time.time())}"
    inp = Command(resume=resume) if resume is not None else {"user_id": str(user_id), "thread_id": marketplace_thread_id,
                                                              "trace_id": trace_id}
    return await _run(build_conversation_graph, tid, inp, deps, trace_id, on_event, {"marketplace_thread": marketplace_thread_id})


async def history(graph: str, thread_id: str) -> list[dict]:
    """Checkpoint history for replay (C6): every checkpoint with the node that produced it."""
    builder = build_bid_graph if graph == "bid" else build_conversation_graph
    out = []
    async with open_checkpointer() as cp:
        g = builder(cp)
        async for s in g.aget_state_history({"configurable": {"thread_id": thread_id}}):
            out.append({"checkpoint_id": s.config["configurable"]["checkpoint_id"], "next": list(s.next),
                        "step": s.metadata.get("step"), "source": s.metadata.get("source"),
                        "writes": list((s.metadata.get("writes") or {}).keys()), "created_at": s.created_at})
    return out


async def replay_from(graph: str, thread_id: str, checkpoint_id: str, deps: Deps, trace_id: str, on_event=None) -> dict:
    """Re-execute a thread from any earlier checkpoint (forks the thread history at that point)."""
    builder = build_bid_graph if graph == "bid" else build_conversation_graph
    async with open_checkpointer() as cp, open_store() as store:
        deps.store = store
        g = builder(cp, store)
        cfg = {"configurable": {"thread_id": thread_id, "checkpoint_id": checkpoint_id, "deps": deps}, "callbacks": [deps.usage]}
        async for mode, chunk in g.astream(None, cfg, stream_mode=["updates", "custom"]):
            if on_event:
                on_event(mode, chunk)
        snap = await g.aget_state({"configurable": {"thread_id": thread_id}})
    return {"state": snap.values, "next": list(snap.next)}


def render_graphs(out_dir: Path | None = None):
    out_dir = out_dir or ROOT / "docs" / "images"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, b in (("bid_graph", build_bid_graph), ("conversation_graph", build_conversation_graph)):
        (out_dir / f"{name}.mmd").write_text(b().get_graph().draw_mermaid(), encoding="utf-8", newline="\n")
    return out_dir


if __name__ == "__main__":
    print(render_graphs())

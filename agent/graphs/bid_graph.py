"""Bid graph (one thread per job), hand-written StateGraph (R3, C1).

scout -> {analyst | risk_assessor | fit_matcher} (parallel via Send) -> decide
  -> skip/watch: END
  -> bid: recall_memory -> pricing -> writer -> verifier -> critic
        critic -> revise -> writer (at most `budgets.max_revisions` times)
        critic -> compliance -> (block: END) -> prepare_approval -> human_approval [interrupt]
        human_approval -> approve: submit | edit: compliance_recheck -> submit / human_approval | reject: END
Any routing point can divert to needs_attention when the step or token budget is exceeded (C4).
Per-node retries + timeouts (C7); MarketplaceUnavailable propagates so the runner can park the job
in degraded mode and resume it later from the checkpoint.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy, Send

from agent.config import settings
from agent.mcp_client import MarketplaceRejected, ToolCallError, ToolNotAllowed
from agent.nodes.analyst import analyst
from agent.nodes.approval import (
    compliance_recheck,
    human_approval,
    needs_attention,
    prepare_approval,
    recall_memory,
    submit,
)
from agent.nodes.common import over_budget
from agent.nodes.compliance import compliance
from agent.nodes.critic import critic, revise
from agent.nodes.decision import decision_node
from agent.nodes.fit_matcher import fit_matcher
from agent.nodes.pricing import pricing
from agent.nodes.risk_assessor import risk_assessor
from agent.nodes.scout import intake
from agent.nodes.verifier import verifier
from agent.nodes.writer import writer
from agent.state import BidState

PARALLEL = ("analyst", "risk_assessor", "fit_matcher")


def _transient(e: BaseException) -> bool:
    return isinstance(e, TimeoutError | ToolCallError) and not isinstance(e, ToolNotAllowed | MarketplaceRejected)


RETRY = RetryPolicy(max_attempts=3, initial_interval=1.0, backoff_factor=2.0, max_interval=10.0, retry_on=_transient)


def fan_out(state: BidState):
    return [Send(n, state) for n in PARALLEL]


def route_decision(state: BidState) -> str:
    if over_budget(state):
        return "needs_attention"
    return "bid" if state.get("decision", {}).get("action") == "bid" else "end"


def route_critic(state: BidState) -> str:
    if over_budget(state):
        return "needs_attention"
    last = (state.get("critiques") or [{}])[-1]
    if last.get("approve"):
        return "ok"
    if state.get("revision", 0) >= settings()["budgets"]["max_revisions"]:
        auto = last.get("auto") or {}
        # nothing grounded survived verification: never hand the human an evidence-free letter
        return "needs_attention" if not auto.get("supported_claims") else "ok"
    return "revise"


def route_compliance(state: BidState) -> str:
    if state.get("status") == "blocked":
        return "block"
    return "needs_attention" if over_budget(state) else "ok"


def route_approval(state: BidState) -> str:
    last = (state.get("approvals") or [{}])[-1]
    return {"approve": "submit", "edit": "recheck", "reject": "end"}.get(last.get("action"), "end")


def route_recheck(state: BidState) -> str:
    return "submit" if state.get("status") == "approved" else "human_approval"


def builder() -> StateGraph:
    g = StateGraph(BidState)
    g.add_node("scout", intake, retry_policy=RETRY, timeout=60)
    g.add_node("analyst", analyst, retry_policy=RETRY, timeout=120)
    g.add_node("risk_assessor", risk_assessor, retry_policy=RETRY, timeout=120)
    g.add_node("fit_matcher", fit_matcher, retry_policy=RETRY, timeout=120)
    g.add_node("decide", decision_node)
    g.add_node("recall_memory", recall_memory)
    g.add_node("pricing", pricing, retry_policy=RETRY, timeout=60)
    g.add_node("writer", writer, retry_policy=RETRY, timeout=240)
    g.add_node("verifier", verifier, timeout=180)
    g.add_node("critic", critic, retry_policy=RETRY, timeout=180)
    g.add_node("revise", revise)
    g.add_node("compliance", compliance, timeout=120)
    g.add_node("prepare_approval", prepare_approval, retry_policy=RETRY, timeout=60)
    g.add_node("human_approval", human_approval)
    g.add_node("compliance_recheck", compliance_recheck, timeout=120)
    g.add_node("submit", submit, retry_policy=RETRY, timeout=90)
    g.add_node("needs_attention", needs_attention)

    g.add_edge(START, "scout")
    g.add_conditional_edges("scout", fan_out, list(PARALLEL))
    for n in PARALLEL:
        g.add_edge(n, "decide")
    g.add_conditional_edges("decide", route_decision, {"bid": "recall_memory", "end": END, "needs_attention": "needs_attention"})
    g.add_edge("recall_memory", "pricing")
    g.add_edge("pricing", "writer")
    g.add_edge("writer", "verifier")
    g.add_edge("verifier", "critic")
    g.add_conditional_edges("critic", route_critic, {"revise": "revise", "ok": "compliance", "needs_attention": "needs_attention"})
    g.add_edge("revise", "writer")
    g.add_conditional_edges("compliance", route_compliance, {"block": END, "ok": "prepare_approval", "needs_attention": "needs_attention"})
    g.add_edge("prepare_approval", "human_approval")
    g.add_conditional_edges("human_approval", route_approval, {"submit": "submit", "recheck": "compliance_recheck", "end": END})
    g.add_conditional_edges("compliance_recheck", route_recheck, {"submit": "submit", "human_approval": "human_approval"})
    g.add_edge("submit", END)
    g.add_edge("needs_attention", END)
    return g


def build_bid_graph(checkpointer=None, store=None):
    return builder().compile(checkpointer=checkpointer, store=store, name="bid_graph")

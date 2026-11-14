"""Conversation graph (one thread per client conversation).

load -> classify intent -> draft reply (slots from Workspace / floor price / evidence) -> compliance
     -> approval [interrupt] -> send (+ tentative calendar holds) -> END
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from agent.graphs.bid_graph import RETRY
from agent.nodes.client_liaison import (
    classify,
    draft_reply,
    load_thread,
    message_approval,
    reply_compliance,
    send,
)
from agent.state import ConversationState


def builder() -> StateGraph:
    g = StateGraph(ConversationState)
    g.add_node("liaison_load", load_thread, retry_policy=RETRY, timeout=60)
    g.add_node("liaison_classify", classify, retry_policy=RETRY, timeout=60)
    g.add_node("liaison_draft", draft_reply, retry_policy=RETRY, timeout=120)
    g.add_node("liaison_compliance", reply_compliance, timeout=60)
    g.add_node("liaison_approval", message_approval)
    g.add_node("liaison_send", send, retry_policy=RETRY, timeout=60)
    g.add_edge(START, "liaison_load")
    g.add_conditional_edges("liaison_load", lambda s: "go" if s.get("status") == "running" else "end",
                            {"go": "liaison_classify", "end": END})
    g.add_edge("liaison_classify", "liaison_draft")
    g.add_edge("liaison_draft", "liaison_compliance")
    g.add_conditional_edges("liaison_compliance", lambda s: "end" if s.get("status") == "blocked" else "ok",
                            {"ok": "liaison_approval", "end": END})
    g.add_conditional_edges("liaison_approval", lambda s: "send" if s.get("status") == "approved" else "end",
                            {"send": "liaison_send", "end": END})
    g.add_edge("liaison_send", END)
    return g


def build_conversation_graph(checkpointer=None, store=None):
    return builder().compile(checkpointer=checkpointer, store=store, name="conversation_graph")

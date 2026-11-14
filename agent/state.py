"""Typed graph state (C2).

Three things are kept apart:
- State (these TypedDicts): what this job / conversation needs right now.
- Execution trace (`trace` field + run_events + audit_log tables): every tool name, argument, result
  and observation, for audit and debugging. Appended through a reducer; never read by agents.
- Long-term memory (agent/memory): only promoted knowledge in the LangGraph store; raw tool output
  never goes there.

Reducers are declared wherever parallel branches (Analyst, Risk, Fit) or loops write.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


def merge_dicts(a: dict | None, b: dict | None) -> dict:
    return {**(a or {}), **(b or {})}


def keep_last(a, b):
    return b if b is not None else a


class BidState(TypedDict, total=False):
    # identity
    user_id: str
    owners: list[str]
    job_id: str
    trace_id: str
    force_bid: bool
    # the job (untrusted text sanitised by the risk branch before writers see it)
    job: dict[str, Any]
    duplicate_of: str | None
    # parallel analyses (each branch owns one field; `analyses` merges summaries)
    job_spec: dict[str, Any]
    risk_report: dict[str, Any]
    fit_report: dict[str, Any]
    analyses: Annotated[dict[str, Any], merge_dicts]
    sanitized_description: str
    # evidence + decisions
    evidence: list[dict[str, Any]]
    decision: dict[str, Any]
    price: dict[str, Any]
    # drafting loop
    draft: dict[str, Any]
    drafts: Annotated[list[dict[str, Any]], operator.add]
    critiques: Annotated[list[dict[str, Any]], operator.add]
    revision: int
    compliance: dict[str, Any]
    preview: dict[str, Any]
    # human + outcome
    approvals: Annotated[list[dict[str, Any]], operator.add]
    submission: dict[str, Any]
    outcome: dict[str, Any]
    memory_context: dict[str, Any]
    # control
    status: str  # running | skipped | watch | awaiting_approval | submitted | rejected | blocked | needs_attention | marketplace_unavailable
    status_reason: str
    steps: Annotated[int, operator.add]
    tokens: Annotated[int, operator.add]
    errors: Annotated[list[str], operator.add]
    trace: Annotated[list[dict[str, Any]], operator.add]


class ConversationState(TypedDict, total=False):
    user_id: str
    owners: list[str]
    thread_id: str  # marketplace thread
    job_id: str
    trace_id: str
    messages: list[dict[str, Any]]
    new_message: dict[str, Any]
    sanitized_message: str
    intent: dict[str, Any]
    slots: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    reply: dict[str, Any]
    compliance: dict[str, Any]
    preview: dict[str, Any]
    approvals: Annotated[list[dict[str, Any]], operator.add]
    sent: dict[str, Any]
    status: str
    status_reason: str
    steps: Annotated[int, operator.add]
    tokens: Annotated[int, operator.add]
    errors: Annotated[list[str], operator.add]
    trace: Annotated[list[dict[str, Any]], operator.add]

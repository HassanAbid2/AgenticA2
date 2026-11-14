"""Client Liaison nodes for the conversation graph: read the thread, classify intent, draft a reply
(with interview slots from the Workspace server), compliance-check, interrupt for approval, send."""

from __future__ import annotations

import re
import time
from datetime import date, timedelta

from langgraph.types import interrupt

from agent.guardrails import find_injections, neutralise, scam_signals
from agent.handoffs import ApprovalDecision, ClientIntent, ReplyDraft
from agent.llm import structured, untrusted
from agent.nodes.approval import idem
from agent.nodes.common import deps, node
from agent.nodes.compliance import guard

PRICE = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)")


def rule_intent(text: str) -> ClientIntent:
    if find_injections(text):
        return ClientIntent(intent="injection", confidence=0.9, explanation="instruction aimed at an AI assistant")
    if scam_signals(text):
        return ClientIntent(intent="scam_signal", confidence=0.9, explanation="off-platform / payment / personal-data request")
    low = text.lower()
    if re.search(r"\b(call|interview|meeting|video|schedule|zoom|chat live)\b", low):
        return ClientIntent(intent="interview_request", confidence=0.7, explanation="asks for a call")
    m = PRICE.search(text)
    if m or re.search(r"\b(budget|price|cheaper|discount|lower|rate)\b", low):
        return ClientIntent(intent="negotiation", confidence=0.7, explanation="price push-back",
                            asked_price=float(m.group(1).replace(",", "")) if m else None)
    if "?" in text:
        return ClientIntent(intent="question", confidence=0.6, explanation="asks a question")
    return ClientIntent(intent="other", confidence=0.4)


def template_reply(intent: str, slots: list[dict], floor: float, asked: float | None, evidence: list[dict]) -> ReplyDraft:
    if intent == "interview_request":
        opts = "; ".join(s["label"] for s in slots[:3]) or "any weekday afternoon"
        return ReplyDraft(text=f"Thanks, happy to talk. I'm free {opts}. Which works best for you? We can use the platform's call feature.",
                          proposed_slots=slots[:3])
    if intent == "negotiation":
        counter = max(floor, asked or 0)
        return ReplyDraft(text=f"Thanks for being upfront about budget. I can do ${counter:,.0f} if we trim the scope to the core "
                               "milestone first and add the rest as a follow-up. Would that work?", counter_price=counter)
    if intent == "scam_signal":
        return ReplyDraft(text="Thanks for the message. I keep all communication and payments on this platform, so let's continue "
                               "here. Happy to answer any questions about the project.", flags=["declined_off_platform"])
    ev = evidence[0]["title"] if evidence else None
    base = "Good question. " + (f"I handled something similar in {ev}. " if ev else "")
    return ReplyDraft(text=base + "I'd confirm the details on a short call and then share a milestone plan. Does that work for you?")


@node("liaison_load")
async def load_thread(state, config):
    th = (await deps(config).market("liaison").list_messages(state["thread_id"]))[0]
    client_msgs = [m for m in th["messages"] if m["sender"] == "client"]
    last = th["messages"][-1] if th["messages"] else None
    if not last or last["sender"] != "client":
        return {"messages": th["messages"], "status": "no_new_message", "_summary": {"new": False}}
    clean, spans = neutralise(last["text"])
    return {"messages": th["messages"], "job_id": th.get("job_id"), "new_message": last, "sanitized_message": clean,
            "status": "running", "_summary": {"new": True, "client_messages": len(client_msgs), "injection": bool(spans)}}


@node("liaison_classify")
async def classify(state, config):
    text = state["new_message"]["text"]
    base = rule_intent(text)
    llm = await structured("liaison_intent", "liaison_intent", ClientIntent, config, job_title=state.get("job_id", ""),
                           signals=base.model_dump(), message=untrusted("client_message", state["sanitized_message"]))
    intent = base if (llm is None or base.intent in ("injection", "scam_signal")) else llm  # rules win on safety intents
    return {"intent": intent.model_dump(), "_summary": {"intent": intent.intent, "by": "rules" if intent is base else "llm"}}


@node("liaison_draft")
async def draft_reply(state, config):
    d = deps(config)
    intent = state["intent"]["intent"]
    slots, ev = [], []
    if intent == "interview_request":
        start = (date.today() + timedelta(days=1)).isoformat()
        slots = (await d.hub.call("liaison", "free_slots", {"start_date": start, "days": 5, "duration_minutes": 30, "max_slots": 3}))["slots"]
    floor = float(d.setting("min_fixed", 0))
    our_price = d.setting("last_bid_amount")
    if our_price:
        floor = max(floor, 0.85 * float(our_price))
    llm = await structured("liaison", "liaison", ReplyDraft, config, freelancer_name=d.profile.get("name", ""),
                           floor_price=floor, job_title=state.get("job_id", ""), intent=intent, our_price=our_price,
                           slots=[s["label"] for s in slots], evidence=[e.get("title") for e in ev],
                           history="\n".join(f"{m['sender']}: {neutralise(m['text'])[0][:300]}" for m in state["messages"][-6:-1]),
                           required_disclosure="", message=untrusted("client_message", state["sanitized_message"]))
    reply = llm or template_reply(intent, slots, floor, state["intent"].get("asked_price"), ev)
    if intent == "interview_request" and slots and not reply.proposed_slots:
        reply.proposed_slots = slots[:3]
    if reply.counter_price is not None and reply.counter_price < floor:  # never below the floor, whatever the model says
        reply.counter_price = floor
    return {"slots": slots, "reply": reply.model_dump(), "_summary": {"intent": intent, "slots": len(slots), "words": len(reply.text.split())}}


@node("liaison_compliance")
async def reply_compliance(state, config):
    v = await guard(state["reply"]["text"], [], config)
    upd = {"compliance": v.model_dump(), "_summary": {"status": v.status}}
    if v.status == "block":
        upd |= {"status": "blocked", "status_reason": "; ".join(x.message for x in v.violations)}
    else:
        upd["reply"] = state["reply"] | {"text": v.cleaned_text}
    return upd


@node("liaison_approval")
async def message_approval(state, config):
    d = deps(config)
    key = idem(state["thread_id"], "msg", state["new_message"]["message_id"])
    preview = await d.market("liaison").preview_message(state["thread_id"], state["reply"]["text"], key)
    raw = interrupt({"kind": "message", "thread_id": state["thread_id"], "job_id": state.get("job_id"),
                     "client_message": state["new_message"], "sanitized_message": state["sanitized_message"],
                     "intent": state["intent"], "reply": state["reply"], "slots": state.get("slots", []),
                     "compliance": state.get("compliance"), "preview": preview})
    dec = ApprovalDecision.model_validate(raw)
    rec = dec.model_dump() | {"at": time.time()}
    if dec.action == "reject":
        return {"approvals": [rec], "status": "rejected", "status_reason": dec.reason or "rejected"}
    reply = state["reply"]
    if dec.action == "edit" and dec.edited_text:
        v = await guard(dec.edited_text, [], config)
        if v.status == "block":
            return {"approvals": [rec], "status": "blocked", "status_reason": "edited reply violates policy"}
        reply = reply | {"text": v.cleaned_text}
    return {"approvals": [rec], "reply": reply, "preview": preview, "status": "approved"}


@node("liaison_send")
async def send(state, config):
    d = deps(config)
    key = idem(state["thread_id"], "send", state["new_message"]["message_id"])
    res = await d.market("liaison").send_message(state["thread_id"], state["reply"]["text"], key)
    holds = []
    for i, s in enumerate(state["reply"].get("proposed_slots") or []):
        if isinstance(s, dict) and s.get("start"):
            holds.append(await d.hub.call("liaison", "create_interview_hold", {
                "start": s["start"], "duration_minutes": 30, "title": f"Interview (tentative) - {state.get('job_id')}",
                "idempotency_key": idem(state["thread_id"], "hold", s["start"], i)}))
    return {"sent": {"result": res.get("result"), "replayed": res.get("idempotent_replay"), "holds": len(holds)},
            "status": "sent", "_summary": {"sent": True, "holds": len(holds)}}

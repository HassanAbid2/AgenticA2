"""Proposal Writer: cover letter + screening answers with [n] citations into numbered evidence.

Evidence comes only from the Portfolio MCP server (fit matcher's matrix + search_evidence). The job
post the writer sees is the risk branch's sanitised copy, delimited as untrusted. Style memory rules
and outcome memory hints are injected; banned phrases are also enforced deterministically.
"""

from __future__ import annotations

import hashlib
import json
import re

from agent.config import settings
from agent.handoffs import ProposalDraft, WriterOutput
from agent.llm import structured, untrusted
from agent.memory.promotion_rules import apply_style
from agent.nodes.common import deps, node, thresholds

MAX_EVIDENCE = 8


def pick_strategy(job_id: str, override: str | None = None) -> str:
    if override:
        return override
    arms = settings()["proposal_strategies"]["arms"]
    h = int(hashlib.sha1(job_id.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return arms[0] if h < settings()["proposal_strategies"]["split"] else arms[1]


def select_evidence(state) -> list[dict]:
    """Diversify: best item per project first, then remaining items; cap at MAX_EVIDENCE."""
    ev = [e for e in state.get("evidence", []) if e.get("type") != "proposal"] + \
         [e for e in state.get("evidence", []) if e.get("type") == "proposal" and e.get("outcome") in ("won", "replied")]
    seen, first, rest = set(), [], []
    for e in ev:
        key = e.get("project") or e["evidence_id"]
        (rest if key in seen else first).append(e)
        seen.add(key)
    return (first + rest)[:MAX_EVIDENCE]


def evidence_block(ev: list[dict]) -> str:
    lines = []
    for i, e in enumerate(ev, 1):
        meta = ", ".join(x for x in (e.get("type"), e.get("project"), e.get("client_industry"), e.get("date"),
                                     f"outcome: {e['outcome']}" if e.get("outcome") else None) if x)
        lines.append(f"[{i}] ({meta}) {re.sub(r'\s+', ' ', e.get('snippet') or '')[:700]}")
    return "\n".join(lines)


def _result_sentence(text: str) -> str | None:
    for s in re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text or "")):
        if re.search(r"\d", s) and 25 < len(s) < 220 and not s.lstrip().startswith(("#", "-", "[")):
            return s.strip().rstrip(".")
    return None


def template_draft(job: dict, spec: dict, ev: list[dict], price: dict, profile: dict) -> WriterOutput:
    """Offline writer (no LLM): stitches verbatim evidence sentences, so every claim is grounded by construction."""
    need = (spec.get("requirements") or [job.get("title", "")])[-1]
    parts = [f"Your post describes {need[0].lower() + need[1:] if need else 'a project'} - that is close to work I have already delivered."]
    used = 0
    for i, e in enumerate(ev, 1):
        s = _result_sentence(e.get("snippet", ""))
        if s and e.get("project"):
            parts.append(f"On {e['project']}, the result: {s[0].lower() + s[1:]} [{i}].")
            used += 1
        if used == 2:
            break
    skills = spec.get("required_skills", [])[:3]
    parts.append(f"I would start with a short call to confirm scope, then deliver a first milestone covering "
                 f"{', '.join(skills) if skills else 'the core requirement'} within the first week.")
    parts.append(f"My quote is ${price.get('amount'):,.0f}{'/h' if price.get('unit') == 'hourly' else ''}.")
    parts.append("What would make this project a clear success for you in the first month?")
    answers = []
    for q in spec.get("screening_questions", []):
        s = next((f"{_result_sentence(e.get('snippet', ''))} [{i}]." for i, e in enumerate(ev, 1) if _result_sentence(e.get("snippet", ""))), "")
        answers.append(f"{s} For your project I would follow the same approach and agree milestones up front.".strip())
    return WriterOutput(cover_letter=" ".join(parts), screening_answers=answers)


@node("writer")
async def writer(state, config):
    d = deps(config)
    job, spec, price = state["job"], state.get("job_spec", {}), state.get("price", {})
    ev = select_evidence(state)
    cv = await d.hub.call("writer", "search_evidence", {"requirement": "professional summary years of experience",
                                                         "k": 1, "filters": {"type": ["cv"]}})
    for it in cv.get("items", []):
        if it["evidence_id"] not in {e["evidence_id"] for e in ev}:
            ev.append({"evidence_id": it["evidence_id"], "type": "cv", "title": it["title"], "project": None,
                       "snippet": it["snippet"], "date": it.get("date"), "skills": it.get("skills", [])})
    revision = state.get("revision", 0)
    strategy = pick_strategy(job["job_id"], d.strategy)
    mem = state.get("memory_context") or {}
    style = mem.get("style_rules") or []
    outcome = mem.get("outcome") or {}
    t = thresholds()
    max_words = t["max_words"]
    if any(r.get("kind") == "shorter" for r in style):
        max_words = int(max_words * 0.8)
    notes = ""
    if revision and state.get("critiques"):
        c = state["critiques"][-1]
        notes = "REVISION REQUEST from the reviewer (fix these):\n" + c.get("instructions", "") + "\n" + "\n".join(c.get("issues", []))
    if state.get("draft", {}).get("removed_claims"):
        notes += "\nThese claims were removed as unsupported; do not make them again: " + json.dumps(state["draft"]["removed_claims"])
    from agent.config import policy_pack

    disclosure = policy_pack().get("required_disclosure")
    out = await structured("writer", f"writer_{strategy}", WriterOutput, config,
                           freelancer_name=d.profile.get("name", "the freelancer"), headline=d.profile.get("headline", ""),
                           min_words=t["min_words"], max_words=max_words,
                           style_rules=("Style rules learned from this user's edits:\n" + "\n".join(f"- {r['rule']}" for r in style)) if style else "",
                           outcome_hint=(f"What has worked in '{outcome.get('category')}' jobs: reply rate {outcome.get('reply_rate')}, "
                                         f"best strategy {outcome.get('best_strategy')}, projects in replied proposals: "
                                         f"{outcome.get('winning_projects')}") if outcome else "",
                           required_disclosure=f"End the cover letter with this exact sentence: \"{disclosure}\"" if disclosure else "",
                           job_spec={k: spec.get(k) for k in ("title", "requirements", "required_skills", "hidden_needs",
                                                               "deliverables", "screening_questions", "client_industry")},
                           price=f"{price.get('amount')} ({price.get('unit')})",
                           job_post=untrusted("job_post", f"{job.get('title', '')}\n{state.get('sanitized_description') or ''}"),
                           evidence=evidence_block(ev), revision_notes=notes)
    source = "llm"
    if out is None:
        out = template_draft(job, spec, ev, price, d.profile)
        source = "template"
    n_q = len(spec.get("screening_questions", []))
    answers = (out.screening_answers + [""] * n_q)[:n_q] if n_q else out.screening_answers[:0]
    draft = ProposalDraft(job_id=job["job_id"], cover_letter=apply_style(out.cover_letter, style),
                          screening_answers=[apply_style(a, style) for a in answers], evidence=ev, revision=revision,
                          strategy=strategy)
    return {"draft": draft.model_dump(), "drafts": [{"revision": revision, "cover_letter": draft.cover_letter, "source": source}],
            "_summary": {"revision": revision, "strategy": strategy, "words": len(draft.cover_letter.split()), "source": source}}

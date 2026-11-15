"""Critic: grounding, personalisation and length checks; sends a draft back at most twice (config)."""

from __future__ import annotations

import json
import re

from agent.handoffs import Critique
from agent.llm import structured
from agent.nodes.common import node, thresholds
from agent.nodes.writer import evidence_block
from rag.verify import normalise, strip_citations

GENERIC_OPEN = re.compile(r"^(dear|hello|hi|greetings|i am|i'm|my name|as an? )", re.I)
CLICHE = re.compile(r"\b(passionate|hardworking|perfect fit|many years of experience|do this job perfectly|look no further)\b", re.I)


def auto_checks(draft: dict, job: dict, spec: dict) -> dict:
    letter = draft["cover_letter"]
    words = len(letter.split())
    t = thresholds()
    terms = {w for w in re.findall(r"[a-z]{5,}", (job.get("title", "") + " " + " ".join(spec.get("requirements", []))).lower())}
    first = re.split(r"(?<=[.!?])\s", letter.strip(), maxsplit=1)[0].lower()
    claims = draft.get("claims", [])
    return {
        "words": words, "length_ok": t["min_words"] * 0.8 <= words <= t["max_words"] * 1.15,
        "generic_opening": bool(GENERIC_OPEN.search(letter.strip())), "cliches": CLICHE.findall(letter),
        "personalised": any(w in letter.lower() for w in terms), "opening_mentions_job": any(w in first for w in terms),
        "has_question": "?" in letter, "citations": len(re.findall(r"\[\d+\]", letter)),
        "screening_answered": len([a for a in draft.get("screening_answers", []) if a.strip()]) >= len(spec.get("screening_questions", [])),
        "unsupported_removed": len(draft.get("removed_claims", [])),
        "supported_claims": sum(c["label"] == "supported" for c in claims),
        "letter_claims": sum(c["label"] != "unsupported" and c["claim"][:40] in normalise(strip_citations(letter)) for c in claims),
    }


def rule_critique(a: dict) -> Critique:
    issues = []
    if not a["length_ok"]:
        issues.append(f"length {a['words']} words is outside the target range")
    if a["generic_opening"] or not a["opening_mentions_job"]:
        issues.append("opening is generic; start with the client's problem")
    if a["cliches"]:
        issues.append("remove clichés: " + ", ".join(set(a["cliches"])))
    if not a["has_question"]:
        issues.append("end with one specific question for the client")
    if not a["screening_answered"]:
        issues.append("answer every screening question")
    if a["citations"] == 0 or a["letter_claims"] == 0:
        issues.append("no grounded evidence left; cite at least one concrete result")
    if a["unsupported_removed"] > 1:
        issues.append(f"{a['unsupported_removed']} unsupported claims were removed; only state what the evidence shows")
    score = max(0.0, 10 - 1.8 * len(issues))
    return Critique(approve=score >= 7 and a["citations"] > 0, score=round(score, 1), issues=issues,
                    instructions="\n".join(f"- {i}" for i in issues[:3]), grounded=a["supported_claims"] > 0,
                    personalised=a["personalised"], length_ok=a["length_ok"])


@node("critic")
async def critic(state, config):
    draft, job, spec = state["draft"], state["job"], state.get("job_spec", {})
    a = auto_checks(draft, job, spec)
    base = rule_critique(a)
    llm = await structured("critic", "critic", Critique, config, min_words=thresholds()["min_words"],
                           approve_score=thresholds()["critic_approve_score"],
                           max_words=thresholds()["max_words"],
                           job_spec=json.dumps({k: spec.get(k) for k in ("title", "requirements", "hidden_needs")}),
                           draft=draft["cover_letter"], answers=draft.get("screening_answers", []),
                           evidence=evidence_block(draft.get("evidence", [])), auto_checks=a)
    c = base
    if llm:
        # rules can veto, never rubber-stamp: hard failures stay failures whatever the model says
        hard = [i for i in base.issues if i.startswith(("no grounded", "answer every", "length"))]
        c = llm.model_copy(update={"approve": (llm.approve or llm.score >= thresholds()["critic_approve_score"]) and not hard, "issues": list(dict.fromkeys(hard + llm.issues)),
                                   "instructions": "\n".join(filter(None, ["\n".join(f"- {h}" for h in hard), llm.instructions]))})
    return {"critiques": [c.model_dump() | {"revision": state.get("revision", 0), "auto": a}],
            "_summary": {"approve": c.approve, "score": c.score, "issues": c.issues[:3]}}


@node("revise")
async def revise(state, config):
    """Bookkeeping for the loop: bump the revision counter before the writer runs again."""
    return {"revision": state.get("revision", 0) + 1, "_summary": {"revision": state.get("revision", 0) + 1}}

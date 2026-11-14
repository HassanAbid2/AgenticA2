"""Claim verification node (B3): split the draft into claims, ground each in the numbered evidence,
remove unsupported claims before the Critic sees the draft, and record before/after rates."""

from __future__ import annotations

from agent.handoffs import ClaimCheck
from agent.llm import get_chat, render
from agent.nodes.common import node
from rag.verify import strip_unsupported, unsupported_rate, verify_claims


def _judge():
    llm = get_chat("claim_judge")
    if llm is None:
        return None

    def judge(claim: str, texts: list[str]) -> str:
        sys_p, user_p = render("claim_judge", claim=claim, evidence="\n---\n".join(t[:800] for t in texts))
        out = llm.invoke([("system", sys_p), ("user", user_p)], config={"metadata": {"gigbid_node": "claim_judge"}}).content.lower()
        return "unsupported" if "unsupported" in out else "supported" if "supported" in out else "partly_supported"

    return judge


def verify_draft(draft: dict, judge=None) -> dict:
    ev = draft["evidence"]
    letter_res = verify_claims(draft["cover_letter"], ev, judge)
    ans_res = [verify_claims(a, ev, judge) for a in draft.get("screening_answers", [])]
    all_res = letter_res + [r for rs in ans_res for r in rs]
    before = unsupported_rate(all_res)
    cleaned = strip_unsupported(draft["cover_letter"], letter_res)
    cleaned_answers = [strip_unsupported(a, rs) for a, rs in zip(draft.get("screening_answers", []), ans_res, strict=True)]
    removed = [r.claim for r in all_res if r.label == "unsupported"]
    kept = [r for r in all_res if r.label != "unsupported"]
    return draft | {"cover_letter": cleaned, "screening_answers": cleaned_answers,
                    "claims": [ClaimCheck(**{k: getattr(r, k) for k in ("claim", "label", "score", "evidence_ids", "reasons")}).model_dump()
                               for r in all_res],
                    "removed_claims": removed, "unsupported_rate_before": before,
                    "unsupported_rate_after": unsupported_rate(kept) if kept else 0.0,
                    "n_claims": len(all_res)}


@node("verifier")
async def verifier(state, config):
    d = verify_draft(state["draft"], _judge())
    return {"draft": d, "_summary": {"claims": d["n_claims"], "unsupported_before": d["unsupported_rate_before"],
                                     "removed": len(d["removed_claims"])}}

"""Compliance Guard: enforce the policy pack (data/policy_pack/marketplace_policy.yaml) on everything
that would leave GigBid. Redacts contact details, removes guarantees and echoes of planted
instructions, removes unsupported claims, appends required disclosures, and blocks (with a reason
shown in the UI) when a draft offers off-platform payment or unpaid work."""

from __future__ import annotations

import re

from pydantic import BaseModel

from agent.config import policy_pack
from agent.handoffs import ComplianceVerdict, Violation
from agent.llm import structured
from agent.nodes.common import node
from rag.verify import sentences


class _LLMViolations(BaseModel):
    violations: list[dict] = []


def check_text(text: str, pack: dict | None = None, unsupported: list[str] | None = None) -> tuple[str, list[Violation], bool]:
    pack = pack or policy_pack()
    viol: list[Violation] = []
    blocked = False
    out = text or ""
    for r in pack["rules"]:
        if r["kind"] != "forbid_regex":
            continue
        rx = re.compile(r["pattern"], re.I)
        for m in list(rx.finditer(out)):
            viol.append(Violation(rule_id=r["id"], message=r["message"], action=r["action"], excerpt=m.group(0)[:80]))
        if not rx.search(out):
            continue
        if r["action"] in ("redact", "rewrite"):  # drop the offending sentence; a half-sentence reads worse
            out = " ".join(s for s in sentences(out) if not rx.search(s))
        elif r["action"] == "block":
            blocked = True
    for claim in unsupported or []:
        if claim and claim in out:
            out = out.replace(claim, "")
            viol.append(Violation(rule_id="P3-fabrication", message="Removed an unsupported claim.", action="rewrite", excerpt=claim[:80]))
    return re.sub(r"\s{2,}", " ", out).strip(), viol, blocked


def apply_disclosure(text: str, pack: dict | None = None) -> tuple[str, list[Violation]]:
    pack = pack or policy_pack()
    d = pack.get("required_disclosure")
    if d and d.lower() not in (text or "").lower():
        return (text.rstrip() + " " + d).strip(), [Violation(rule_id=pack.get("disclosure_rule_id", "P8"), action="append",
                                                             message="Added the required AI-assistance disclosure.", excerpt=d)]
    return text, []


async def guard(text: str, answers: list[str], config=None, unsupported=None) -> ComplianceVerdict:
    pack = policy_pack()
    clean, viol, blocked = check_text(text, pack, unsupported)
    clean_answers = []
    for a in answers:
        ca, va, ba = check_text(a, pack, unsupported)
        clean_answers.append(ca)
        viol += va
        blocked = blocked or ba
    rules_txt = "\n".join(f"- {r['id']}: {r['rule']}" for r in pack["rules"])
    llm = await structured("compliance", "compliance", _LLMViolations, config, rules=rules_txt, text=clean + "\n" + "\n".join(clean_answers))
    for v in (llm.violations if llm else []):
        ex = str(v.get("excerpt", ""))[:200]
        if ex and ex in clean:
            clean = " ".join(s for s in sentences(clean) if ex not in s)
            viol.append(Violation(rule_id=str(v.get("rule_id", "LLM")), message=str(v.get("message", ""))[:200], action="rewrite", excerpt=ex[:80]))
    clean, dv = apply_disclosure(clean, pack)
    viol += dv
    status = "block" if blocked else ("fixed" if viol else "pass")
    return ComplianceVerdict(status=status, violations=viol, cleaned_text=clean, cleaned_answers=clean_answers)


@node("compliance")
async def compliance(state, config):
    d = state["draft"]
    v = await guard(d["cover_letter"], d.get("screening_answers", []), config, d.get("removed_claims"))
    upd = {"compliance": v.model_dump(), "_summary": {"status": v.status, "violations": [x.rule_id for x in v.violations]}}
    if v.status == "block":
        upd |= {"status": "blocked", "status_reason": "; ".join(f"{x.rule_id}: {x.message}" for x in v.violations if x.action == "block")}
    else:
        upd["draft"] = d | {"cover_letter": v.cleaned_text, "screening_answers": v.cleaned_answers}
    return upd

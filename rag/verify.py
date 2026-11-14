"""Claim verification (B3): split a draft into atomic claims and ground each one in evidence.

A claim is a sentence asserting past experience, a result or a capability fact ("I built...",
"cut response time by 38%", "6 years of experience"). Plans ("I would start..."), questions and
pleasantries are not claims. Each claim is labelled:

  supported         every number and tool it names appears in evidence, and it is semantically close
  partly_supported  entities check out but wording is loose, or it is close but one entity is missing
  unsupported       a number/tool/project the evidence never mentions, or no evidence is close

Unsupported claims are removed before the Critic sees the draft (`strip_unsupported`).
An optional LLM judge (judge_fn) may upgrade/downgrade the grey-zone `partly_supported` cases.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

import numpy as np

from rag.index.store import embed
from rag.skills import extract_skills

CITE = re.compile(r"\s*\[(\d+)\]")
NUM = re.compile(r"(?<![\w.])\$?\d[\d,]*(?:\.\d+)?\s?(?:%|k\b|x\b)?")
FUTURE = re.compile(r"\b(I would|I will|I'll|I'd|I can|I could|I plan|I propose|I'm happy to|I am happy to|let's|we can|we could|my plan|happy to)\b", re.I)
EXPERIENCE = re.compile(
    r"\b(built|build|shipped|delivered|led|designed|developed|created|implemented|worked|"
    r"used|cut|reduced|increased|improved|migrated|automated|trained|deployed|launched|wrote|have \d+|years|experience|"
    r"helped|ran|optimi[sz]ed|scaled|integrated|handled|saved|achieved|reached)\b", re.I)
RESULT = re.compile(r"\d")  # any number is a factual assertion worth checking
SUPPORTED_SIM, PARTLY_SIM = 0.80, 0.70


@dataclass
class ClaimResult:
    claim: str
    label: str
    score: float
    evidence_ids: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    sentence_index: int = 0

    def to_dict(self):
        return asdict(self)


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\"'(\[])|\n+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def is_claim(sent: str) -> bool:
    s = CITE.sub("", sent)
    if s.endswith("?") or FUTURE.search(s) or re.match(r"^(you|your)\b", s, re.I):
        return False  # questions, plans and restating the client's own post are not claims
    return bool(EXPERIENCE.search(s) or RESULT.search(s))


def _norm_num(n: str) -> str:
    return n.replace(",", "").replace("$", "").replace(" ", "").lower().rstrip("x")


def _numbers(text: str) -> set[str]:
    return {_norm_num(m) for m in NUM.findall(text) if re.search(r"\d", m)}


def verify_claims(draft: str, evidence: list[dict], judge_fn=None) -> list[ClaimResult]:
    sents = sentences(draft)
    claims = [(i, s) for i, s in enumerate(sents) if is_claim(s)]
    if not claims:
        return []
    texts = [e.get("text", "") for e in evidence]
    ev_nums = [_numbers(t) for t in texts]
    ev_skills = [set(e.get("skills") or []) | set(extract_skills(t, code=True)) for e, t in zip(evidence, texts, strict=True)]
    ev_vecs = embed(texts) if texts else np.zeros((0, 384))
    cl_vecs = embed([CITE.sub("", s) for _, s in claims])
    out = []
    for (i, s), v in zip(claims, cl_vecs, strict=True):
        cited = [int(c) - 1 for c in CITE.findall(s) if 0 < int(c) <= len(evidence)]
        pool = cited or list(range(len(evidence)))
        clean = CITE.sub("", s)
        sims = (ev_vecs[pool] @ v) if pool else np.array([0.0])
        best = float(sims.max()) if len(pool) else 0.0
        reasons = []
        nums = _numbers(clean)
        all_nums = set().union(*(ev_nums[j] for j in pool)) if pool else set()
        missing_nums = sorted(n for n in nums if n not in all_nums)
        skills = set(extract_skills(clean))
        all_skills = set().union(*(ev_skills[j] for j in pool)) if pool else set()
        missing_sk = sorted(skills - all_skills)
        if missing_nums:
            reasons.append(f"numbers not in evidence: {missing_nums}")
        if missing_sk:
            reasons.append(f"tools/skills not in evidence: {missing_sk}")
        top = [pool[j] for j in np.argsort(-sims)[:2]] if pool else []
        if not missing_nums and not missing_sk and best >= SUPPORTED_SIM:
            label = "supported"
        elif not missing_nums and (not missing_sk or len(missing_sk) < len(skills)) and best >= PARTLY_SIM:
            label = "partly_supported"
            if missing_sk:
                reasons.append("some named tools unsupported")
            else:
                reasons.append(f"loose wording (similarity {best:.2f})")
        else:
            label = "unsupported"
            if best < PARTLY_SIM:
                reasons.append(f"no close evidence (similarity {best:.2f})")
        if judge_fn and label == "partly_supported":
            try:
                verdict = judge_fn(clean, [texts[j] for j in top])
                if verdict in ("supported", "unsupported"):
                    reasons.append(f"llm judge: {verdict}")
                    label = verdict
            except Exception:  # noqa: BLE001 - judge is optional
                pass
        out.append(ClaimResult(clean, label, round(best, 3), [evidence[j]["evidence_id"] for j in top], reasons, i))
    return out


def strip_unsupported(draft: str, results: list[ClaimResult]) -> str:
    bad = {r.sentence_index for r in results if r.label == "unsupported"}
    sents = sentences(draft)
    return " ".join(s for i, s in enumerate(sents) if i not in bad)


def unsupported_rate(results: list[ClaimResult]) -> float:
    return round(sum(r.label == "unsupported" for r in results) / len(results), 4) if results else 0.0


def strip_citations(text: str) -> str:
    """Citation markers are for the human reviewer; the client never sees them."""
    return re.sub(r"[ \t]+([.,;:!?])", r"\1", CITE.sub("", text)).strip()

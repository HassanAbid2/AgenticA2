"""Explicit promotion rules (R7): how raw signals become long-term memory.

Style memory. Each user edit to a draft is diffed and abstracted into *patterns* (deterministic, no
LLM): a phrase the user deleted, the first sentence cut, the letter shortened, a phrase they added.
A pattern is promoted to a style rule only when
  - it appears in at least STYLE_MIN_SUPPORT distinct edits (different jobs) among the last
    STYLE_WINDOW edits, and
  - it was never contradicted (a deleted phrase the user later wrote back in is not banned), and
  - it is one of the allowed kinds below.
Rules store the abstraction ("never say 'passionate'"), never the user's raw text.

Outcome memory. Outcomes (replied / interview / hired vs ignored / lost) are aggregated per job
category; a category's stats are promoted once it has OUTCOME_MIN_N outcomes. Only aggregates
(rates, best strategy arm, projects cited in replied proposals at least twice) are stored.
"""

from __future__ import annotations

import difflib
import re
from collections import Counter, defaultdict

STYLE_MIN_SUPPORT = 3
STYLE_WINDOW = 20
OUTCOME_MIN_N = 5
MAX_STYLE_RULES = 15
ALLOWED = {"ban_phrase", "cut_first_sentence", "shorter", "prefer_phrase"}
STOP = set("the a an and or of to for in on our we with that this is it be by from as at you your i my me "
           "have has can will would am are was were".split())
POSITIVE = {"replied", "interview", "hired"}


def should_promote_style_edit(edit_count: int, consistent_pattern: bool) -> bool:
    """Starter-kit signature kept: promote only repeated, consistent edits."""
    return edit_count >= STYLE_MIN_SUPPORT and consistent_pattern


def _sentences(t: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", (t or "").strip()) if s.strip()]


def _ngrams(text: str, n: int) -> set[str]:
    w = re.findall(r"[a-z']+", text.lower())
    return {" ".join(w[i:i + n]) for i in range(len(w) - n + 1)}


def diff_text(before: str, after: str) -> str:
    return "\n".join(difflib.unified_diff(_sentences(before), _sentences(after), "draft", "edited", lineterm=""))


def extract_patterns(before: str, after: str) -> list[dict]:
    pats: list[dict] = []
    bs, as_ = _sentences(before), _sentences(after)
    if bs and as_ and bs[0] not in after and as_[0] in " ".join(bs[1:]):
        pats.append({"kind": "cut_first_sentence", "key": "cut_first_sentence"})
    wb, wa = len(before.split()), len(after.split())
    if wb and wa < 0.8 * wb:
        pats.append({"kind": "shorter", "key": "shorter", "ratio": round(wa / wb, 2)})
    for n in (1, 2):
        for g in _ngrams(before, n) - _ngrams(after, n):
            if all(t not in STOP for t in g.split()) and len(g) > 4:
                pats.append({"kind": "ban_phrase", "key": f"ban:{g}", "phrase": g})
        for g in _ngrams(after, n) - _ngrams(before, n):
            if all(t not in STOP for t in g.split()) and len(g) > 4:
                pats.append({"kind": "prefer_phrase", "key": f"prefer:{g}", "phrase": g})
    return pats


def promote_style(edits: list[dict]) -> list[dict]:
    """edits: chronological [{id, job_id, after, patterns}] -> style rules to store."""
    window = edits[-STYLE_WINDOW:]
    support: dict[str, set] = defaultdict(set)
    proto: dict[str, dict] = {}
    for e in window:
        for p in e["patterns"]:
            if p["kind"] in ALLOWED:
                support[p["key"]].add(e["job_id"])
                proto.setdefault(p["key"], p)
    rules = []
    for key, jobs in support.items():
        if len(jobs) < STYLE_MIN_SUPPORT:
            continue
        p = proto[key]
        if p["kind"] == "ban_phrase":
            # contradicted if the user wrote the phrase themselves in a later edit
            if any(p["phrase"] in (e.get("after") or "").lower() for e in window):
                continue
            text = f"Never use the phrase '{p['phrase']}'."
        elif p["kind"] == "prefer_phrase":
            text = f"The user likes to include: '{p['phrase']}'."
        elif p["kind"] == "cut_first_sentence":
            text = "Open with the client's problem; the user keeps deleting a generic first sentence."
        else:
            text = "Keep it shorter: the user trims drafts by 20% or more."
        rules.append({"id": key, "kind": p["kind"], "rule": text, "phrase": p.get("phrase"), "support": len(jobs),
                      "edit_ids": [e["id"] for e in window if any(x["key"] == key for x in e["patterns"])]})
    rules.sort(key=lambda r: -r["support"])
    return rules[:MAX_STYLE_RULES]


def promote_outcomes(rows: list[dict]) -> dict[str, dict]:
    """rows: [{category, status, strategy, projects}] for proposals with a final-ish status."""
    by_cat: dict[str, list] = defaultdict(list)
    for r in rows:
        by_cat[r["category"] or "uncategorised"].append(r)
    out = {}
    for cat, rs in by_cat.items():
        if len(rs) < OUTCOME_MIN_N:
            continue
        pos = [r for r in rs if r["status"] in POSITIVE]
        strat = Counter(r["strategy"] for r in pos)
        tried = Counter(r["strategy"] for r in rs)
        rates = {s: round(strat[s] / tried[s], 3) for s in tried}
        proj = Counter(p for r in pos for p in (r.get("projects") or []))
        out[cat] = {"category": cat, "n": len(rs), "reply_rate": round(len(pos) / len(rs), 3),
                    "hired": sum(r["status"] == "hired" for r in rs), "rate_by_strategy": rates,
                    "best_strategy": max(rates, key=rates.get) if rates else None,
                    "winning_projects": [p for p, c in proj.most_common(5) if c >= 2]}
    return out


def apply_style(text: str, rules: list[dict]) -> str:
    """Deterministic enforcement of banned phrases after drafting (the prompt also lists the rules)."""
    for r in rules:
        if r.get("kind") == "ban_phrase" and r.get("phrase"):
            text = re.sub(rf"\b{re.escape(r['phrase'])}\b\s*", "", text, flags=re.I)
    return re.sub(r"\s{2,}", " ", text).strip()

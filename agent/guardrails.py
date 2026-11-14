"""Untrusted-input defences (E4 / R9): detection and neutralisation of instructions planted in job
posts and client messages. Layered with (1) delimiting in every prompt (llm.untrusted), (2) system
prompts that say content in those blocks is data, (3) the Compliance Guard's output canary rules.

Patterns live in agent/prompts/injection_patterns.yaml so they can be extended without code changes.
"""

from __future__ import annotations

import re
from functools import lru_cache

import yaml

from agent.config import ROOT


@lru_cache
def _patterns():
    d = yaml.safe_load((ROOT / "agent" / "prompts" / "injection_patterns.yaml").read_text(encoding="utf-8"))
    comp = lambda xs: [re.compile(x, re.I | re.S) for x in xs]  # noqa: E731
    return comp(d["injection"]), {k: comp(v) for k, v in d["scam"].items()}


def find_injections(text: str) -> list[str]:
    inj, _ = _patterns()
    spans = []
    for rx in inj:
        for m in rx.finditer(text or ""):
            spans.append(m.group(0).strip()[:300])
    return list(dict.fromkeys(spans))


def neutralise(text: str) -> tuple[str, list[str]]:
    """Remove instruction-like spans; the writer only ever sees the cleaned post."""
    spans = find_injections(text)
    clean = text or ""
    for s in spans:
        clean = clean.replace(s, "[removed: instruction-like text addressed to AI tools]")
    return clean, spans


def scam_signals(text: str) -> dict[str, list[str]]:
    _, scams = _patterns()
    out = {}
    for flag, rxs in scams.items():
        hits = [m.group(0)[:120] for rx in rxs for m in [rx.search(text or "")] if m]
        if hits:
            out[flag] = hits
    return out

"""Skill lexicon: explicit names, aliases and code-import patterns.

Only names a real lexicon would contain (tool names, aliases, import statements). The generator's
"implied" descriptions are deliberately NOT here: recovering those is retrieval's job.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

LEXICON_PATH = Path(__file__).parent / "skills_lexicon.json"
GENERIC = {"Python", "Docker", "pandas", "SQL", "TypeScript", "JavaScript", "Excel", "dashboards"}


@lru_cache
def lexicon() -> dict[str, dict]:
    return json.loads(LEXICON_PATH.read_text(encoding="utf-8"))


@lru_cache
def _patterns():
    out = []
    for skill, d in lexicon().items():
        names = [skill, *d.get("aliases", [])]
        alt = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
        flags = 0 if len(skill) <= 2 else re.I  # "R" must not match every stray "r"
        out.append((skill, re.compile(rf"(?<![\w.]){alt}(?![\w])", flags),
                    [re.compile(p) for p in d.get("code_patterns", [])]))
    return out


def extract_skills(text: str, code: bool = False) -> list[str]:
    found = []
    for skill, rx, code_rx in _patterns():
        if rx.search(text) or (code and any(c.search(text) for c in code_rx)):
            found.append(skill)
    return found


def canonical(skill: str) -> str:
    s = skill.strip().lower()
    for name, d in lexicon().items():
        if s == name.lower() or s in (a.lower() for a in d.get("aliases", [])):
            return name
    return skill.strip()

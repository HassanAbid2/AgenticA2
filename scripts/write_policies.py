"""Writes gigsim/policies.json (kept as a script so the regexes stay readable)."""

import json
from pathlib import Path

EMAIL = r"[\w.+-]+@[\w-]+\.[\w.]+"
PHONE = r"(?<![\w-])\+?(?:\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{3,4}(?![\w-])"
APPS = r"\b(whatsapp|telegram|skype|signal app|wechat)\b"
GUAR = r"\bguarantee(d|s)?\b"
BASE = [
    {"id": "P1", "kind": "forbid_regex", "pattern": EMAIL, "message": "no email addresses (off-platform contact)"},
    {"id": "P1", "kind": "forbid_regex", "pattern": PHONE, "message": "no phone numbers (off-platform contact)"},
    {"id": "P1", "kind": "forbid_regex", "pattern": APPS, "message": "no off-platform messaging apps"},
    {"id": "P4", "kind": "forbid_regex", "pattern": GUAR, "message": "no guarantees of results"},
]
POLICIES = {
    "2026-10": {"effective": "2026-10-01", "summary": "Baseline marketplace rules.",
                "submission_fee_connects": 0, "featured_multiplier": 1.0, "submission_rules": BASE},
    "2026-11-02": {
        "effective": "2026-11-02",
        "summary": "Platform policy update: (1) every proposal submission costs 2 extra Connects and Featured "
                   "jobs cost 1.5x; (2) proposals drafted with AI assistance must disclose it in the cover letter.",
        "submission_fee_connects": 2, "featured_multiplier": 1.5,
        "submission_rules": BASE + [{"id": "P8", "kind": "require_regex",
                                     "pattern": r"(drafted|written|prepared) with (the help of )?AI",
                                     "message": "AI-assisted proposals must disclose AI assistance"}],
    },
}

if __name__ == "__main__":
    Path("gigsim/policies.json").write_text(json.dumps(POLICIES, indent=2) + "\n", encoding="utf-8", newline="\n")

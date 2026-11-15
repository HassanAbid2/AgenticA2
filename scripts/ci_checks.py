"""Repository rules CI enforces (see .github/workflows/ci.yml):

1. nothing under gigsim/ changed   (tree hash must equal .github/gigsim.lock)
2. every prompt lives in agent/prompts/ (no long LLM instruction strings inline in Python)
3. no secrets committed            (high-entropy key patterns in tracked files)
4. every number in README.md tables traces to a file in evals/results/

    python -m scripts.ci_checks [--update-lock]
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / ".github" / "gigsim.lock"
SECRET = re.compile(r"(gsk_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|"
                    r"AKIA[0-9A-Z]{16}|-----BEGIN (RSA |EC )?PRIVATE KEY-----|xox[bp]-[A-Za-z0-9-]{20,})")
PROMPTISH = re.compile(r"(You are (a|an|the) [A-Za-z ]{3,40}(assistant|reviewer|writer|analyst|checker)|Reply with JSON only)")


def git(*args) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def check_gigsim(update: bool) -> list[str]:
    h = git("rev-parse", "HEAD:gigsim")
    dirty = git("status", "--porcelain", "--", "gigsim")
    if update:
        LOCK.write_text(h + "\n", encoding="utf-8")
        return []
    if not LOCK.exists():
        return ["missing .github/gigsim.lock (run with --update-lock once)"]
    errs = []
    if LOCK.read_text().strip() != h:
        errs.append(f"gigsim/ changed: tree {h} != locked {LOCK.read_text().strip()}")
    if dirty:
        errs.append("uncommitted changes under gigsim/")
    return errs


def check_prompts() -> list[str]:
    errs = []
    for f in git("ls-files", "*.py").splitlines():
        if f.startswith(("tests/", "scripts/")):
            continue
        txt = (ROOT / f).read_text(encoding="utf-8", errors="ignore")
        for m in PROMPTISH.finditer(txt):
            errs.append(f"{f}: inline prompt text '{m.group(0)[:50]}' (move it to agent/prompts/)")
    return errs


def check_secrets() -> list[str]:
    errs = []
    for f in git("ls-files").splitlines():
        p = ROOT / f
        if p.suffix in {".png", ".pdf", ".gif", ".jpg", ".npz"} or not p.is_file() or p.stat().st_size > 2_000_000:
            continue
        for m in SECRET.finditer(p.read_text(encoding="utf-8", errors="ignore")):
            errs.append(f"{f}: possible secret {m.group(0)[:8]}…")
    return errs


def check_numbers() -> list[str]:
    """Every decimal number inside a README table row must appear in some evals/results/*.json value."""
    readme = ROOT / "README.md"
    if not readme.exists():
        return []
    blob = " ".join(p.read_text(encoding="utf-8") for p in (ROOT / "evals" / "results").glob("*.json"))
    known = {round(float(x), 3) for x in re.findall(r"-?\d+(?:\.\d+)?(?:e-?\d+)?", blob)}
    errs = []
    for line in readme.read_text(encoding="utf-8").splitlines():
        if line.startswith("|") and "<!-- untraced -->" not in line:
            for n in re.findall(r"(?<![\w.])\d+\.\d+(?![\w.])", line):
                v = float(n)
                if round(v, 3) not in known and round(v / 100, 3) not in known and round(v / 100, 4) not in {round(k, 4) for k in known}:
                    errs.append(f"README number {n} not found in evals/results/: {line[:80]}")
    return errs


def main():
    update = "--update-lock" in sys.argv
    errs = check_gigsim(update) + check_prompts() + check_secrets() + check_numbers()
    for e in errs:
        print("FAIL:", e)
    print(json.dumps({"ok": not errs, "problems": len(errs)}))
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()

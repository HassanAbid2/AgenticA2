"""Shared eval plumbing: dev-set loading, gold mapping, metrics, resumable result files."""

from __future__ import annotations

import asyncio
import json
import math
import os
import statistics
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "evals" / "results"
RAW = RESULTS / "raw"
PERSONAS = ("ai_ml", "fullstack", "data_analyst")


def model_run(name: str) -> tuple[str, dict]:
    """Keep new profiles and local model changes out of historical evaluation logs."""
    import re

    from agent.config import settings

    models = settings()["models"]
    profile = models["profile"]
    config = models["profiles"][profile]
    nodes = config["nodes"]
    names = sorted(set(nodes.values()) | ({config["fallback"]} if config.get("fallback") else set()))
    suffix = re.sub(r"[^a-zA-Z0-9._-]+", "-", "_".join([profile, *names]))
    return (name if profile == "open" else f"{name.removesuffix('_open')}_{suffix}",
            {"profile": profile, "models": nodes, "model_names": names})


def eval_deadline() -> float | None:
    seconds = os.getenv("GIGBID_EVAL_SECONDS")
    return asyncio.get_running_loop().time() + float(seconds) if seconds else None


def load_dev(persona: str | None = None, split: str = "dev") -> list[dict]:
    rows = []
    for p in ([persona] if persona else PERSONAS):
        path = (ROOT / "evals" / "datasets" / f"dev_{p}.jsonl") if split == "dev" else (ROOT / "evals" / "holdout" / f"holdout_{p}.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            r["persona"] = p
            rows.append(r)
    return rows


def project_titles() -> dict[str, dict[str, str]]:
    """gold project slug -> canonical title, per persona (from the persona's case-study front matter)."""
    import re

    out = {}
    for p in PERSONAS:
        m = {}
        for f in (ROOT / "data" / "personas" / p / "case_studies").glob("*.md"):
            mm = re.search(r"^project: (.+)$", f.read_text(encoding="utf-8"), re.M)
            if mm:
                m[f.stem] = mm.group(1).strip()
        out[p] = m
    return out


def sample(rows: list[dict], n_per_persona: int, seed: int = 4016, where=None) -> list[dict]:
    """Deterministic stratified sample: first n per persona after a seeded shuffle (job ids are stable)."""
    import random

    out = []
    for p in PERSONAS:
        xs = [r for r in rows if r["persona"] == p and (where is None or where(r))]
        random.Random(seed).shuffle(xs)
        out += xs[:n_per_persona]
    return out


# ----------------------------------------------------------------------------- metrics
def ranking_metrics(ranked_projects: list[str], gold: set[str]) -> dict:
    uniq = list(dict.fromkeys(p for p in ranked_projects if p))
    rec5 = len(gold & set(uniq[:5])) / len(gold)
    mrr = next((1 / (i + 1) for i, p in enumerate(uniq) if p in gold), 0.0)
    dcg = sum(1 / math.log2(i + 2) for i, p in enumerate(uniq[:10]) if p in gold)
    idcg = sum(1 / math.log2(i + 2) for i in range(min(len(gold), 10)))
    return {"recall@5": rec5, "mrr": mrr, "ndcg@10": dcg / idcg if idcg else 0.0}


def f1(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(2 * p * r / (p + r), 4) if p + r else 0.0}


def pct(xs, q):
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))], 4)


def mean(xs):
    return round(statistics.fmean(xs), 4) if xs else None


def group_mean(rows: list[dict], key: str, fields: list[str]) -> dict:
    g = defaultdict(list)
    for r in rows:
        g[r[key]].append(r)
    return {k: {f: mean([x[f] for x in v if x.get(f) is not None]) for f in fields} | {"n": len(v)} for k, v in sorted(g.items())}


# ----------------------------------------------------------------------------- resumable raw results
class RawLog:
    """Append-only JSONL of per-item results; reruns skip items already done (free-tier friendly)."""

    def __init__(self, name: str):
        RAW.mkdir(parents=True, exist_ok=True)
        self.path = RAW / f"{name}.jsonl"
        self.done: dict[str, dict] = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    r = json.loads(line)
                    self.done[r["key"]] = r

    def has(self, key: str) -> bool:
        return key in self.done

    def add(self, key: str, rec: dict):
        rec = {"key": key, **rec, "ts": time.time()}
        self.done[key] = rec
        with open(self.path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(rec) + "\n")

    def values(self) -> list[dict]:
        return list(self.done.values())


def write_result(name: str, obj: dict):
    RESULTS.mkdir(parents=True, exist_ok=True)
    obj = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "git_commit": os.popen("git rev-parse --short HEAD").read().strip(), **obj}
    (RESULTS / f"{name}.json").write_text(json.dumps(obj, indent=1) + "\n", encoding="utf-8", newline="\n")
    return RESULTS / f"{name}.json"


class QuotaExhausted(Exception):
    """Raised when the provider says the daily token/request cap is used up; runners stop cleanly."""


def is_quota_error(e: BaseException) -> bool:
    s = str(e).lower()
    return "per day" in s or "tokens per day" in s or "requests per day" in s or "(tpd)" in s or "(rpd)" in s


def model_stop(e: Exception) -> str | None:
    from langgraph.errors import NodeTimeoutError
    from openai import APIConnectionError, APIStatusError

    if is_quota_error(e) or "rate limit" in str(e).lower():
        return "provider_quota"
    if isinstance(e, (NodeTimeoutError, APIConnectionError, APIStatusError)):
        return type(e).__name__
    return None

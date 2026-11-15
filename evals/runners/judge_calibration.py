"""LLM-judge calibration (B4): a human labels 30 proposals, Cohen's kappa against the judge.

    python -m evals.runners.judge_calibration --prepare   # writes evals/datasets/judge_calibration.csv
    (open the CSV, fill `human_label` with good/bad for every row, save)
    python -m evals.runners.judge_calibration --score     # judge verdicts + kappa -> evals/results/judge_calibration.json

Items: GigBid drafts from the proposal eval (if present) plus past persona proposals of known outcome,
shuffled so the labeller can't tell which is which. The human label is the ground truth; outcome
labels are reported only as a secondary reference.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import random

os.environ.update({"GIGBID_STRICT_LLM": "1"})

from evals.runners.common import RAW, ROOT, RawLog, eval_deadline, model_run, model_stop, write_result  # noqa: E402

CSV = ROOT / "evals" / "datasets" / "judge_calibration.csv"
KEY = ROOT / "evals" / "datasets" / "judge_calibration_key.json"  # hidden from the labeller


def prepare(n: int = 30):
    items = []
    from evals.runners.common import load_dev

    titles = {r["job"]["job_id"]: r["job"] for r in load_dev()}
    raw = RAW / "proposals_open.jsonl"
    if raw.exists():
        for line in raw.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r.get("final_text"):
                job = titles.get(r["key"].split("|")[1], {})
                items.append({"source": "gigbid", "job": f"{job.get('category', '')}: {job.get('title', '')}", "proposal": r["final_text"], "outcome": ""})
    rng = random.Random(30)
    for p in ("ai_ml", "fullstack", "data_analyst"):
        rows = [json.loads(x) for x in (ROOT / "data/personas" / p / "proposals.jsonl").read_text(encoding="utf-8").splitlines()]
        rng.shuffle(rows)
        for r in rows[:8]:
            items.append({"source": "past", "job": r["job_title"], "proposal": r["text"], "outcome": r["outcome"]})
    rng.shuffle(items)
    items = items[:n]
    with open(CSV, "w", newline="", encoding="utf-8") as f:  # blind: no source / outcome columns
        w = csv.DictWriter(f, fieldnames=["item_id", "job", "proposal", "human_label", "notes"])
        w.writeheader()
        for i, it in enumerate(items):
            w.writerow({"item_id": i, "job": it["job"], "proposal": it["proposal"], "human_label": "", "notes": ""})
    KEY.write_text(json.dumps({str(i): {"source": it["source"], "outcome": it["outcome"]} for i, it in enumerate(items)}, indent=1),
                   encoding="utf-8")
    print(f"wrote {CSV} with {len(items)} items: fill human_label (good/bad) for each row")


def kappa(a: list[str], b: list[str]) -> float | None:
    if not a:
        return None
    labels = sorted(set(a) | set(b))
    po = sum(x == y for x, y in zip(a, b, strict=True)) / len(a)
    pe = sum((a.count(lab) / len(a)) * (b.count(lab) / len(b)) for lab in labels)
    return round((po - pe) / (1 - pe), 4) if pe < 1 else 1.0


async def score():
    from evals.runners.proposal_eval import judge

    key = json.loads(KEY.read_text(encoding="utf-8"))
    rows = [r | key[r["item_id"]] for r in csv.DictReader(open(CSV, encoding="utf-8"))]
    labelled = [r for r in rows if r["human_label"].strip().lower() in ("good", "bad")]
    if len(labelled) < len(rows):
        raise SystemExit(f"{len(rows) - len(labelled)} rows still need a human_label (good/bad) in {CSV}")
    name, metadata = model_run("judge_calibration")
    log = RawLog(name)
    deadline = eval_deadline()
    stopped = None
    for r in labelled:
        item = r["item_id"]
        if log.has(item):
            continue
        try:
            async with asyncio.timeout_at(deadline):
                j = await judge({"title": r["job"], "description": r["job"]}, r["proposal"])
        except TimeoutError:
            stopped = "time_limit"
            break
        except Exception as e:
            stopped = model_stop(e)
            if not stopped:
                raise
            print(f"failed {item}: {stopped}; progress saved", flush=True)
            break
        verdict = (j or {}).get("verdict", "").strip().lower()
        log.add(item, {"judge_verdict": verdict if verdict in ("good", "bad") else None,
                       "judge_overall": (j or {}).get("overall"), "judge_why": (j or {}).get("why", "")})
        print("scored", item, verdict or "invalid", flush=True)
    attempted = [r | log.done[r["item_id"]] for r in labelled if log.has(r["item_id"])]
    out = [r for r in attempted if r["judge_verdict"] is not None]
    human = [r["human_label"].lower() for r in out]
    jd = [r["judge_verdict"].lower() for r in out]
    past = [r for r in out if r["outcome"]]
    labeller = "student" if not any("[assistant rubric label]" in r["notes"] for r in labelled) else "AI assistant with a written rubric (the student did not label; see docs/AI_USAGE.md)"
    res = {**metadata, "n": len(out), "n_attempted": len(attempted), "n_labelled": len(labelled),
           "complete": len(out) == len(labelled), "stopped": stopped, "labeller": labeller,
           "cohens_kappa_judge_vs_human": kappa(human, jd) if len(out) == len(labelled) else None,
           "agreement": round(sum(h == j for h, j in zip(human, jd, strict=True)) / len(out), 4) if out else None,
           "secondary_kappa_human_vs_outcome(past items)": kappa([r["human_label"].lower() for r in past],
                                                                 ["good" if r["outcome"] in ("won", "replied") else "bad" for r in past]),
           "disagreements": [{"item_id": r["item_id"], "human": r["human_label"], "judge": r["judge_verdict"], "judge_why": r["judge_why"],
                              "notes": r["notes"], "proposal": r["proposal"][:400]} for r in out if r["human_label"].lower() != r["judge_verdict"].lower()]}
    print(write_result(name, res), {k: v for k, v in res.items() if k != "disagreements"})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--score", action="store_true")
    a = ap.parse_args()
    prepare() if a.prepare else asyncio.run(score())

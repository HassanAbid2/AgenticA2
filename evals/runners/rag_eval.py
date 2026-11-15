"""R&D B retrieval evaluation: every RAG variant and combination on the dev set.

    python -m evals.runners.rag_eval                 # all variants (rerank variants on a stratified subset)
    python -m evals.runners.rag_eval --quick         # 20 jobs per persona (CI smoke)

Metrics (project level: the corpus describes each project several ways, so gold is the set of
relevant projects): Recall@5, MRR, nDCG@10, plus item-level recall of gold evidence ids in the top 5.
Writes evals/results/rag_variants.json (+ .csv) with breakdowns by persona and job type.
Pre-registered hypothesis (written before the run, see docs/adr/0003): requirement decomposition +
hybrid retrieval (V1+V2) raises Recall@5 by >= 5 points over V0 on multi-requirement jobs.
"""

from __future__ import annotations

import argparse
import csv
import time

from evals.runners.common import (
    RESULTS,
    group_mean,
    load_dev,
    mean,
    pct,
    project_titles,
    ranking_metrics,
    sample,
    write_result,
)

VARIANTS = ["v0", "v1", "v2", "v3", "v4", "v5", "v6", "v7", "v8", "v9",
            "v1+v2", "v1+v2+v9", "v1+v2+v4", "v1+v2+v3", "v1+v2+v4+v9", "v1+v2+v6+v9", "v1+v2+v5+v9", "v1+v2+v8+v9"]
SLOW = {"v3", "v1+v2+v3"}  # cross-encoder on CPU (~14 s/job): run on the stratified subset only


def run_variant(spec: str, rows: list[dict], titles) -> list[dict]:
    from rag.retriever import build

    r = build(spec)
    out = []
    for row in rows:
        gold_slugs = row["gold"]["relevant_projects"]
        if not gold_slugs:  # mismatch jobs: did the variant refuse to surface evidence? (V8's purpose)
            res = r(row["job"], [row["persona"]], k=10)
            out.append({"job_id": row["job"]["job_id"], "persona": row["persona"], "job_type": row["gold"]["job_type"],
                        "no_gold": True, "refused": len(res.items) == 0})
            continue
        gold = {titles[row["persona"]][s] for s in gold_slugs}
        t0 = time.perf_counter()
        res = r(row["job"], [row["persona"]], k=10)
        dt = time.perf_counter() - t0
        m = ranking_metrics([i["project"] for i in res.items], gold)
        gold_ids = set(row["gold"]["relevant_evidence_ids"])
        top5 = [i["evidence_id"] for i in res.items[:5]]
        m["item_recall@5"] = len(gold_ids & set(top5)) / min(5, len(gold_ids)) if gold_ids else 0.0
        out.append({"job_id": row["job"]["job_id"], "persona": row["persona"], "job_type": row["gold"]["job_type"],
                    "n_req": len(row["gold"]["requirements"]), "latency_s": dt, **m})
    return out


def summarise(per: list[dict]) -> dict:
    f = ["recall@5", "mrr", "ndcg@10", "item_recall@5"]
    skips = [x for x in per if x.get("no_gold")]
    per = [x for x in per if not x.get("no_gold")]
    multi = [x for x in per if x["n_req"] >= 4]
    if not per:
        return {"n": 0}
    return {"n": len(per), **{k: mean([x[k] for x in per]) for k in f},
            "recall@5_multi_req(>=4)": mean([x["recall@5"] for x in multi]), "n_multi_req": len(multi),
            "refusal_rate_on_mismatch_jobs": mean([x["refused"] for x in skips]), "n_mismatch": len(skips),
            "p50_latency_s": pct([x["latency_s"] for x in per], .5), "p95_latency_s": pct([x["latency_s"] for x in per], .95),
            "by_persona": group_mean(per, "persona", f), "by_job_type": group_mean(per, "job_type", f)}


def main(quick: bool = False):
    titles = project_titles()
    rows = load_dev()
    full = sample(rows, 20) if quick else rows
    subset = sample(rows, 20)
    results, per_job = {}, {}
    for spec in VARIANTS:
        rs = subset if spec in SLOW else full
        t = time.time()
        per = run_variant(spec, rs, titles)
        per_job[spec] = per
        results[spec] = summarise(per) | {"eval_set": "subset_50_per_persona" if spec in SLOW and not quick else ("quick" if quick else "full_dev")}
        print(f"{spec:14s} n={len(per):4d} R@5={results[spec]['recall@5']:.3f} MRR={results[spec]['mrr']:.3f} "
              f"nDCG={results[spec]['ndcg@10']:.3f} ({time.time() - t:.0f}s)", flush=True)
    # every variant also on the same subset, so slow variants compare like for like
    sub_ids = {r["job"]["job_id"] for r in subset}
    on_subset = {s: summarise([x for x in per_job[s] if x["job_id"] in sub_ids]) for s in VARIANTS}
    # ablation: drop one component of the best full-dev pipeline at a time
    best_full = max((s for s in VARIANTS if s not in SLOW), key=lambda s: (results[s]["ndcg@10"], results[s]["recall@5"]))
    parts = best_full.split("+")
    ablation = {"pipeline": best_full, "full": {k: results[best_full][k] for k in ("recall@5", "mrr", "ndcg@10")}}
    for p in parts:
        spec = "+".join(x for x in parts if x != p) or "v0"
        per = per_job.get(spec) or run_variant(spec, full, titles)
        sm = summarise(per)
        ablation[f"without_{p}"] = {k: sm[k] for k in ("recall@5", "mrr", "ndcg@10")}
    v0m = results["v0"]["recall@5_multi_req(>=4)"]
    hyp = results["v1+v2"]["recall@5_multi_req(>=4)"]
    best = max(VARIANTS, key=lambda s: (on_subset[s].get("ndcg@10", 0), on_subset[s].get("recall@5", 0)))
    out = write_result("rag_variants" + ("_quick" if quick else ""), {
        "metric_notes": "project-level ranking metrics; gold = relevant projects from the generator's ground truth",
        "hypothesis": "V1+V2 raises Recall@5 by >= 5 points over V0 on jobs with >= 4 requirements",
        "hypothesis_result": {"v0": v0m, "v1+v2": hyp, "delta_points": round((hyp - v0m) * 100, 1) if v0m is not None else None,
                              "supported": (hyp - v0m) >= 0.05 if v0m is not None else None},
        "variants": results, "same_subset_comparison": on_subset, "ablation_recall@5": ablation,
        "best_by_ndcg_on_subset": best, "best_by_ndcg_full_dev": best_full})
    with open(RESULTS / ("rag_variants" + ("_quick" if quick else "") + ".csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["variant", "eval_set", "n", "recall@5", "mrr", "ndcg@10", "item_recall@5", "recall@5_multi_req", "p95_latency_s"])
        for s in VARIANTS:
            v = results[s]
            w.writerow([s, v["eval_set"], v["n"], v["recall@5"], v["mrr"], v["ndcg@10"], v["item_recall@5"],
                        v["recall@5_multi_req(>=4)"], v["p95_latency_s"]])
    print("wrote", out, "| best on subset:", best)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    main(ap.parse_args().quick)

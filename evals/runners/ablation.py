"""Measure retrieval with one component removed from the selected pipeline at a time."""

import argparse

from evals.runners.common import load_dev, project_titles, sample, write_result


def run(pipeline, rows, titles, measured):
    from evals.runners.rag_eval import run_variant, summarise

    parts = pipeline.split("+")
    configurations = {"full": pipeline}
    for i, part in enumerate(parts):
        configurations[f"without_{part}"] = "+".join(parts[:i] + parts[i + 1:]) or "v0"
    ablation = {"pipeline": pipeline}
    for name, variant in configurations.items():
        records = measured.get(variant)
        if records is None:
            records = run_variant(variant, rows, titles)
        metrics = summarise(records)
        keys = ("recall@5", "mrr", "ndcg@10") if name == "full" else ("recall@5", "ndcg@10")
        ablation[name] = {key: metrics[key] for key in keys}
    return ablation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipeline", default="v1+v2+v6+v9")
    parser.add_argument("--quick", action="store_true", help="use 20 jobs per persona")
    args = parser.parse_args()
    rows = load_dev()
    if args.quick:
        rows = sample(rows, 20)
    result = run(args.pipeline, rows, project_titles(), {})
    print(write_result("ablation_quick" if args.quick else "ablation", {"n_jobs": len(rows), **result}))


if __name__ == "__main__":
    main()

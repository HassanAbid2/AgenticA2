"""Signature extension X2: proposal-strategy A/B test in GigSim with a significance test.

    python -m evals.runners.ab_experiment

Arms (prompt variants, config `proposal_strategies`): A = evidence_first, B = question_first. Every
proposal the eval pipeline drafts is assigned an arm by a stable hash of the job id (50/50) and submitted
to GigSim, whose simulated clients decide replies. This script reports reply rates, Fisher's exact
test for the small sample, and mean simulated reply probability by arm. Use one profile and retrieval
variant so there is one observation per job and the prompt is the only intended treatment.
"""

from __future__ import annotations

import argparse
import json
import math
from statistics import fmean, pvariance

from evals.runners.common import RAW, write_result


def phi(z):
    return 0.5 * math.erfc(-z / math.sqrt(2))


def two_prop_z(x1, n1, x2, n2):
    if not (n1 and n2):
        return None, None
    p = (x1 + x2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2)) if 0 < p < 1 else 0
    if not se:
        return 0.0, 1.0
    z = (x1 / n1 - x2 / n2) / se
    return round(z, 3), round(2 * (1 - phi(abs(z))), 4)


def welch(a, b):
    if len(a) < 2 or len(b) < 2:
        return None, None
    va, vb = pvariance(a) * len(a) / (len(a) - 1), pvariance(b) * len(b) / (len(b) - 1)
    se = math.sqrt(va / len(a) + vb / len(b))
    if not se:
        return 0.0, 1.0
    t = (fmean(a) - fmean(b)) / se
    return round(t, 3), round(2 * (1 - phi(abs(t))), 4)  # normal approximation (small-sample caveat in report)


def n_for_power(p1, p2, alpha_z=1.96, power_z=0.8416):
    if p1 == p2:
        return None
    pbar = (p1 + p2) / 2
    return math.ceil(((alpha_z * math.sqrt(2 * pbar * (1 - pbar)) + power_z * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2) / (p1 - p2) ** 2)


def fisher_exact(x1, n1, x2, n2):
    if not (n1 and n2):
        return None
    total = x1 + x2
    weight = lambda x: math.comb(n1, x) * math.comb(n2, total - x)  # noqa: E731
    return round(sum(weight(x) for x in range(max(0, total - n2), min(n1, total) + 1)
                     if weight(x) <= weight(x1)) / math.comb(n1 + n2, total), 4)


def main(variant):
    recs = [json.loads(x) for x in (RAW / "proposals_open.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    sent = {r["key"].split("|", 1)[1]: r for r in recs if r["variant"] == variant and r.get("outcome")
            and r.get("strategy") and "template" not in r.get("draft_sources", [])}
    sent = list(sent.values())
    arms = {}
    for arm in ("evidence_first", "question_first"):
        rs = [r for r in sent if r["strategy"] == arm]
        arms[arm] = {"n": len(rs), "replies": sum(bool(r["outcome"]["replied"]) for r in rs),
                     "reply_rate": round(sum(bool(r["outcome"]["replied"]) for r in rs) / len(rs), 4) if rs else None,
                     "mean_p_reply": round(fmean([r["outcome"].get("p_reply", 0) for r in rs]), 4) if rs else None,
                     "judge_mean": round(fmean([r["judge"]["overall"] for r in rs if r.get("judge")]), 3) if any(r.get("judge") for r in rs) else None}
    a, b = arms["evidence_first"], arms["question_first"]
    z, pz = two_prop_z(a["replies"], a["n"], b["replies"], b["n"])
    pf = fisher_exact(a["replies"], a["n"], b["replies"], b["n"])
    t, pt = welch([r["outcome"].get("p_reply", 0) for r in sent if r["strategy"] == "evidence_first"],
                  [r["outcome"].get("p_reply", 0) for r in sent if r["strategy"] == "question_first"])
    need = n_for_power(a["reply_rate"] or 0, b["reply_rate"] or 0) if a["n"] and b["n"] else None
    res = {"profile": "open", "variant": variant, "n": len(sent), "arms": arms,
           "reply_rate_fisher_exact": {"p_value": pf}, "reply_rate_two_proportion_z": {"z": z, "p_value": pz},
           "p_reply_welch": {"t": t, "p_value": pt},
           "n_per_arm_for_80pct_power_at_observed_difference": need,
           "conclusion": ("pending: both arms need submissions" if pf is None else "significant at 0.05" if pf < 0.05 else
                          "not significant at 0.05; this small pilot cannot establish which prompt performs better")}
    print(write_result("ab_experiment", res), json.dumps(res, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="v0")
    main(ap.parse_args().variant)

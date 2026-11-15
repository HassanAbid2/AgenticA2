# ADR 0003: Shipped retrieval pipeline chosen by measurement

Status: accepted (evidence: `evals/results/rag_variants.json`, all 600 dev jobs)

**Decision rule (written before running).** Ship the variant with the best nDCG@10 on the full dev set
among variants that need no LLM call per query and keep p95 retrieval latency under 1 s; break ties with
Recall@5. Cross-encoder variants were evaluated on a stratified 60-job subset because they take about
14 s per job on CPU, which already rules them out under the latency rule.

**Hypothesis.** Requirement decomposition + hybrid retrieval (V1+V2) raises Recall@5 by at least 5
points over V0 on jobs with four or more requirements. **Result: not supported, narrowly** (+4.8 points:
0.749 -> 0.797).

**Result.** Best evaluated combination: `v1+v2+v6+v9` (decomposition + hybrid BM25/dense + contextual
context lines + skill graph): nDCG@10 0.862 and Recall@5 0.880 vs V0 0.796 / 0.776, p95 0.80 s.

**Deviation from the rule, and why.** The ablation shows that dropping V1 gives nDCG@10 0.871 (MRR
0.958, Recall@5 0.869). Taken literally, the rule would ship `v2+v6+v9`. It is not shipped because V1 is
what produces one evidence list per requirement: the Fit Matcher's score, the requirement-to-evidence
matrix in the UI and the writer's per-requirement evidence all depend on it. A +0.009 nDCG gain does not
justify losing that function; the trade-off is reported as such rather than hidden.

**Negative results kept out of the shipped pipeline.**
* V4 outcome-aware boost: Recall@5 0.694 (worse than V0). Past winning proposals over-boost a few popular
  projects regardless of the requirement.
* V5 multi-vector grouping: 0.686. Grouping by project lets a weak project's many chunks outrank a strong
  single case study.
* V8 corrective loop: refuses evidence on 85% of jobs the persona should skip (its purpose), but its query
  rewriting lowers ranking quality when combined (0.739).
* V6 alone hurts (0.733) yet helps inside the combination: context lines add skill names that BM25 then
  matches exactly.
* Vague posts are the one job type where the shipped pipeline is slightly worse than V0 (0.747 vs 0.775);
  HyDE (V7, 0.809 overall) is the candidate for a vague-post route.

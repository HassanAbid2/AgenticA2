# ADR 0003: Shipped retrieval pipeline chosen by measurement

Status: accepted. Evidence: `evals/results/rag_variants.json` (all 600 dev jobs) and the end-to-end decision
runs `decisions_dev_offline*.json`.

**Decision rule (written before running).** Ship the variant with the best nDCG@10 on the full dev set among
variants that need no LLM call per query and keep p95 retrieval latency under 1 s; break ties with Recall@5.
Cross-encoder variants ran on a stratified 60-job subset (about 14 s/job on CPU, which already fails the
latency rule).

**Hypothesis.** Requirement decomposition + hybrid retrieval (V1+V2) raises Recall@5 by at least 5 points
over V0 on jobs with four or more requirements. **Not supported, narrowly:** +4.8 points (0.749 -> 0.797).

**Retrieval result.** Best evaluated combination by nDCG: `v1+v2+v6+v9` (nDCG@10 0.862, Recall@5 0.880);
runner-up `v1+v2+v9` (0.848 / 0.871); V0 0.796 / 0.776.

**Shipped: `v1+v2+v9`, a deliberate deviation from the rule, because retrieval is not the product metric.**
The Fit Matcher scores each requirement's strength from the retrieval similarity, so the retrieval variant
also drives bid/skip decisions. With pricing held fixed, swapping the Fit Matcher's retrieval from
`v1+v2+v9` to `v1+v2+v6+v9` lowered bid/skip F1 on the 600 dev jobs from 0.941 to 0.931 (bid recall 0.927 ->
0.907). The context lines shift cosine similarities downward, and the strength thresholds (`fit.strong_cos`,
`fit.partial_cos`) were calibrated on the plain index, so more good jobs fall to "watch". A +0.014 nDCG gain
is not worth losing bid recall. Recalibrating the thresholds for the contextual index is the follow-up that
could let V6 ship. The held-out proxy split agrees: bid/skip F1 0.934 with `v1+v2+v9` vs 0.922 with `v1+v2+v6+v9`
(`decisions_holdout_offline.json`, `decisions_holdout_offline_fit_v1+v2+v6+v9.json`). This is the clearest case in the project of better retrieval not translating into better
outcomes.

**Not shipped: V1.** Dropping V1 also scores slightly higher nDCG (0.871 for `v2+v6+v9`), but V1 produces the
per-requirement evidence lists the Fit Matcher, the writer and the UI's requirement-to-evidence matrix need.

**Negative results.**
* V4 outcome-aware boost: Recall@5 0.694 (below V0). Past winning proposals over-boost a few popular projects
  regardless of the requirement.
* V5 multi-vector grouping: 0.686. A weak project's many chunks outrank a strong single case study.
* V8 corrective loop: refuses evidence on 85% of jobs the persona should skip (its purpose), but its query
  rewriting lowers ranking quality when combined (0.739).
* V6 alone hurts (0.733) yet helps inside the combination: the context lines add skill names that BM25 then
  matches exactly.
* Vague posts are the one job type where decomposition is slightly worse than V0; HyDE (V7, 0.809 overall) is
  the candidate for a vague-post route.

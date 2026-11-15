# ADR 0003: Shipped retrieval pipeline chosen by measurement

Status: accepted (evidence: `evals/results/rag_variants.json`)

**Decision rule (written before running).** Ship the variant with the best nDCG@10 on the full dev set
among variants that need no LLM call per query and keep p95 retrieval latency under 1 s; break ties with
Recall@5. Cross-encoder variants were evaluated on a stratified 60-job subset because they take about
14 s per job on CPU, which already rules them out under the latency rule.

**Hypothesis.** Requirement decomposition + hybrid retrieval (V1+V2) raises Recall@5 by at least 5
points over V0 on jobs with four or more requirements.

**Result.** See the README results tables. `rag.variant` in `agent/config.yaml` is set to the winner;
variants that lowered ranking quality on this corpus (outcome-aware boost V4, multi-vector grouping V5,
corrective query rewriting V8) are not shipped and are discussed as negative results in the report.

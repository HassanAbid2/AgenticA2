# ADR 0005: Deterministic claim verification, LLM only for the grey zone

Status: accepted

**Decision.** `rag/verify.py` splits drafts into claims (experience verbs or metrics; plans, questions,
offers and restatements of the post are not claims), compares each with the closest two-sentence passage
of its cited evidence, and requires every number and named tool in the claim to appear in that evidence.
Only `partly_supported` cases go to the small LLM judge. Unsupported claims are removed before the Critic.
The compliance model never judges facts: it cannot see the evidence, and when it was allowed to, it deleted
true claims.

**Consequences.** Cheap and explainable (the reasons for every claim are shown on hover in the studio).
Live runs exposed Unicode differences in model output (narrow no-break spaces in "62 %", non-breaking
hyphens), so text is normalised before comparison. A cover letter with no grounded claim left after the
maximum revisions goes to *needs attention*, never to the human.

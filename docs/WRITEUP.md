# What GigBid taught me about trusting AI agents

GigBid scans freelance jobs, flags scams, recommends bids, and writes proposals from portfolio evidence. A person reviews every proposal before it goes to the marketplace. I expected the hardest part to be getting the agents to cooperate. The bigger challenge was deciding when a model's answer deserved to influence a bid. Four experiments changed where I put those checks, from the evidence shown alongside a proposal to the thresholds that decide which jobs reach the writer.

## Citations need verification

In 12 baseline proposals generated with Groq, the verifier flagged **30.6% of experience claims** before review and **0% after filtering**. The writer already had instructions to cite every experience claim. Some citations pointed to real projects while the sentence combined details from different projects or turned a general description into a named tool. A valid citation made the sentence look more credible even when its evidence supported only part of it. [Proposal evaluation](../evals/results/proposals_open.json)

The verifier now checks each claim against the closest passage of the cited evidence and looks for support for its numbers and named tools. This lets me distinguish a link that opens from evidence that backs the claim. It also gives the reviewer something concrete to inspect in the proposal studio. If a claim has to be removed, the person reviewing the proposal can see what changed before deciding whether the letter still answers the job post.

The rejects also exposed errors in the verifier. A statement about work delivered in 2022 failed because the date appeared in case study metadata. Checking the rejected claims revealed that the verifier had overlooked valid evidence. For future evaluations, I want to track both unsupported claims that survive and supported claims that get removed. False positives can erase the specific experience that makes a proposal worth reading.

## Scam flags need a stronger threshold

The Risk Assessor uses signals from the job post and the client's history. In an early version, I accepted the model's additional risk flags at face value. On the same **30 jobs**, scam precision dropped from **0.75 to 0.38**. Recall was already **1.0** with the rules on that sample. The extra flags made legitimate jobs look suspicious without finding additional scams. [Trusted-flag run](../evals/results/decisions_dev_open_v1_trusted_llm_flags.json) · [Gated run](../evals/results/decisions_dev_open.json)

The mistakes mattered because a false alarm can keep a freelancer from seeing a suitable job. The model read a low budget as suspicious and treated an ordinary request for a call as a sign of off-platform contact. GigBid now lets the model add flags when its scam probability reaches **0.7**, and the combined score determines the decision. Precision returned to **0.75** on that sample. For the next threshold change, I would review the jobs that switched from ordinary to suspicious. Those examples show which model flags affect the freelancer's inbox and whether the gate is worth keeping at its current setting.

On those same 30 jobs, the gated hosted model and the rules alone both scored **0.909 bid-or-skip F1**. I kept the larger dev evaluation separate because it used a different sample size. The paired result supports using model calls selectively. It also gives me a baseline to revisit when I change the risk threshold or try a stronger analyst. [Paired decision evaluation](../evals/results/decisions_dev_open.json)

The same evaluation helped decide where to spend model calls. A vague request such as “make our site faster” can benefit from a model that extracts concrete requirements. Pricing and bid thresholds already receive inputs that can be checked and compared directly. Keeping those decisions explicit makes it possible to explain a skip and rerun the decision after changing a threshold, with the rest of the pipeline held fixed.

## Each checker needs the evidence for its decision

I gave an early compliance model the proposal text and asked it to identify invented experience. It removed a supported claim about reducing support ticket response time by 38%. From its input, it could see a statistic and no evidence for it. The portfolio was available elsewhere in the pipeline, so the compliance step had been asked to make a decision with a real input missing. [R&D report](report/GigBid_RD_Report.pdf)

I assigned factual checks to the verifier, which receives portfolio evidence. The Compliance Guard focuses on what it can see in the letter, including contact details, requests to move payment off the platform, and guarantees. This division makes failures easier to diagnose. A missing result now points back to the evidence selected and the way the verifier read it. An off-platform payment suggestion points to the policy checks. The review in the studio still gives the freelancer the final decision.

## Better retrieval changed which jobs got bids

I compared retrieval variants on a synthetic dev corpus of **600 labelled jobs**. Boosting projects mentioned in proposals that won or received replies reduced Recall@5 from **0.776 to 0.694**. It pushed frequently cited projects toward the top of searches, including jobs that called for different work. Grouping chunks by project also hurt recall. Grouping reached **0.686 Recall@5**. A project with several mediocre matches could outrank one case study with a precise answer. The scores made me check whether the top evidence answered the requirement before using past outcomes to promote it. [Retrieval results](../evals/results/rag_variants.json)

Splitting a job into requirements, adding BM25 for exact terms such as Celery and dbt, and using a skill graph helped. With extra context attached to each chunk, the best-ranked combination reached **0.880 Recall@5** and **0.862 nDCG@10**. My stated hypothesis for requirement splitting plus hybrid retrieval was a five-point recall gain on jobs with four or more requirements. The measured gain was **4.8 points**, just below the target. [Retrieval results](../evals/results/rag_variants.json)

The fit step uses similarity scores to decide whether a requirement has strong, partial, or missing evidence. Adding context changed the scores, so the existing thresholds classified some jobs differently. With the rest of the system held fixed, the best-ranked retrieval variant reduced bid-or-skip F1 from **0.941 to 0.931**. I shipped the variant without the extra chunk context. It reached **0.848 nDCG@10** and kept the stronger downstream decision score. If I revisit the context variant, I would recalibrate the fit thresholds and evaluate it against a separate labelled set. [Retrieval decision record](adr/0003-rag-variant-choice.md)

## What the smaller pilots can tell us

The simulator measures how proposals performed against synthetic clients. In the Groq pilot, the evidence-first opening received **3 replies from 7 submissions** and the question-first opening received **1 from 5**. Fisher's exact test gave **p = 0.576**. The counts are too small to choose an opening confidently, and the sample covers submitted proposals in GigSim. A larger comparison should use the same selection rules for both openings and track which jobs produce submissions. [A/B results](../evals/results/ab_experiment.json)

The judge pilot exposed a separate problem. Qwen2.5 0.5B attempted **30 assistant-labelled items**, returned **good** for every valid verdict, and abstained on three malformed outputs. Cohen's kappa was **0.071**. The verdict distribution explains why I would avoid using this judge to rank the openings. A useful follow-up would compare a stronger judge against independent labels and inspect the disagreements alongside the aggregate score. [Judge calibration](../evals/results/judge_calibration_local_qwen2.5-0.5b.json)

The reply counts and judge scores answer different questions. Reply counts reflect how the simulator responded to submissions. A judge can flag a weak claim before submission, including on jobs that may never receive a reply. I would keep both measurements visible in the next trial.

These experiments left GigBid with specific checks at the points where mistakes cost the freelancer time or money. The writer can propose language, the verifier checks whether the portfolio supports it, and the freelancer decides whether to spend Connects on the job. The next experiment I would prioritize is recalibrating fit after changing retrieval, because that choice controls which jobs get far enough for proposal quality to matter. [Full results](RESULTS.md)

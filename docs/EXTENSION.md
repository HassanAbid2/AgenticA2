# Signature extension: X2 proposal experiments

**What.** Two proposal strategies run as a live A/B test inside GigBid, measured on GigSim's simulated
clients with a significance test on reply rate.

| Arm | Prompt | Strategy |
|---|---|---|
| A `evidence_first` | `agent/prompts/writer_evidence_first.md` | client's problem in their words, then the two strongest results, a first-milestone plan, one question |
| B `question_first` | `agent/prompts/writer_question_first.md` | open with a diagnostic question about the real (often hidden) need, one result, a 3-step plan, a question |

**How it works.**
* Assignment: a stable hash of the job id puts each job in an arm (`proposal_strategies.split`, 50/50),
  so a job always gets the same arm across retries and replays (`agent/nodes/writer.py::pick_strategy`).
* The arm is stored on the draft and on the `proposals` row (`strategy`), shown in the studio and on
  pipeline cards, and aggregated by the outcome-memory promotion rule (`rate_by_strategy`, `best_strategy`),
  so the writer is told which arm has been winning per job category once there is enough data.
* Arms are prompt files plus one config list: adding a third arm is a new `.md` file and a config entry.

**Measurement.** `python -m evals.runners.ab_experiment` pools every proposal the evals submitted to GigSim
(no extra LLM cost) and reports, per arm: reply rate with a two-proportion z-test; mean simulated reply
probability (GigSim's `p_reply`, lower variance) with Welch's t-test; and the sample size per arm needed for
80% power at the observed difference. Results: `evals/results/ab_experiment.json`, summarised in
`docs/RESULTS.md`.

**Honest limits.** On the Groq free tier the eval budget allows a few dozen proposals, far below the
hundreds per arm the power analysis asks for; the result is therefore reported as an effect estimate with
its p-value and the required sample size, not as a winner. GigSim's heuristic clients reward specific
opening lines and a question, which both arms include, so the expected effect is small.

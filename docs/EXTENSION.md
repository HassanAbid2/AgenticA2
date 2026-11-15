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

**Measurement.** `python -m evals.runners.ab_experiment --variant v0` reuses submitted Groq `open`
proposals with one entry per job. It reports a two-sided Fisher exact test on reply rates and the mean
simulated reply probability per arm. See [`docs/RESULTS.md`](RESULTS.md) for the pilot results.

**Limits.** The pilot conditions on submitting a draft and uses GigSim clients. Its small sample cannot
establish a winner or predict how real clients will respond. A follow-up should keep the model and retrieval
variant fixed, count all jobs assigned to each arm, and collect more outcomes.

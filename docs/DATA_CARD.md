# Data card

All data in this repository is **synthetic**: no real clients, freelancers or marketplace records.

## Why it was generated
The assignment's starter kit (v0.1) referred to instructor-provided GigSim data, three persona corpora, a
policy pack, a job stream and a dev set with gold labels, but shipped only five tiny examples. Everything
was therefore generated deterministically by `scripts/generate_synthetic_data.py` (seed 4016) from the
hand-written ground truth in `scripts/catalog.py`, so gold labels are known by construction rather than
inferred by the system being evaluated.

## Contents
| Asset | Path | Size |
|---|---|---|
| Persona corpora: AI/ML engineer, full-stack developer, data analyst | `data/personas/<persona>/` | 18-19 projects each: CV (PDF), case studies (Markdown + front matter), a second write-up for about a third of projects, repo READMEs and code, 14 client reviews, 150 past proposals labelled won / replied / ignored |
| Policy pack | `data/policy_pack/marketplace_policy.{md,yaml}` | 8 rules, including the 2 Nov 2026 disclosure rule |
| GigSim seed | `gigsim/seed/dev/` | 360 clients (public history + hidden preferences), 600 open jobs, a 240-job live stream (duplicates, scams, planted injections), 1,500 historical jobs for price statistics |
| Dev set | `evals/datasets/dev_<persona>.jsonl` | 200 jobs per persona; gold: bid/skip, scam, injection canary, relevant projects and evidence ids, fair price band, requirements, job type |
| Held-out proxy | `--split holdout --seed 999` into git-ignored folders | same shape, new jobs and clients |
| Judge calibration sheet | `evals/datasets/judge_calibration.csv` | 30 proposals; `human_label` filled in by the student |

Job types per persona: standard 60, multi-requirement 30, exact tool name 25, vague 20, industry 15,
mismatch 20, low budget 10, scam 12, planted injection in a legitimate job 4, injection + scam 4.

## Deliberate messiness (to defeat naive RAG)
* About 40% of the skills in a case study are only described ("a Redis-backed task queue with retrying
  workers"), never named; code files reveal them through imports; about 35% of READMEs are terse.
* The same project appears under three names (case-study title, product name, repo name). The ingester
  resolves aliases and falls back to wording overlap (measured: no wrong attributions).
* Job posts describe needs in the client's own words (`CLIENT_NEED`), never copying portfolio wording.
* Past proposals' outcomes depend on specificity (specific ones win about 24% of the time, generic ones about 3%).

## Gold label rules
* `bid`: not a scam, budget at or above the persona's floor, at least 60% of required skills covered by the
  persona, and the client not flagged as difficult (half of difficult-client jobs are labelled skip).
* `relevant_projects`: the anchor project plus projects sharing at least two non-generic required skills (max 4).
* `fair_price_band`: 0.8-1.2x the generator's fair price (category hours x requirement count x market rate).

## Known limitations
* Synthetic text is more regular than real posts; absolute scores overstate real-world performance.
* GigSim's heuristic clients reward must-have skills, concrete results, a question and answered screening
  questions; reply rates measure fit to that model, not to real clients.
* Mismatch jobs are easy to skip because their skills are disjoint from the persona's.

## Handling
Synthetic and shareable. The held-out proxy never enters the repository. Live-mode Upwork data is never
committed; OAuth tokens are encrypted at rest and masked in logs and traces.

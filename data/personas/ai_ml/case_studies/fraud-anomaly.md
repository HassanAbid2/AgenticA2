---
project: Card-fraud anomaly detection
client_industry: fintech
date: 2022-06
skills: [Python, scikit-learn]
---

# Card-fraud anomaly detection

## Context
The brief from this fintech company was simple to say and hard to do: flag suspicious card transactions in near real time. They had tried an off-the-shelf tool first and it did not fit their workflow.

## What I built
I designed and shipped the solution end to end using Python, scikit-learn. Under the hood it relies on gradient-boosted decision trees. Under the hood it relies on managed training jobs and endpoints on Amazon. I wrote tests for the critical paths and documented the handover.

## Results
The system caught 31% more fraud at the same false-positive rate.

## Stack
- Python
- scikit-learn

---
project: App-review sentiment analytics
client_industry: mobile apps
date: 2022-12
skills: [Python, NLP, Hugging Face Transformers, pandas]
---

# App-review sentiment analytics

## Context
A mobile apps client came to me needing make sense of thousands of app-store reviews and tell us what users complain about. They had tried an off-the-shelf tool first and it did not fit their workflow.

## What I built
I designed and shipped the solution end to end using Python, NLP, Hugging Face Transformers, pandas. Under the hood it relies on the standard classical-ML toolkit (pipelines, cross-validation). I wrote tests for the critical paths and documented the handover.

## Results
The system tagged 250k reviews into 14 themes with 0.87 macro-F1.

## Stack
- Python
- NLP
- Hugging Face Transformers
- pandas

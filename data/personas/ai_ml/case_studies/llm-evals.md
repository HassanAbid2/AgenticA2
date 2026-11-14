---
project: LLM evaluation harness
client_industry: SaaS
date: 2025-03
skills: [Python, LLM evaluation, prompt engineering]
---

# LLM evaluation harness

## Context
The brief from this SaaS company was simple to say and hard to do: a way to test our chatbot answers automatically before each release. They had tried an off-the-shelf tool first and it did not fit their workflow.

## What I built
I designed and shipped the solution end to end using Python, LLM evaluation, prompt engineering. Under the hood it relies on hosted GPT models called over HTTP. I wrote tests for the critical paths and documented the handover.

## Results
The system caught 3 regressions before release; judge agreement with humans kappa 0.74.

## Stack
- Python
- LLM evaluation
- prompt engineering

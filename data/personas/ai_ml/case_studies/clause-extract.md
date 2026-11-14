---
project: Contract clause extraction
client_industry: legal
date: 2024-01
skills: [Python, Hugging Face Transformers, FastAPI]
---

# Contract clause extraction

## Context
The brief from this legal company was simple to say and hard to do: a tool that pulls key clauses (termination, liability, renewal) out of our contracts. They had tried an off-the-shelf tool first and it did not fit their workflow.

## What I built
I designed and shipped the solution end to end using Python, Hugging Face Transformers, FastAPI. Under the hood it relies on an industrial NLP pipeline with custom entity rules. Under the hood it relies on text classification and entity extraction. I wrote tests for the critical paths and documented the handover.

## Results
The system reached F1 0.91 on 12 clause types and saved paralegals ~20 hours a week.

## Stack
- Python
- Hugging Face Transformers
- FastAPI

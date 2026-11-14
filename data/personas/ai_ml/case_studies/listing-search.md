---
project: Semantic search for property listings
client_industry: real estate
date: 2024-09
skills: [Python, FAISS, Docker]
---

# Semantic search for property listings

## Context
A real estate client came to me needing let buyers search listings in plain English like "quiet 3-bed near a park". They had tried an off-the-shelf tool first and it did not fit their workflow.

## What I built
I designed and shipped the solution end to end using Python, FAISS, Docker. Under the hood it relies on dense sentence vectors for semantic similarity. Under the hood it relies on a typed async Python web API. I wrote tests for the critical paths and documented the handover.

## Results
The system search success rate up from 61% to 84%.

## Stack
- Python
- FAISS
- Docker

---
project: Multi-agent research assistant
client_industry: consulting
date: 2025-04
skills: [Python, prompt engineering, Pinecone]
---

# Multi-agent research assistant

## Context
This engagement (consulting) started with a pain point - an AI helper that researches a market and drafts a cited report for our analysts. They had tried an off-the-shelf tool first and it did not fit their workflow.

## What I built
I designed and shipped the solution end to end using Python, prompt engineering, Pinecone. Under the hood it relies on a stateful agent graph with checkpoints and human approval steps. Under the hood it relies on an LLM orchestration library with retrievers and chains. Under the hood it relies on hosted GPT models called over HTTP. I wrote tests for the critical paths and documented the handover.

## Results
The system first-draft market reports went from 5 hours to 40 minutes.

## Stack
- Python
- prompt engineering
- Pinecone

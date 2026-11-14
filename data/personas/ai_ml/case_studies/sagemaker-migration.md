---
project: ML platform migration to SageMaker
client_industry: logistics
date: 2024-03
skills: [MLflow, Docker, Python, CI/CD]
---

# ML platform migration to SageMaker

## Context
The brief from this logistics company was simple to say and hard to do: move our models off a single EC2 box to a proper deployment pipeline. They had tried an off-the-shelf tool first and it did not fit their workflow.

## What I built
I designed and shipped the solution end to end using MLflow, Docker, Python, CI/CD. Under the hood it relies on managed training jobs and endpoints on Amazon. I wrote tests for the critical paths and documented the handover.

## Results
The system deploy time for a model went from 2 days to 25 minutes.

## Stack
- MLflow
- Docker
- Python
- CI/CD

---
project: Chest X-ray triage classifier
client_industry: healthcare
date: 2023-12
skills: [Python, Docker]
---

# Chest X-ray triage classifier

## Context
The brief from this healthcare company was simple to say and hard to do: prioritise urgent scans so radiologists see them first. They had tried an off-the-shelf tool first and it did not fit their workflow.

## What I built
I designed and shipped the solution end to end using Python, Docker. Under the hood it relies on Google's deep learning framework with Keras layers. Under the hood it relies on models that look at images and video frames. I wrote tests for the critical paths and documented the handover.

## Results
The system AUROC 0.93 on a held-out hospital; radiologist review queue reordered by urgency.

## Stack
- Python
- Docker

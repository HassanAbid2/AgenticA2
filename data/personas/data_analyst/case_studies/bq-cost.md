---
project: BigQuery cost optimisation
client_industry: media
date: 2025-09
skills: [SQL]
---

# BigQuery cost optimisation

## Context
A media client came to me needing our cloud data warehouse bill keeps growing; help us cut it. They had tried an off-the-shelf tool first and it did not fit their workflow.

## What I built
I designed and shipped the solution end to end using SQL. Under the hood it relies on Google's serverless warehouse billed per byte scanned. Under the hood it relies on version-controlled SQL models with tests and documented lineage. I wrote tests for the critical paths and documented the handover.

## Results
The system monthly warehouse bill down 48% with partitioning and incremental models.

## Stack
- SQL

---
project: Inventory API with background jobs
client_industry: retail
date: 2024-04
skills: [Django, PostgreSQL, Docker]
---

# Inventory API with background jobs

## Context
A retail client came to me needing keep stock levels in sync between our warehouses and the online shop. They had tried an off-the-shelf tool first and it did not fit their workflow.

## What I built
I designed and shipped the solution end to end using Django, PostgreSQL, Docker. Under the hood it relies on a Redis-backed task queue with retrying workers. Under the hood it relies on an in-memory store used for caching and pub/sub. I wrote tests for the critical paths and documented the handover.

## Results
The system stock sync across 3 warehouses every 2 minutes instead of nightly.

## Stack
- Django
- PostgreSQL
- Docker

---
project: Multi-tenant CRM
client_industry: real estate
date: 2023-10
skills: [Django, PostgreSQL, Redis, Celery]
---

# Multi-tenant CRM

## Context
The brief from this real estate company was simple to say and hard to do: a CRM for estate agencies where each agency only sees its own leads. They had tried an off-the-shelf tool first and it did not fit their workflow.

## What I built
I designed and shipped the solution end to end using Django, PostgreSQL, Redis, Celery. Under the hood it relies on component-based UI with hooks. Under the hood it relies on Amazon cloud (S3, Lambda, RDS). I wrote tests for the critical paths and documented the handover.

## Results
The system rolled out to 45 agencies with strict per-tenant data isolation.

## Stack
- Django
- PostgreSQL
- Redis
- Celery

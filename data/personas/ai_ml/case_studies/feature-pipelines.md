---
project: Feature pipelines on Airflow
client_industry: logistics
date: 2023-05
skills: [Python, pandas]
---

# Feature pipelines on Airflow

## Context
A logistics client came to me needing reliable nightly data preparation for our delivery-time models. They had tried an off-the-shelf tool first and it did not fit their workflow.

## What I built
I designed and shipped the solution end to end using Python, pandas. Under the hood it relies on DAG-scheduled batch pipelines. Under the hood it relies on a relational database with strong constraints. I wrote tests for the critical paths and documented the handover.

## Results
The system nightly features ready by 6am with zero missed runs in 9 months.

## Stack
- Python
- pandas

---
project: Payment reconciliation tool
client_industry: fintech
date: 2024-06
skills: [Node.js, Express, PostgreSQL, Stripe]
---

# Payment reconciliation tool

## Context
A fintech client came to me needing match payment-provider payouts against our orders so finance stops doing it by hand. They had tried an off-the-shelf tool first and it did not fit their workflow.

## What I built
I designed and shipped the solution end to end using Node.js, Express, PostgreSQL, Stripe. Under the hood it relies on Amazon cloud (S3, Lambda, RDS). I wrote tests for the critical paths and documented the handover.

## Results
The system matched 99.4% of payouts automatically; month-end close 3 days shorter.

## Stack
- Node.js
- Express
- PostgreSQL
- Stripe

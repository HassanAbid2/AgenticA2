---
project: LoRA fine-tune for clinical note summaries
client_industry: healthcare
date: 2025-05
skills: [Python, Hugging Face Transformers, LLM evaluation]
---

# LoRA fine-tune for clinical note summaries

## Context
The brief from this healthcare company was simple to say and hard to do: summaries of long discharge notes that doctors can trust. They had tried an off-the-shelf tool first and it did not fit their workflow.

## What I built
I designed and shipped the solution end to end using Python, Hugging Face Transformers, LLM evaluation. Under the hood it relies on a dynamic-graph deep learning framework from Meta. Under the hood it relies on parameter-efficient adapters trained on a 7B base model. I wrote tests for the critical paths and documented the handover.

## Results
The system ROUGE-L up 9 points; clinicians preferred its summaries 71% of the time.

## Stack
- Python
- Hugging Face Transformers
- LLM evaluation

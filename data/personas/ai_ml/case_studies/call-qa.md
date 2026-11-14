---
project: Call transcription and QA scoring
client_industry: call centers
date: 2024-12
skills: [Python, speech recognition, Celery, AWS]
---

# Call transcription and QA scoring

## Context
The brief from this call centers company was simple to say and hard to do: score every recorded sales call against our QA checklist. They had tried an off-the-shelf tool first and it did not fit their workflow.

## What I built
I designed and shipped the solution end to end using Python, speech recognition, Celery, AWS. Under the hood it relies on text classification and entity extraction. I wrote tests for the critical paths and documented the handover.

## Results
The system QA coverage went from 2% of calls sampled by hand to 100% scored automatically.

## Stack
- Python
- speech recognition
- Celery
- AWS

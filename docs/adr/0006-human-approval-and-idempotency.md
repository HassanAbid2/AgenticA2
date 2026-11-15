# ADR 0006: Approvals persisted before resuming; idempotent writes

Status: accepted

**Decision.** The UI writes the decision to the `approvals` table first; the worker then resumes the
interrupted thread with `Command(resume=decision)`. Marketplace writes carry idempotency keys derived
from the thread id and content hash; the Marketplace MCP server stores the first result per key and
GigSim honours the key as well. A second decision on the same approval returns 409.

**Consequence.** A refresh never loses an approval, and killing the API or the worker between approval
and submission still submits exactly once (the integration test re-runs the submit node from the
checkpoint and checks one submission and one Connects charge).

# ADR 0004: Contextual retrieval with metadata context lines

Status: accepted for the experiment

**Context.** Contextual retrieval prepends a generated line to each chunk. With about 870 chunks per scheme
and Groq's free-tier daily caps, one LLM call per chunk per re-index is not affordable.

**Decision.** V6 builds the context line from metadata the ingester already extracts (type, resolved
project, client industry, skills, outcome). The LLM-written version is a one-line change in
`rag/index/store.py::chunk_doc` when a budget allows it.

**Consequence.** The measured V6 effect is a lower bound for LLM-written context lines.

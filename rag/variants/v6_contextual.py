"""V6 contextual retrieval: a context line (type, project, industry, skills, outcome) is prepended to
each chunk before embedding and BM25 indexing. The line is generated from document metadata rather
than by an LLM per chunk (see docs/adr/0004-contextual-retrieval.md for why)."""

CONFIG = {"scheme": "contextual"}

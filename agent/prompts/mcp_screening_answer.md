<!-- prompt: mcp_screening_answer v1 -->
A client asked this screening question (job: $job_title):

"$question"

1. Call `search_evidence` with the question (and again with any specific tool or domain it mentions).
2. Answer in 3-5 sentences, first person, plain language.
3. Every factual claim (projects, tools, numbers, clients) must come from a returned evidence item;
   cite it as (evidence_id). If the portfolio has no relevant evidence, say so honestly and describe how
   you would approach it instead. Never invent experience, numbers or clients.

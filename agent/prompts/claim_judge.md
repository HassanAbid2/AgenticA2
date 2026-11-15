<!-- prompt: claim_judge v1 -->
## system
Decide whether a CLAIM from a proposal is fully supported by the EVIDENCE. Numbers, tools, clients and
outcomes must be stated in the evidence; a faithful paraphrase of what the evidence says IS supported (e.g. 'a
self-hosted Rust vector database' supports 'a Rust-based vector store'). Reply with one word: supported or unsupported.

## user
CLAIM: $claim

EVIDENCE:
$evidence

# The least trustworthy part of my AI agent was the AI

*Draft for LinkedIn / Medium (about 1,450 words). Every number links to a results file in the GigBid repo.*

I spent the last few weeks building GigBid, a team of nine AI agents that does the tedious half of
freelancing: it scans job feeds, flags scams, decides whether a job is worth the paid "Connects" a bid costs,
and drafts a proposal in which every claim points at real evidence from my portfolio. A human approves
everything before it leaves the system. It runs on open-weight models through Groq's free tier, which turned
out to matter: with 200,000 tokens a day for the big model, every experiment had to earn its tokens.

I expected the hard part to be the agents. It wasn't. The most surprising thing my experiments showed is
that, again and again, the language model was the component I could trust least, and the parts that made
the system good were boring, deterministic and measurable. Here are four results that changed how I build
agents.

## 1. A third of the experience claims were not supported, even when citations were mandatory

The writer's prompt is strict: every sentence that claims experience must cite a numbered evidence item, and
must not claim anything the evidence doesn't state. I then ran every draft through a claim verifier before a
critic agent saw it. The verifier splits the letter into claims, finds the closest passage of the cited
evidence, and requires every number and named tool in the claim to appear in that evidence.

On the first 12 live drafts, **30.6% of experience claims failed verification** (`proposals_open.json`).
They weren't wild hallucinations. They were the plausible kind: the model merged two different projects into
one impressive sentence, or turned "a self-hosted vector database written in Rust" into a named product, or
quoted a result from one project as if it belonged to another. With citations attached, they looked
trustworthy, which is exactly why they were dangerous. After verification removed them, the rate in what
reached me for approval was 0%.

The twist: some of those removals were wrong. A claim like "In 2022 I delivered..." failed because the year
lives in the case study's metadata, not its text. The checker needed checking too. I only found it by
reading the removed claims one by one, which is now a step in my evaluation, not an afterthought.

## 2. Trusting a small model's judgement halved scam precision

Scams are a real cost for freelancers: "build the full app as a free test", "let's move to Telegram and I'll
pay in USDT". GigBid's Risk Assessor combines rules (pattern signals plus the client's history: payment
verified, hires, ratings) with a small LLM classifier for the subtle cases.

My first version simply added any red flags the model named. On the same 30 jobs, scam **precision dropped
from 0.75 with rules alone to 0.38** with the model's flags trusted (`decisions_dev_open_v1_trusted_llm_flags.json`).
The model was "helpfully" calling ordinary jobs scams: a low budget became "suspicious", a mention of a call
became "off-platform contact". Recall was already 1.0 from the rules, so the model added false alarms and
nothing else.

The fix was a confidence gate: the model may add flags only when its own scam probability is at least 0.7,
and it never declares "scam" by itself; the combined score does. Precision went back to 0.75. More
uncomfortable was the overall result on bid-or-skip decisions: the LLM profile **matched but did not beat**
the deterministic rules on the same jobs (F1 0.909 either way), while costing about 2,200 tokens per job
(`decisions_dev_open.json`). On 600 dev jobs the rule-based path alone scores F1 0.94 with 100% scam recall.

The language model isn't useless here: on vague posts ("we're not technical, we need our website to load
faster"), turning a client's words into capabilities is a language problem, and that's where the LLM analyst
is worth its tokens. But "is this a scam?" turned out to be a question of evidence (payment verification,
zero hires, the word "USDT"), and rules answer it better and cheaper.

## 3. A compliance model that can't see the evidence deletes the truth

The Compliance Guard enforces the platform's policy: no contact details, no off-platform payment, no
guarantees, no invented experience. The first three are regex-friendly; "invented experience" is not, so I
gave a small model the draft and asked it to flag violations.

It deleted true claims. Shown "I built a support-ticket assistant that cut response time by 38%", with no
access to my portfolio, it reasonably flagged an unverifiable boast as possible fabrication, and the guard
removed the best sentence in the letter. The model wasn't wrong given what it could see; the design was.
Fabrication is a question about evidence, so only the component that holds the evidence (the verifier)
should judge it. The compliance model now only looks for what text alone can show: "ping me on the green
app", "we can settle payment privately", "I promise first-page rankings".

## 4. Learning from winning proposals made retrieval worse

Retrieval decides which evidence the writer sees. I built ten variants on a deliberately messy synthetic
corpus: each project described three ways, skills implied rather than named, code that reveals what a terse
README hides. Then I measured all ten on 600 labelled jobs (`rag_variants.json`).

The intuitive idea, boosting evidence from past proposals that won or got replies, was the worst variant:
Recall@5 fell from 0.776 for plain dense retrieval to 0.694. A handful of popular projects appear in many
winning proposals, so the boost pushed them up regardless of what the job asked for. Grouping a project's
chunks together (multi-vector) also hurt (0.686).

What helped was unglamorous. Split the job into its individual requirements and retrieve for each one. Add
BM25, because embeddings blur exact tool names like "Celery" or "dbt". Add a small skill graph that knows
which projects used which tools for which industries. Prefix chunks with a context line built from
metadata. Together: Recall@5 0.880, nDCG@10 0.862, under 1 second p95, no LLM call per query. My
pre-registered hypothesis (requirement decomposition plus hybrid retrieval would add at least 5 points on
multi-requirement jobs) missed by a hair: +4.8. I'm reporting it as not supported.

And then I didn't ship the winner. The agent that scores fit turns retrieval similarity into "strong",
"partial" or "no" evidence for each requirement, so retrieval quietly drives the bid-or-skip decision too.
With everything else fixed, swapping in the best-ranked pipeline lowered decision F1 from 0.941 to 0.931,
because the context lines shift similarity scores and the thresholds had been tuned on the plain index.
The runner-up (nDCG 0.848, without context lines) ships. Better retrieval by its own metric made the
product worse, and only an end-to-end run with one variable changed could show it.

## What I'd tell someone building an agent system

**Give the model the jobs where language is the bottleneck.** In GigBid that's writing the proposal,
turning a vague post into requirements, and replying to clients. Scouting, fit scoring, pricing and the
bid decision run with no LLM at all, which is also why a skipped scam costs almost nothing.

**Wrap every model with a check that can be measured on its own.** The verifier, the compliance rules and
the decision thresholds each have their own evaluation on the same items. That's how the scam-precision drop
showed up as a number instead of a vague feeling that "the risk agent is a bit jumpy".

**Measure components in isolation, on identical inputs.** The comparison that changed my design was the
same 30 jobs run twice, once with model flags trusted and once with them gated. End-to-end metrics would
have hidden it; a reply rate on 12 proposals can't tell you which of nine agents is misbehaving.

**Read the rejects.** The verifier's false positives (dates in metadata) and the compliance model's
deletions were both found by reading what the system threw away, not what it kept.

## Limits

The corpus and the clients are synthetic: my simulator's clients reward specific results, a must-have skill
and a question, so reply rates measure fit to that model rather than to real people. LLM experiments ran on
small samples because of the free tier, and each sample size is stated in the results files. The code,
the data generator, the evaluation runners and every number in this post are in the repository.

*GigBid: LangGraph, MCP, FastAPI, React; open-weight models (gpt-oss-120b / 20b) on Groq; Qdrant, BM25 and
a skill graph for retrieval. Repo and live demo: <links>.*

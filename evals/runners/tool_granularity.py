"""R&D question A: does tool granularity change agent behaviour?

    python -m evals.runners.tool_granularity

40 tasks with known correct calls x 3 tool designs:
  fine   - 27 narrow tools (one per field / per evidence type)
  coarse - 3 action-dispatch tools (marketplace_read, marketplace_write, portfolio)
  ours   - GigBid's 21 MCP tools with the descriptions shipped in the servers (loaded live via MCP)
One tool-choice call per task (model = the cheap `analyst` model, temperature 0, nothing executes).
Metrics: tool-selection accuracy, argument accuracy (expected key args present and matching), tokens/task.
Hypothesis (pre-registered): `ours` beats `coarse` on argument accuracy (typed schemas instead of a free
`params` dict) and beats `fine` on selection accuracy (fewer near-duplicate choices), at fewer tokens than `fine`.
"""

from __future__ import annotations

import asyncio
import os

os.environ.update({"GIGBID_STRICT_LLM": "1", "MCP_INPROCESS": "1"})

from evals.runners.common import RawLog, is_quota_error, mean, write_result  # noqa: E402

S = {"type": "string"}
N = {"type": "number"}
SL = {"type": "array", "items": {"type": "string"}}


def fn(name, desc, props, req=()):
    return {"type": "function", "function": {"name": name, "description": desc,
                                             "parameters": {"type": "object", "properties": props, "required": list(req)}}}


FINE = [
    fn("search_jobs_by_keyword", "Search open jobs by free-text keyword.", {"query": S}, ["query"]),
    fn("search_jobs_by_skill", "Search open jobs requiring given skills.", {"skills": SL}, ["skills"]),
    fn("search_jobs_by_budget", "Search open jobs with budget at least min_budget USD.", {"min_budget": N}, ["min_budget"]),
    fn("search_jobs_by_category", "Search open jobs in a category.", {"category": S}, ["category"]),
    fn("get_job_title", "Title of a job.", {"job_id": S}, ["job_id"]),
    fn("get_job_description", "Description text of a job.", {"job_id": S}, ["job_id"]),
    fn("get_job_budget", "Budget of a job.", {"job_id": S}, ["job_id"]),
    fn("get_job_screening_questions", "Screening questions of a job.", {"job_id": S}, ["job_id"]),
    fn("get_client_rating", "Average rating a client gives.", {"client_id": S}, ["client_id"]),
    fn("get_client_spend", "Total money a client has spent.", {"client_id": S}, ["client_id"]),
    fn("get_client_payment_status", "Whether a client's payment method is verified.", {"client_id": S}, ["client_id"]),
    fn("get_client_hires", "How many freelancers a client hired.", {"client_id": S}, ["client_id"]),
    fn("get_connects", "Connects balance.", {}),
    fn("get_policy_rules", "Platform submission rules.", {}),
    fn("get_policy_fees", "Platform Connects fees.", {}),
    fn("get_price_stats", "Historical prices for a category.", {"category": S}, ["category"]),
    fn("search_case_studies", "Search case studies.", {"query": S}, ["query"]),
    fn("search_code", "Search code files and READMEs.", {"query": S}, ["query"]),
    fn("search_reviews", "Search client reviews.", {"query": S}, ["query"]),
    fn("search_past_proposals", "Search past proposals (with outcomes).", {"query": S, "outcome": S}, ["query"]),
    fn("get_evidence", "Full text of an evidence item.", {"evidence_id": S}, ["evidence_id"]),
    fn("list_my_skills", "Skills in the portfolio.", {}),
    fn("find_projects_by_skill_and_industry", "Projects using a skill for an industry.", {"skill": S, "industry": S}),
    fn("create_draft", "Create a proposal draft.", {"job_id": S, "cover_letter": S, "bid_amount": N}, ["job_id", "cover_letter", "bid_amount"]),
    fn("submit_draft", "Submit a proposal draft.", {"proposal_id": S}, ["proposal_id"]),
    fn("send_client_message", "Send a message in a thread.", {"thread_id": S, "text": S}, ["thread_id", "text"]),
    fn("list_threads", "List client threads.", {}),
]
COARSE = [
    fn("marketplace_read", "Read from the marketplace. action: search_jobs|get_job|get_client|get_connects|get_policy|get_stats|list_messages|get_events",
       {"action": S, "params": {"type": "object"}}, ["action"]),
    fn("marketplace_write", "Write to the marketplace. action: create_draft|submit|send_message", {"action": S, "params": {"type": "object"}}, ["action"]),
    fn("portfolio", "Query the portfolio. action: search|get_item|list_skills|find_projects", {"action": S, "params": {"type": "object"}}, ["action"]),
]

# (request, {design: (tool, {arg: expected substring})})
TASKS = [
    ("Find open jobs that mention Celery.", {"fine": ("search_jobs_by_keyword", {"query": "celery"}), "coarse": ("marketplace_read", {"action": "search_jobs"}), "ours": ("search_jobs", {"query": "celery"})}),
    ("Show me jobs needing dbt and Snowflake.", {"fine": ("search_jobs_by_skill", {"skills": "dbt"}), "coarse": ("marketplace_read", {"action": "search_jobs"}), "ours": ("search_jobs", {"skills": "dbt"})}),
    ("Any jobs paying at least $2000?", {"fine": ("search_jobs_by_budget", {"min_budget": "2000"}), "coarse": ("marketplace_read", {"action": "search_jobs"}), "ours": ("search_jobs", {"min_budget": "2000"})}),
    ("List open jobs in the Computer vision category.", {"fine": ("search_jobs_by_category", {"category": "computer vision"}), "coarse": ("marketplace_read", {"action": "search_jobs"}), "ours": ("search_jobs", {"category": "computer vision"})}),
    ("What exactly does job j-ai-0042 ask for?", {"fine": ("get_job_description", {"job_id": "j-ai-0042"}), "coarse": ("marketplace_read", {"action": "get_job"}), "ours": ("get_job", {"job_id": "j-ai-0042"})}),
    ("What's the budget on job j-fu-0300?", {"fine": ("get_job_budget", {"job_id": "j-fu-0300"}), "coarse": ("marketplace_read", {"action": "get_job"}), "ours": ("get_job", {"job_id": "j-fu-0300"})}),
    ("Which screening questions does j-da-0450 have?", {"fine": ("get_job_screening_questions", {"job_id": "j-da-0450"}), "coarse": ("marketplace_read", {"action": "get_job"}), "ours": ("get_job", {"job_id": "j-da-0450"})}),
    ("Is client cl-0062 payment verified?", {"fine": ("get_client_payment_status", {"client_id": "cl-0062"}), "coarse": ("marketplace_read", {"action": "get_client"}), "ours": ("get_client_history", {"client_id": "cl-0062"})}),
    ("How much has client cl-0168 spent on the platform?", {"fine": ("get_client_spend", {"client_id": "cl-0168"}), "coarse": ("marketplace_read", {"action": "get_client"}), "ours": ("get_client_history", {"client_id": "cl-0168"})}),
    ("What rating does client cl-0011 usually give freelancers?", {"fine": ("get_client_rating", {"client_id": "cl-0011"}), "coarse": ("marketplace_read", {"action": "get_client"}), "ours": ("get_client_history", {"client_id": "cl-0011"})}),
    ("Has cl-0099 ever hired anyone?", {"fine": ("get_client_hires", {"client_id": "cl-0099"}), "coarse": ("marketplace_read", {"action": "get_client"}), "ours": ("get_client_history", {"client_id": "cl-0099"})}),
    ("How many Connects do I have left?", {"fine": ("get_connects", {}), "coarse": ("marketplace_read", {"action": "get_connects"}), "ours": ("get_connects_balance", {})}),
    ("What are the current platform rules for proposals?", {"fine": ("get_policy_rules", {}), "coarse": ("marketplace_read", {"action": "get_policy"}), "ours": ("get_policy", {})}),
    ("Did the platform change Connects fees recently?", {"fine": ("get_policy_fees", {}), "coarse": ("marketplace_read", {"action": "get_policy"}), "ours": ("get_policy", {})}),
    ("What do Dashboards & BI jobs usually pay?", {"fine": ("get_price_stats", {"category": "dashboards"}), "coarse": ("marketplace_read", {"action": "get_stats"}), "ours": ("get_market_stats", {"category": "dashboards"})}),
    ("Find my evidence of building RAG chatbots.", {"fine": ("search_case_studies", {"query": "rag"}), "coarse": ("portfolio", {"action": "search"}), "ours": ("search_evidence", {"requirement": "rag"})}),
    ("Do I have code that uses Qdrant?", {"fine": ("search_code", {"query": "qdrant"}), "coarse": ("portfolio", {"action": "search"}), "ours": ("search_evidence", {"requirement": "qdrant"})}),
    ("What did clients say about my churn model work?", {"fine": ("search_reviews", {"query": "churn"}), "coarse": ("portfolio", {"action": "search"}), "ours": ("search_evidence", {"requirement": "churn"})}),
    ("Show past proposals about dashboards that won.", {"fine": ("search_past_proposals", {"query": "dashboard"}), "coarse": ("portfolio", {"action": "search"}), "ours": ("search_evidence", {"requirement": "dashboard"})}),
    ("Open the full case study ai_ml-cs-telco-churn.", {"fine": ("get_evidence", {"evidence_id": "ai_ml-cs-telco-churn"}), "coarse": ("portfolio", {"action": "get_item"}), "ours": ("get_case_study", {"id": "ai_ml-cs-telco-churn"})}),
    ("Which skills can I prove from my portfolio?", {"fine": ("list_my_skills", {}), "coarse": ("portfolio", {"action": "list_skills"}), "ours": ("list_skills", {})}),
    ("Have I used XGBoost for an insurance client?", {"fine": ("find_projects_by_skill_and_industry", {"skill": "xgboost", "industry": "insurance"}), "coarse": ("portfolio", {"action": "find_projects"}), "ours": ("find_projects", {"skill": "xgboost", "industry": "insurance"})}),
    ("Which projects did I do for healthcare clients?", {"fine": ("find_projects_by_skill_and_industry", {"industry": "healthcare"}), "coarse": ("portfolio", {"action": "find_projects"}), "ours": ("find_projects", {"industry": "healthcare"})}),
    ("Map every requirement of this job to my portfolio: 'Need Airflow pipelines and pandas cleaning'.", {"fine": ("search_case_studies", {"query": "airflow"}), "coarse": ("portfolio", {"action": "search"}), "ours": ("match_job_requirements", {"job_description": "airflow"})}),
    ("Show me my conversations with clients.", {"fine": ("list_threads", {}), "coarse": ("marketplace_read", {"action": "list_messages"}), "ours": ("list_messages", {})}),
    ("Read the thread t-p-abc123.", {"fine": ("list_threads", {}), "coarse": ("marketplace_read", {"action": "list_messages"}), "ours": ("list_messages", {"thread_id": "t-p-abc123"})}),
    ("Any updates on my submitted proposals since event 40?", {"fine": ("list_threads", {}), "coarse": ("marketplace_read", {"action": "get_events"}), "ours": ("get_events", {"since": "40"})}),
    ("Draft (don't send) a proposal for j-ai-0001 at $1500 with this letter: 'You need a support bot...'", {"fine": ("create_draft", {"job_id": "j-ai-0001", "bid_amount": "1500"}), "coarse": ("marketplace_write", {"action": "create_draft"}), "ours": ("create_proposal_draft", {"dry_run": "true"})}),
    ("Preview exactly what would be sent for job j-ai-0002 at $900 before I approve.", {"fine": ("create_draft", {"job_id": "j-ai-0002"}), "coarse": ("marketplace_write", {"action": "create_draft"}), "ours": ("create_proposal_draft", {"dry_run": "true"})}),
    ("I approved it: submit proposal p-1a2b3c with key k-approved-77.", {"fine": ("submit_draft", {"proposal_id": "p-1a2b3c"}), "coarse": ("marketplace_write", {"action": "submit"}), "ours": ("submit_proposal", {"proposal_id": "p-1a2b3c", "idempotency_key": "k-approved-77"})}),
    ("Reply 'Tuesday 3pm works' in thread t-p-xyz, idempotency key msg-key-0001.", {"fine": ("send_client_message", {"thread_id": "t-p-xyz"}), "coarse": ("marketplace_write", {"action": "send_message"}), "ours": ("send_message", {"thread_id": "t-p-xyz", "idempotency_key": "msg-key-0001"})}),
    ("Find recent jobs posted after 2026-11-01 about Next.js.", {"fine": ("search_jobs_by_keyword", {"query": "next.js"}), "coarse": ("marketplace_read", {"action": "search_jobs"}), "ours": ("search_jobs", {"posted_after": "2026-11-01"})}),
    ("Is the marketplace reachable right now?", {"fine": ("get_connects", {}), "coarse": ("marketplace_read", {"action": "get_connects"}), "ours": ("health", {})}),
    ("Look up my past proposals that got ignored about churn.", {"fine": ("search_past_proposals", {"outcome": "ignored"}), "coarse": ("portfolio", {"action": "search"}), "ours": ("search_evidence", {"requirement": "churn"})}),
    ("What evidence do I have for Stripe subscriptions?", {"fine": ("search_case_studies", {"query": "stripe"}), "coarse": ("portfolio", {"action": "search"}), "ours": ("search_evidence", {"requirement": "stripe"})}),
    ("Get the details of client cl-0200 before I bid.", {"fine": ("get_client_payment_status", {"client_id": "cl-0200"}), "coarse": ("marketplace_read", {"action": "get_client"}), "ours": ("get_client_history", {"client_id": "cl-0200"})}),
    ("Which of my projects used Power BI?", {"fine": ("find_projects_by_skill_and_industry", {"skill": "power bi"}), "coarse": ("portfolio", {"action": "find_projects"}), "ours": ("find_projects", {"skill": "power bi"})}),
    ("Find hourly-friendly jobs in Web apps above $500 budget.", {"fine": ("search_jobs_by_budget", {"min_budget": "500"}), "coarse": ("marketplace_read", {"action": "search_jobs"}), "ours": ("search_jobs", {"min_budget": "500"})}),
    ("Show job j-da-0401 in full.", {"fine": ("get_job_description", {"job_id": "j-da-0401"}), "coarse": ("marketplace_read", {"action": "get_job"}), "ours": ("get_job", {"job_id": "j-da-0401"})}),
    ("Read the past proposal fullstack-prop-012.", {"fine": ("get_evidence", {"evidence_id": "fullstack-prop-012"}), "coarse": ("portfolio", {"action": "get_item"}), "ours": ("get_case_study", {"id": "fullstack-prop-012"})}),
]
SYSTEM = "You are a freelancer's assistant. Call exactly one tool that fulfils the request. Do not answer in text."


async def ours_tools() -> list[dict]:
    from mcp.shared.memory import create_connected_server_and_client_session

    from agent.mcp_client import _servers

    out = []
    for srv in _servers().values():
        async with create_connected_server_and_client_session(srv._mcp_server) as s:
            for t in (await s.list_tools()).tools:
                out.append({"type": "function", "function": {"name": t.name, "description": t.description or "", "parameters": t.inputSchema}})
    return out


def arg_ok(got: dict, want: dict) -> bool:
    flat = {k: str(v).lower() for k, v in got.items()}
    if "params" in got and isinstance(got["params"], dict):
        flat |= {k: str(v).lower() for k, v in got["params"].items()}
    return all(any(str(w).lower() in flat.get(k, "") for _ in [0]) for k, w in want.items())


async def main():
    from agent.llm import UsageTracker, get_chat

    llm = get_chat("analyst", temperature=0)
    if llm is None:
        raise SystemExit("needs MODEL_PROFILE=open and GROQ_API_KEY")
    designs = {"fine": FINE, "coarse": COARSE, "ours": await ours_tools()}
    log = RawLog("tool_granularity")
    for name, tools in designs.items():
        bound = llm.bind_tools(tools, tool_choice="required") if hasattr(llm, "bind_tools") else llm
        for i, (req, exp) in enumerate(TASKS):
            key = f"{name}|{i}"
            if log.has(key):
                continue
            usage = UsageTracker()
            try:
                msg = await bound.ainvoke([("system", SYSTEM), ("user", req)], config={"callbacks": [usage]})
            except Exception as e:  # noqa: BLE001
                if is_quota_error(e) or "rate limit" in str(e).lower():
                    print("quota reached; progress saved")
                    return report(designs, log)
                log.add(key, {"design": name, "task": i, "tool": None, "args": {}, "error": str(e)[:200], "tokens": 0,
                              "tool_ok": False, "args_ok": False})
                continue
            calls = getattr(msg, "tool_calls", []) or []
            tool, args = (calls[0]["name"], calls[0]["args"]) if calls else (None, {})
            want_tool, want_args = exp[name]
            log.add(key, {"design": name, "task": i, "tool": tool, "args": args, "tokens": usage.total_tokens(),
                          "tool_ok": tool == want_tool, "args_ok": tool == want_tool and arg_ok(args, want_args)})
    report(designs, log)


def report(designs, log):
    recs = log.values()
    res = {n: {"n_tools": len(t), "n_tasks": sum(r["design"] == n for r in recs),
               "tool_selection_accuracy": mean([r["tool_ok"] for r in recs if r["design"] == n]),
               "argument_accuracy": mean([r["args_ok"] for r in recs if r["design"] == n]),
               "tokens_per_task": mean([r["tokens"] for r in recs if r["design"] == n])} for n, t in designs.items()}
    misses = [{"design": r["design"], "task": TASKS[r["task"]][0], "chose": r["tool"], "expected": TASKS[r["task"]][1][r["design"]][0]}
              for r in recs if not r["tool_ok"]][:30]
    out = write_result("tool_granularity", {"model": "analyst model (see agent/config.yaml)", "n_tasks": len(TASKS),
                                            "complete": len(recs) == len(TASKS) * len(designs), "results": res, "misses": misses})
    print(out, res)


if __name__ == "__main__":
    asyncio.run(main())

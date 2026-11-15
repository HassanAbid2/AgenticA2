"""R&D question C: is the multi-agent design worth it?

    python -m evals.runners.multiagent_compare [--n 3]

Same jobs, three systems:
  (a) react      - one prebuilt ReAct agent holding all read tools (marketplace + portfolio)
  (b) supervisor - langgraph-supervisor with a researcher and a writer agent
  (c) graph      - GigBid's hand-built bid graph
All three are scored identically: bid-or-skip vs gold, unsupported claims (our verifier against the same
evidence pool for the job), compliance violations left in the final text, GigSim reply when they bid,
tokens and latency. Resumable across days on the free tier.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time

os.environ.update({"GIGBID_STRICT_LLM": "1"})
for k, v in {"MCP_INPROCESS": "1", "GIGSIM_INPROCESS": "1", "GIGSIM_ERROR_RATE": "0", "GIGSIM_RATE_LIMIT_PER_MIN": "100000",
             "MARKETPLACE_RPM": "100000", "GIGSIM_TIME_SCALE": "1000", "DATABASE_URL": "sqlite:///var/macompare.db",
             "CHECKPOINT_DB": "var/macompare_cp.db", "MEMORY_DB": "var/macompare_mem.db"}.items():
    os.environ.setdefault(k, v)

from evals.runners.common import RawLog, is_quota_error, load_dev, mean, pct, sample, write_result  # noqa: E402


def parse_final(text: str) -> dict:
    try:
        from agent.llm import _json_from

        d = _json_from(text)
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {"decision": "bid" if re.search(r"\bbid\b", text, re.I) else "skip", "cover_letter": ""}


async def evidence_pool(persona: str, job: dict) -> list[dict]:
    from agent.mcp_client import MCPHub

    r = await MCPHub(persona, "").call("fit_matcher", "match_job_requirements",
                                       {"job_title": job["title"], "job_description": job["description"], "requirements": [], "k": 12})
    return [{"evidence_id": i["evidence_id"], "text": i["snippet"], "skills": i["skills"]} for i in r["ranked"]]


async def run_react(persona, job, usage):
    from langgraph.prebuilt import create_react_agent

    from agent.config import settings
    from agent.llm import get_chat, render
    from agent.mcp_client import MCPHub
    from agent.runner import persona_profile

    p = persona_profile(persona)
    tools = await MCPHub(persona, "").langchain_tools(set(settings()["agents"]["baseline"]))
    agent = create_react_agent(get_chat("baseline"), tools, prompt=render("baseline_react", freelancer_name=p["name"], headline=p["headline"])[0])
    out = await agent.ainvoke({"messages": [("user", f"Job {job['job_id']}:\n{job['title']}\n{job['description']}\nScreening: {job.get('screening_questions')}")]},
                              config={"callbacks": [usage], "recursion_limit": 25})
    return parse_final(out["messages"][-1].content)


async def run_supervisor(persona, job, usage):
    from langgraph.prebuilt import create_react_agent
    from langgraph_supervisor import create_supervisor

    from agent.config import settings
    from agent.llm import get_chat, render
    from agent.mcp_client import MCPHub
    from agent.runner import persona_profile

    p = persona_profile(persona)
    tools = await MCPHub(persona, "").langchain_tools(set(settings()["agents"]["baseline"]))
    model = get_chat("baseline")
    researcher = create_react_agent(model, tools, name="researcher", prompt=render("baseline_researcher", freelancer_name=p["name"])[0])
    writer = create_react_agent(model, [], name="writer", prompt=render("baseline_writer", freelancer_name=p["name"])[0])
    sup = create_supervisor([researcher, writer], model=model, prompt=render("baseline_supervisor")[0]).compile()
    out = await sup.ainvoke({"messages": [("user", f"Job {job['job_id']}:\n{job['title']}\n{job['description']}")]},
                            config={"callbacks": [usage], "recursion_limit": 40})
    return parse_final(out["messages"][-1].content)


async def run_graph(persona, job, usage):
    from agent.runner import persona_profile, run_bid

    o = await run_bid(persona, job["job_id"], profile=persona_profile(persona), thread_id=f"mac-{job['job_id']}-{int(time.time())}")
    for node, v in o["usage"].items():  # fold the graph's own tracker into this one
        d = usage.per_node[node]
        for k in d:
            d[k] += v.get(k, 0)
    st = o["state"]
    caught = len((st.get("compliance") or {}).get("violations", [])) + len((st.get("draft") or {}).get("removed_claims", []))
    return {"decision": st["decision"]["action"], "cover_letter": (o["interrupt"] or {}).get("final_text", ""),
            "price": (st.get("price") or {}).get("amount"), "violations_caught": caught}


async def score_one(system: str, row: dict) -> dict:
    from agent.llm import UsageTracker
    from agent.nodes.compliance import check_text
    from gigsim.app import W, fast_forward, outcomes
    from rag.verify import unsupported_rate, verify_claims

    W.reset()
    persona, job = row["persona"], row["job"]
    usage = UsageTracker()
    t0 = time.perf_counter()
    fn = {"react": run_react, "supervisor": run_supervisor, "graph": run_graph}[system]
    out = await fn(persona, job, usage)
    dt = time.perf_counter() - t0
    bid = str(out.get("decision", "")).lower() == "bid"
    letter = out.get("cover_letter") or ""
    rec = {"system": system, "persona": persona, "job_type": row["gold"]["job_type"], "gold_bid": row["gold"]["bid"],
           "bid": bid, "correct": bid == row["gold"]["bid"], "latency_s": dt, "tokens": usage.total_tokens(),
           "cost_usd": usage.total_cost(), "violations_caught": out.get("violations_caught", 0)}
    if bid and letter.strip():
        claims = verify_claims(letter, await evidence_pool(persona, job))
        _, viol, _ = check_text(letter)
        rec |= {"n_claims": len(claims), "unsupported_claims": sum(c.label == "unsupported" for c in claims),
                "unsupported_rate": unsupported_rate(claims), "violations_left": len(viol)}
        if len(letter) >= 50:
            import httpx

            from gigsim.app import app as gs

            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gs), base_url="http://g",
                                         headers={"Authorization": f"Bearer gigsim-dev-token-{persona}"}) as c:
                amt = float(out.get("price") or (job["budget"].get("max") or 500))
                d = (await c.post("/proposals/drafts", headers={"Idempotency-Key": f"mac-{system}-d"},
                                  json={"job_id": job["job_id"], "cover_letter": letter[:5000], "bid_amount": amt,
                                        "bid_type": job["budget"]["type"]})).json()
                s = await c.post(f"/proposals/{d.get('proposal_id')}/submit", headers={"Idempotency-Key": f"mac-{system}-s"})
                if s.status_code == 200:
                    fast_forward()
                    o = next((x for x in outcomes() if x["proposal_id"] == d["proposal_id"]), {})
                    rec["replied"] = bool(o.get("replied"))
                else:
                    rec["rejected_by_platform"] = s.json().get("detail", "")[:120]
                    rec["replied"] = False
    return rec


async def main(n: int):
    rows = sample(load_dev(), n)
    log = RawLog("multiagent_compare")
    for row in rows:
        for system in ("graph", "react", "supervisor"):
            key = f"{system}|{row['job']['job_id']}"
            if log.has(key):
                continue
            try:
                log.add(key, await score_one(system, row))
                print("done", key, flush=True)
            except Exception as e:  # noqa: BLE001
                if is_quota_error(e) or "rate limit" in str(e).lower():
                    print("quota reached; progress saved")
                    return report(rows, log)
                log.add(key, {"system": system, "persona": row["persona"], "job_type": row["gold"]["job_type"], "error": str(e)[:300],
                              "gold_bid": row["gold"]["bid"], "bid": False, "correct": False, "latency_s": 0, "tokens": 0, "cost_usd": 0})
    report(rows, log)


def report(rows, log):
    recs = log.values()
    res = {}
    for s in ("react", "supervisor", "graph"):
        rs = [r for r in recs if r["system"] == s]
        if not rs:
            continue
        bids = [r for r in rs if "n_claims" in r]
        res[s] = {"n": len(rs), "errors": sum("error" in r for r in rs), "bid_or_skip_accuracy": mean([r["correct"] for r in rs]),
                  "unsupported_claims_per_proposal": mean([r["unsupported_claims"] for r in bids]),
                  "unsupported_rate": mean([r["unsupported_rate"] for r in bids]),
                  "compliance_violations_left": mean([r["violations_left"] for r in bids]),
                  "violations_caught_by_system": sum(r.get("violations_caught", 0) for r in rs),
                  "gigsim_reply_rate": mean([r["replied"] for r in rs if "replied" in r]),
                  "mean_tokens": mean([r["tokens"] for r in rs]), "p95_latency_s": pct([r["latency_s"] for r in rs], .95),
                  "accuracy_by_job_type": {t: mean([r["correct"] for r in rs if r["job_type"] == t]) for t in sorted({r["job_type"] for r in rs})}}
    out = write_result("multiagent_compare", {"jobs": len(rows), "complete": all(log.has(f"{s}|{r['job']['job_id']}") for r in rows
                                                                                for s in ("graph", "react", "supervisor")), "results": res})
    print(out, json.dumps(res, indent=1)[:1500])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3, help="jobs per persona")
    asyncio.run(main(ap.parse_args().n))

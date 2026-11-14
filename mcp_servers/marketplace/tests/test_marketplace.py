

from contextlib import asynccontextmanager  # noqa: E402

from mcp.shared.memory import create_connected_server_and_client_session  # noqa: E402

from gigsim.app import W  # noqa: E402
from mcp_servers.common import INPROC_USER  # noqa: E402
from mcp_servers.marketplace.server import mcp  # noqa: E402
from shared.db import AuditLog, session  # noqa: E402

LETTER = ("You need a bot that replies to support tickets from your knowledge base. I built HelpDesk Copilot with "
          "LangChain and Qdrant, which cut first-response time by 38%. What does success look like for you?")


@asynccontextmanager
async def connect():
    # in-memory MCP client; the caller identity travels in a context var (no HTTP headers in memory)
    tok = INPROC_USER.set("ai_ml")
    try:
        async with create_connected_server_and_client_session(mcp._mcp_server) as c:
            yield c
    finally:
        INPROC_USER.reset(tok)


async def _first_job(c):
    return (await c.call_tool("search_jobs", {"limit": 3})).structuredContent["jobs"][0]


async def test_annotations():
    async with connect() as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
        assert tools["search_jobs"].annotations.readOnlyHint
        assert tools["submit_proposal"].annotations.destructiveHint and tools["submit_proposal"].annotations.idempotentHint
        assert not tools["create_proposal_draft"].annotations.readOnlyHint
        assert tools["create_proposal_draft"].outputSchema["properties"]["policy_issues"]


async def test_dry_run_has_no_side_effects_and_flags_policy():
    W.reset()
    async with connect() as c:
        job = await _first_job(c)
        bal = (await c.call_tool("get_connects_balance", {})).structuredContent["balance"]
        draft = {"job_id": job["job_id"], "cover_letter": LETTER + " Mail me: me@x.com", "bid_amount": 500, "bid_type": "fixed"}
        r = (await c.call_tool("create_proposal_draft", {"draft": draft, "idempotency_key": "dry-0001", "dry_run": True})).structuredContent
        assert r["dry_run"] and r["connects_cost"] == job["connects_cost"] and r["balance_after"] == bal - job["connects_cost"]
        assert any(i.startswith("P1") for i in r["policy_issues"])
        assert not (await c.call_tool("list_proposals", {})).structuredContent["proposals"]


async def test_idempotent_writes_spend_connects_once():
    W.reset()
    async with connect() as c:
        job = await _first_job(c)
        bal = (await c.call_tool("get_connects_balance", {})).structuredContent["balance"]
        draft = {"job_id": job["job_id"], "cover_letter": LETTER, "bid_amount": 500, "bid_type": "fixed"}
        d1 = (await c.call_tool("create_proposal_draft", {"draft": draft, "idempotency_key": "draft-key-1"})).structuredContent
        d2 = (await c.call_tool("create_proposal_draft", {"draft": draft, "idempotency_key": "draft-key-1"})).structuredContent
        pid = d1["result"]["proposal_id"]
        assert d2["idempotent_replay"] and d2["result"]["proposal_id"] == pid
        s1 = (await c.call_tool("submit_proposal", {"proposal_id": pid, "idempotency_key": "submit-key-1"})).structuredContent
        s2 = (await c.call_tool("submit_proposal", {"proposal_id": pid, "idempotency_key": "submit-key-1"})).structuredContent
        assert s1["result"]["status"] == "submitted" and s2["idempotent_replay"]
        assert (await c.call_tool("get_connects_balance", {})).structuredContent["balance"] == bal - job["connects_cost"]


async def test_degraded_mode_error_code_and_audit():
    W.reset()
    async with connect() as c:
        W.forced_down = True
        try:
            r = await c.call_tool("get_connects_balance", {})
            assert r.isError and "MARKETPLACE_UNAVAILABLE" in r.content[0].text
            h = (await c.call_tool("health", {})).structuredContent
            assert h["marketplace_ok"] is False
        finally:
            W.forced_down = False
    with session() as s:
        rows = s.query(AuditLog).filter_by(tool="get_connects_balance").all()
        assert any(r.status == "MARKETPLACE_UNAVAILABLE" for r in rows)


async def test_invalid_input_rejected_by_schema():
    async with connect() as c:
        r = await c.call_tool("create_proposal_draft", {"draft": {"job_id": "x", "cover_letter": "short", "bid_amount": -1,
                                                                  "bid_type": "fixed"}, "idempotency_key": "k"})
        assert r.isError

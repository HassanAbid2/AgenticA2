import os
from datetime import date, timedelta

os.environ["MCP_DEFAULT_USER"] = "ws-test-user"

from mcp.shared.memory import create_connected_server_and_client_session  # noqa: E402

from mcp_servers.workspace.server import mcp  # noqa: E402


def connect():
    return create_connected_server_and_client_session(mcp._mcp_server)


async def test_slots_skip_holds_and_are_idempotent():
    start = (date.today() + timedelta(days=7 - date.today().weekday())).isoformat()  # next Monday
    async with connect() as c:
        slots = (await c.call_tool("free_slots", {"start_date": start, "days": 1})).structuredContent["slots"]
        assert slots
        first = slots[0]["start"]
        h1 = (await c.call_tool("create_interview_hold", {"start": first, "title": "Call", "idempotency_key": "hold-key-1"})).structuredContent
        h2 = (await c.call_tool("create_interview_hold", {"start": first, "title": "Call", "idempotency_key": "hold-key-1"})).structuredContent
        assert h2["idempotent_replay"] and h1["hold_id"] == h2["hold_id"]
        again = (await c.call_tool("free_slots", {"start_date": start, "days": 1})).structuredContent["slots"]
        assert first not in [s["start"] for s in again]


async def test_email_is_draft_only():
    async with connect() as c:
        names = {t.name for t in (await c.list_tools()).tools}
        assert "send_email" not in names
        d = (await c.call_tool("create_email_draft", {"to": "client@example.com", "subject": "Hi", "body": "Draft",
                                                      "idempotency_key": "draft-key-1"})).structuredContent
        assert d["draft_id"] > 0

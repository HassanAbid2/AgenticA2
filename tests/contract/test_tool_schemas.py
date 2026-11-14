"""Schema snapshot: fails CI when any MCP tool signature changes unintentionally.

Intentional change: UPDATE_SNAPSHOTS=1 pytest tests/contract && commit the new snapshot."""

import json
import os
from pathlib import Path

from mcp.shared.memory import create_connected_server_and_client_session

SNAP = Path(__file__).parent / "snapshots" / "tools.json"


async def current_schemas() -> dict:
    from mcp_servers.marketplace.server import mcp as market
    from mcp_servers.portfolio.server import mcp as portfolio
    from mcp_servers.workspace.server import mcp as workspace

    out = {}
    for name, srv in (("portfolio", portfolio), ("marketplace", market), ("workspace", workspace)):
        async with create_connected_server_and_client_session(srv._mcp_server) as c:
            for t in (await c.list_tools()).tools:
                out[f"{name}.{t.name}"] = {"input": t.inputSchema, "output": t.outputSchema,
                                           "annotations": t.annotations.model_dump(exclude_none=True) if t.annotations else {}}
    return out


async def test_tool_schemas_match_snapshot():
    cur = await current_schemas()
    if os.getenv("UPDATE_SNAPSHOTS") == "1" or not SNAP.exists():
        SNAP.parent.mkdir(exist_ok=True)
        SNAP.write_text(json.dumps(cur, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    snap = json.loads(SNAP.read_text(encoding="utf-8"))
    changed = sorted(k for k in set(cur) | set(snap) if cur.get(k) != snap.get(k))
    assert not changed, f"MCP tool signatures changed: {changed}. If intentional, run UPDATE_SNAPSHOTS=1."

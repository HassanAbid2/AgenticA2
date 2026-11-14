"""MCP client setup (MultiServerMCPClient) + per-agent tool allowlists (A6).

Agents never touch GigSim, Upwork, the DB or files: every capability is an MCP tool call made here.
- Allowlists come from agent/config.yaml -> agents; a node calling a tool outside its list fails.
- Every call has a timeout and bounded retries with backoff (connection errors / timeouts only).
- Errors are mapped to typed exceptions; a dead marketplace server becomes MarketplaceUnavailable,
  which the graph turns into the visible degraded mode.
- Each call is recorded (masked) for the execution trace, and carries the user's service token and
  the run's trace id as HTTP headers so the server-side audit log joins up with the trace.

Transport: Streamable HTTP to the three servers (docker compose / production), or in-process memory
sessions to the same FastMCP servers when MCP_INPROCESS=1 (tests, single-process dev).
"""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from functools import lru_cache

from agent.config import settings
from mcp_servers.common import INPROC_TRACE, INPROC_USER
from shared.security import mask_pii, service_token

SERVERS = ("portfolio", "marketplace", "workspace")


class ToolCallError(Exception):
    pass


class ToolNotAllowed(ToolCallError):
    pass


class MarketplaceUnavailable(ToolCallError):
    pass


class MarketplaceRejected(ToolCallError):
    pass


def urls() -> dict[str, str]:
    return {"portfolio": os.getenv("PORTFOLIO_MCP_URL", "http://localhost:8101/mcp"),
            "marketplace": os.getenv("MARKETPLACE_MCP_URL", "http://localhost:8102/mcp"),
            "workspace": os.getenv("WORKSPACE_MCP_URL", "http://localhost:8103/mcp")}


def inprocess() -> bool:
    return os.getenv("MCP_INPROCESS") == "1"


@lru_cache
def _servers():
    from mcp_servers.marketplace.server import mcp as m
    from mcp_servers.portfolio.server import mcp as p
    from mcp_servers.workspace.server import mcp as w

    return {"portfolio": p, "marketplace": m, "workspace": w}


@lru_cache
def tool_server_map() -> dict[str, str]:
    """tool name -> server, from the contract snapshot (the same source CI checks)."""
    import json
    from pathlib import Path

    snap = json.loads((Path(__file__).resolve().parents[1] / "tests/contract/snapshots/tools.json").read_text(encoding="utf-8"))
    return {k.split(".", 1)[1]: k.split(".", 1)[0] for k in snap}


def allowlist(node: str) -> set[str]:
    return set(settings()["agents"].get(node, []))


class MCPHub:
    """One per graph run: identity, trace id, call records."""

    def __init__(self, user_id: str, trace_id: str = "", timeout: float | None = None, retries: int = 2):
        self.user_id, self.trace_id = str(user_id), trace_id
        self.timeout = timeout or float(settings()["marketplace"]["timeout_s"]) * 3
        self.retries = retries
        self.records: list[dict] = []

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {service_token(self.user_id)}", "X-Trace-Id": self.trace_id}

    def client(self):
        from langchain_mcp_adapters.client import MultiServerMCPClient

        return MultiServerMCPClient({s: {"transport": "streamable_http", "url": u, "headers": self.headers(),
                                         "timeout": __import__("datetime").timedelta(seconds=self.timeout)}
                                     for s, u in urls().items()})

    @asynccontextmanager
    async def session(self, server: str):
        if inprocess():
            from mcp.shared.memory import create_connected_server_and_client_session

            tok_u, tok_t = INPROC_USER.set(self.user_id), INPROC_TRACE.set(self.trace_id)
            try:
                async with create_connected_server_and_client_session(_servers()[server]._mcp_server) as s:
                    yield s
            finally:
                INPROC_USER.reset(tok_u)
                INPROC_TRACE.reset(tok_t)
        else:
            async with self.client().session(server) as s:
                yield s

    async def call(self, node: str, tool: str, args: dict | None = None) -> dict:
        args = args or {}
        if tool not in allowlist(node):
            raise ToolNotAllowed(f"agent '{node}' is not allowed to call '{tool}' (see agent/config.yaml -> agents)")
        server = tool_server_map().get(tool)
        if not server:
            raise ToolCallError(f"unknown tool {tool}")
        delay, t0, err = 0.5, time.perf_counter(), None
        for attempt in range(self.retries + 1):
            try:
                async with asyncio.timeout(self.timeout):
                    async with self.session(server) as s:
                        res = await s.call_tool(tool, args)
                break
            except (TimeoutError, OSError, ConnectionError) as e:
                err = e
            except BaseException as e:  # noqa: BLE001 - anyio wraps transport failures in ExceptionGroups
                if isinstance(e, asyncio.CancelledError):
                    raise
                err = e
            if attempt < self.retries:
                await asyncio.sleep(delay)
                delay *= 2
        else:
            self._record(node, server, tool, args, None, f"unreachable: {type(err).__name__}", t0)
            if server == "marketplace":
                raise MarketplaceUnavailable(f"marketplace MCP server unreachable ({type(err).__name__})")
            raise ToolCallError(f"{server} MCP server unreachable ({type(err).__name__})")
        if res.isError:
            msg = " ".join(getattr(c, "text", "") for c in res.content)
            self._record(node, server, tool, args, None, msg[:300], t0)
            if "MARKETPLACE_UNAVAILABLE" in msg:
                raise MarketplaceUnavailable(msg)
            if "MARKETPLACE_REJECTED" in msg:
                raise MarketplaceRejected(msg)
            raise ToolCallError(f"{tool}: {msg[:500]}")
        out = res.structuredContent or {}
        if "result" in out and len(out) == 1 and not isinstance(out["result"], dict):
            out = out["result"]
        self._record(node, server, tool, args, out, None, t0)
        return out

    def _record(self, node, server, tool, args, out, error, t0):
        summary = None
        if isinstance(out, dict):
            summary = {k: (f"<{len(v)} items>" if isinstance(v, list) else v) for k, v in list(out.items())[:8]
                       if not isinstance(v, dict | str) or len(str(v)) < 200}
        self.records.append(mask_pii({"node": node, "server": server, "tool": tool, "args": args, "result": summary,
                                      "error": error, "ms": round((time.perf_counter() - t0) * 1000), "trace_id": self.trace_id}))

    def drain(self) -> list[dict]:
        out, self.records = self.records, []
        return out

    async def langchain_tools(self, names: set[str] | None = None):
        """LangChain tool objects (for the ReAct / supervisor baselines in R&D C)."""

        tools = []
        if inprocess():
            # in-process baselines get adapter tools bound to a fresh memory session per call
            from langchain_core.tools import StructuredTool

            for server in SERVERS:
                async with self.session(server) as s:
                    listed = (await s.list_tools()).tools
                for t in listed:
                    if names and t.name not in names:
                        continue

                    async def _run(_tool=t.name, **kw):
                        try:
                            return await self.call("baseline", _tool, kw)
                        except ToolCallError as e:
                            return {"error": str(e)}

                    tools.append(StructuredTool.from_function(coroutine=_run, name=t.name, description=t.description or "",
                                                              args_schema=t.inputSchema))
            return tools
        for server in SERVERS:
            for t in await self.client().get_tools(server_name=server):
                if not names or t.name in names:
                    tools.append(t)
        return tools

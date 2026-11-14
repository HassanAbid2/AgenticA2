"""Shared plumbing for GigBid's own MCP servers: bearer auth, caller identity, trace id, audit log,
per-user rate limiting and the HTTP runner."""

from __future__ import annotations

import asyncio
import os
import time
from collections import defaultdict, deque

from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import Context
from mcp.server.transport_security import TransportSecuritySettings

from shared.security import mask_pii, verify_service_token


class ServiceTokenVerifier(TokenVerifier):
    """Accepts "<user_id>.<hmac>" tokens minted by the API/worker for the user they act for."""

    async def verify_token(self, token: str) -> AccessToken | None:
        uid = verify_service_token(token)
        if uid is None:
            return None
        return AccessToken(token=token, client_id=uid, scopes=["gigbid"], expires_at=None)


def server_kwargs(port: int, require_auth: bool = True) -> dict:
    """Bearer auth on the streamable HTTP endpoint (stdio / in-memory use has no HTTP layer).
    DNS-rebinding protection is off because callers reach us by compose service name; the endpoint
    is never exposed publicly (only the API is)."""
    kw = {"host": "0.0.0.0", "port": port, "stateless_http": True,
          "transport_security": TransportSecuritySettings(enable_dns_rebinding_protection=False)}
    if require_auth:
        base = os.getenv("GIGBID_PUBLIC_API_URL", "http://localhost:8000")
        kw |= {"token_verifier": ServiceTokenVerifier(),
               "auth": AuthSettings(issuer_url=base, resource_server_url=f"http://localhost:{port}", required_scopes=["gigbid"])}
    return kw


def caller(ctx: Context | None) -> str:
    """User id of the caller: from the verified bearer token over HTTP, else the local default
    (stdio for Claude Desktop / Cursor, or in-memory tests)."""
    try:
        from mcp.server.auth.middleware.auth_context import get_access_token

        tok = get_access_token()
        if tok:
            return tok.client_id
    except Exception:  # noqa: BLE001
        pass
    return os.getenv("MCP_DEFAULT_USER", "local")


def trace_id(ctx: Context | None) -> str:
    try:
        req = ctx.request_context.request  # starlette Request over HTTP
        return req.headers.get("x-trace-id", "") if req is not None else ""
    except Exception:  # noqa: BLE001
        return ""


def audit(server: str, user: str, tool: str, args: dict, result, status: str, trace: str):
    """Append-only audit row. Arguments and results are PII-masked and truncated."""
    from shared.db import AuditLog, session

    res = result if isinstance(result, dict) else {"value": result}
    text = str(mask_pii(res))
    with session() as s:
        s.add(AuditLog(user_id=str(user), server=server, tool=tool, args=mask_pii(args), status=status,
                       result=mask_pii(res) if len(text) < 4000 else {"truncated": text[:4000]}, trace_id=trace or ""))


class RateLimiter:
    """Per-user sliding window, async-aware: callers wait instead of failing.
    ponytail: in-process; one marketplace server replica. Move to Redis if it is ever scaled out."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.calls: dict[str, deque] = defaultdict(deque)

    async def acquire(self, user: str):
        while True:
            now = time.monotonic()
            q = self.calls[user]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) < self.per_minute:
                q.append(now)
                return
            await asyncio.sleep(min(5.0, 60 - (now - q[0]) + 0.05))


def run(mcp, port: int):
    """stdio by default (Claude Desktop / Cursor); `--http` serves streamable HTTP on `port`."""
    import sys

    import uvicorn

    if "--http" in sys.argv:
        uvicorn.run(mcp.streamable_http_app(), host=os.getenv("MCP_HOST", "0.0.0.0"), port=port, log_level="warning")
    elif "--sse" in sys.argv:
        mcp.run("sse")
    else:
        mcp.run("stdio")

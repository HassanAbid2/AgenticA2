"""OAuth 2.1 (authorization code + PKCE, dynamic client registration) for the official Upwork MCP
server, following the MCP authorization spec:

  1. GET <mcp>/.well-known/oauth-protected-resource      -> authorization_servers[0]
  2. GET <as>/.well-known/oauth-authorization-server     -> endpoints
  3. POST registration_endpoint (RFC 7591) if no client id is configured
  4. redirect the user to authorization_endpoint with PKCE S256 + state + resource indicator
  5. exchange the code at token_endpoint; refresh later with the refresh token

Tokens are returned to the caller (the API), which stores them Fernet-encrypted per user and never logs
them. No browser automation, cookies or scraping are involved: the user signs in on Upwork's own page.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import time
from urllib.parse import urlencode, urljoin

import httpx

UPWORK_MCP_URL = os.getenv("UPWORK_MCP_URL", "https://mcp.upwork.com/mcp")


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


async def discover(client: httpx.AsyncClient, mcp_url: str = UPWORK_MCP_URL) -> dict:
    origin = mcp_url.split("/mcp")[0]
    prm = await client.get(urljoin(origin + "/", ".well-known/oauth-protected-resource"))
    prm.raise_for_status()
    as_url = prm.json()["authorization_servers"][0].rstrip("/")
    meta = await client.get(as_url + "/.well-known/oauth-authorization-server")
    meta.raise_for_status()
    return meta.json() | {"resource": prm.json().get("resource", mcp_url)}


async def register_client(client: httpx.AsyncClient, meta: dict, redirect_uri: str) -> dict:
    if os.getenv("UPWORK_CLIENT_ID"):
        return {"client_id": os.environ["UPWORK_CLIENT_ID"], "client_secret": os.getenv("UPWORK_CLIENT_SECRET")}
    r = await client.post(meta["registration_endpoint"], json={
        "client_name": "GigBid", "redirect_uris": [redirect_uri], "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"], "token_endpoint_auth_method": "none"})
    r.raise_for_status()
    return r.json()


async def start(redirect_uri: str, transport: httpx.AsyncBaseTransport | None = None) -> dict:
    """Returns {authorize_url, pending} - `pending` (verifier, state, client, endpoints) is stored
    server-side, encrypted, until the callback arrives."""
    async with httpx.AsyncClient(timeout=15, transport=transport) as c:
        meta = await discover(c)
        reg = await register_client(c, meta, redirect_uri)
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(24)
    params = {"response_type": "code", "client_id": reg["client_id"], "redirect_uri": redirect_uri, "state": state,
              "code_challenge": challenge, "code_challenge_method": "S256", "resource": meta["resource"]}
    if meta.get("scopes_supported"):
        params["scope"] = " ".join(meta["scopes_supported"])
    return {"authorize_url": f"{meta['authorization_endpoint']}?{urlencode(params)}",
            "pending": {"verifier": verifier, "state": state, "client": reg, "token_endpoint": meta["token_endpoint"],
                        "resource": meta["resource"], "redirect_uri": redirect_uri}}


async def exchange(pending: dict, code: str, state: str, transport: httpx.AsyncBaseTransport | None = None) -> dict:
    if not secrets.compare_digest(state, pending["state"]):
        raise ValueError("OAuth state mismatch")
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": pending["redirect_uri"],
            "client_id": pending["client"]["client_id"], "code_verifier": pending["verifier"], "resource": pending["resource"]}
    async with httpx.AsyncClient(timeout=15, transport=transport) as c:
        r = await c.post(pending["token_endpoint"], data=data)
        r.raise_for_status()
        tok = r.json()
    return _stamp(tok, pending)


async def refresh(tokens: dict, transport: httpx.AsyncBaseTransport | None = None) -> dict:
    data = {"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"],
            "client_id": tokens["client_id"], "resource": tokens.get("resource", UPWORK_MCP_URL)}
    async with httpx.AsyncClient(timeout=15, transport=transport) as c:
        r = await c.post(tokens["token_endpoint"], data=data)
        r.raise_for_status()
    return _stamp(r.json() | {"refresh_token": r.json().get("refresh_token", tokens["refresh_token"])}, tokens)


def _stamp(tok: dict, ctx: dict) -> dict:
    return tok | {"expires_at": time.time() + int(tok.get("expires_in", 3600)) - 60,
                  "client_id": ctx.get("client", {}).get("client_id", ctx.get("client_id")),
                  "token_endpoint": ctx["token_endpoint"], "resource": ctx.get("resource", UPWORK_MCP_URL)}

"""Encrypted per-user marketplace credentials (GigSim API token, Upwork OAuth tokens) and the Upwork
OAuth 2.1 connect flow. Tokens are Fernet-encrypted at rest, never returned by the API and never logged."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse

from apps.api.auth.users import current_user
from apps.api.schemas import AccountOut
from shared.db import KV, ConnectedAccount, User, session
from shared.security import decrypt_json, encrypt_json

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


def save_account(user_id: int, provider: str, secret: dict, meta: dict | None = None):
    with session() as db:
        acc = db.query(ConnectedAccount).filter_by(user_id=user_id, provider=provider).one_or_none()
        if acc:
            acc.enc_token, acc.meta = encrypt_json(secret), meta or acc.meta
        else:
            db.add(ConnectedAccount(user_id=user_id, provider=provider, enc_token=encrypt_json(secret), meta=meta or {}))


def load_account(user_id: int, provider: str) -> dict | None:
    with session() as db:
        acc = db.query(ConnectedAccount).filter_by(user_id=user_id, provider=provider).one_or_none()
        return decrypt_json(acc.enc_token) if acc else None


@router.get("", response_model=list[AccountOut])
def list_accounts(u: User = Depends(current_user)):
    with session() as db:
        accs = {a.provider: a for a in db.query(ConnectedAccount).filter_by(user_id=u.id)}
    return [AccountOut(provider=p, connected=p in accs, meta=(accs[p].meta if p in accs else {})) for p in ("gigsim", "upwork")]


@router.delete("/{provider}")
def disconnect(provider: str, u: User = Depends(current_user)) -> dict:
    with session() as db:
        n = db.query(ConnectedAccount).filter_by(user_id=u.id, provider=provider).delete()
    return {"deleted": n}


def _redirect_uri() -> str:
    return os.getenv("GIGBID_PUBLIC_API_URL", "http://localhost:8000").rstrip("/") + "/api/accounts/upwork/callback"


@router.get("/upwork/start")
async def upwork_start(u: User = Depends(current_user)) -> dict:
    """Begin OAuth with the official Upwork MCP server; the browser is sent to Upwork's own sign-in page."""
    from mcp_servers.marketplace.adapters import upwork_oauth

    try:
        r = await upwork_oauth.start(_redirect_uri())
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"could not reach Upwork authorization server: {type(e).__name__}") from e
    with session() as db:
        row = db.get(KV, (u.id, "upwork_oauth_pending"))
        val = {"enc": encrypt_json(r["pending"])}
        if row:
            row.value = val
        else:
            db.add(KV(user_id=u.id, key="upwork_oauth_pending", value=val))
    return {"authorize_url": r["authorize_url"]}


@router.get("/upwork/callback")
async def upwork_callback(code: str, state: str, u: User = Depends(current_user)):
    from mcp_servers.marketplace.adapters import upwork_oauth

    with session() as db:
        row = db.get(KV, (u.id, "upwork_oauth_pending"))
        if not row:
            raise HTTPException(400, "no pending Upwork authorization")
        pending = decrypt_json(row.value["enc"])
        db.delete(row)
    try:
        tokens = await upwork_oauth.exchange(pending, code, state)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    save_account(u.id, "upwork", tokens, {"scope": tokens.get("scope", ""), "connected": True})
    return RedirectResponse("/settings?upwork=connected")

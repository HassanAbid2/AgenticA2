"""Users and sessions: scrypt password hashes, opaque session tokens (only their SHA-256 is stored),
HttpOnly SameSite cookie. Every router depends on `current_user`, and every query filters by its id."""

from __future__ import annotations

import hashlib
import os
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response

from apps.api.schemas import LoginIn, SignupIn, UserOut
from shared.db import SessionToken, User, session
from shared.security import check_password, hash_password

COOKIE = "gigbid_session"
TTL = timedelta(days=7)
router = APIRouter(prefix="/api/auth", tags=["auth"])


def _h(tok: str) -> str:
    return hashlib.sha256(tok.encode()).hexdigest()


def start_session(resp: Response, user_id: int) -> str:
    tok = secrets.token_urlsafe(32)
    with session() as db:
        db.add(SessionToken(token_hash=_h(tok), user_id=user_id, expires_at=datetime.now(UTC) + TTL))
    resp.set_cookie(COOKIE, tok, httponly=True, samesite="lax", secure=os.getenv("COOKIE_SECURE", "0") == "1",
                    max_age=int(TTL.total_seconds()), path="/")
    return tok


def current_user(gigbid_session: str | None = Cookie(default=None)) -> User:
    if not gigbid_session:
        raise HTTPException(401, "not signed in")
    with session() as db:
        st = db.get(SessionToken, _h(gigbid_session))
        if not st or st.expires_at.replace(tzinfo=UTC) < datetime.now(UTC):
            raise HTTPException(401, "session expired")
        u = db.get(User, st.user_id)
        db.expunge(u)
        return u


def out(u: User) -> UserOut:
    return UserOut(id=u.id, email=u.email, name=u.name, persona=u.persona, onboarded=u.onboarded, settings=u.settings or {})


@router.post("/signup", response_model=UserOut)
def signup(body: SignupIn, resp: Response):
    with session() as db:
        if db.query(User).filter_by(email=body.email.lower()).first():
            raise HTTPException(409, "email already registered")
        u = User(email=body.email.lower(), name=body.name, password_hash=hash_password(body.password), settings={})
        db.add(u)
        db.flush()
        uid = u.id
    start_session(resp, uid)
    with session() as db:
        return out(db.get(User, uid))


@router.post("/login", response_model=UserOut)
def login(body: LoginIn, resp: Response):
    with session() as db:
        u = db.query(User).filter_by(email=body.email.lower()).first()
        if not u or not check_password(body.password, u.password_hash):
            raise HTTPException(401, "wrong email or password")
        uid = u.id
    start_session(resp, uid)
    with session() as db:
        return out(db.get(User, uid))


@router.post("/logout")
def logout(resp: Response, gigbid_session: str | None = Cookie(default=None)) -> dict:
    if gigbid_session:
        with session() as db:
            st = db.get(SessionToken, _h(gigbid_session))
            if st:
                db.delete(st)
    resp.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(u: User = Depends(current_user)):
    return out(u)

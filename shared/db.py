"""Relational store shared by the API, worker and MCP servers (Postgres in compose, SQLite locally).

Tenant rule: every table holding user data has `user_id`, and every query in the codebase goes
through helpers that filter on it. The audit log is append-only (no update/delete path exists in
code; Postgres additionally gets a trigger that rejects UPDATE/DELETE).
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

ROOT = Path(__file__).resolve().parents[1]


def now():
    return datetime.now(UTC)


def database_url() -> str:
    url = os.getenv("DATABASE_URL", "")
    if not url:
        (ROOT / "var").mkdir(exist_ok=True)
        url = f"sqlite:///{(ROOT / 'var' / 'gigbid.db').as_posix()}"
    return url


class Base(DeclarativeBase):
    type_annotation_map = {dict: JSON, list: JSON}


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    password_hash: Mapped[str] = mapped_column(String(300))
    persona: Mapped[str | None] = mapped_column(String(50), nullable=True)  # ai_ml | fullstack | data_analyst | own
    onboarded: Mapped[bool] = mapped_column(Boolean, default=False)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SessionToken(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConnectedAccount(Base):
    __tablename__ = "connected_accounts"
    __table_args__ = (UniqueConstraint("user_id", "provider"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    provider: Mapped[str] = mapped_column(String(30))  # gigsim | upwork
    enc_token: Mapped[str] = mapped_column(Text)  # Fernet-encrypted JSON (access/refresh tokens)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SavedSearch(Base):
    __tablename__ = "saved_searches"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    query: Mapped[str] = mapped_column(String(300), default="")
    skills: Mapped[list] = mapped_column(JSON, default=list)
    category: Mapped[str] = mapped_column(String(100), default="")
    min_budget: Mapped[float] = mapped_column(Float, default=0)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=180)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Job(Base):
    """The user's inbox: one row per (user, marketplace job)."""

    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("user_id", "job_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    job_id: Mapped[str] = mapped_column(String(80))
    dedup_key: Mapped[str] = mapped_column(String(64), index=True)
    duplicate_of: Mapped[str | None] = mapped_column(String(80), nullable=True)
    job: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="new")
    # new | queued | analysing | skipped | watch | awaiting_approval | approved | submitted | rejected
    # | needs_attention | dead_letter | marketplace_unavailable
    decision: Mapped[str | None] = mapped_column(String(10), nullable=True)
    fit_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_flags: Mapped[list] = mapped_column(JSON, default=list)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    connects_cost: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)  # analysis snapshot for the UI
    thread_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Proposal(Base):
    __tablename__ = "proposals"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    job_id: Mapped[str] = mapped_column(String(80))
    thread_id: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(30), default="drafted")
    # drafted | submitted | viewed | replied | interview | hired | lost | rejected | blocked
    draft: Mapped[dict] = mapped_column(JSON, default=dict)
    final_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    bid_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    marketplace_proposal_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    connects_spent: Mapped[int] = mapped_column(Integer, default=0)
    category: Mapped[str] = mapped_column(String(100), default="")
    strategy: Mapped[str] = mapped_column(String(40), default="default")  # X2 A/B arm
    cost_usd: Mapped[float] = mapped_column(Float, default=0)
    latency_s: Mapped[float] = mapped_column(Float, default=0)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    thread_id: Mapped[str] = mapped_column(String(120), index=True)
    graph: Mapped[str] = mapped_column(String(20))  # bid | conversation
    kind: Mapped[str] = mapped_column(String(20))  # proposal | message
    interrupt_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | approved | edited | rejected | resumed
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    diff: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("user_id", "marketplace_thread_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    marketplace_thread_id: Mapped[str] = mapped_column(String(120))
    job_id: Mapped[str] = mapped_column(String(80))
    proposal_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    messages: Mapped[list] = mapped_column(JSON, default=list)
    last_seen_message: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="open")
    intent: Mapped[str | None] = mapped_column(String(30), nullable=True)
    graph_thread_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    thread_id: Mapped[str] = mapped_column(String(160), index=True)
    graph: Mapped[str] = mapped_column(String(20))
    job_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="running")
    # running | interrupted | completed | failed | needs_attention | dead_letter
    trace_id: Mapped[str] = mapped_column(String(64))
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0)
    latency_s: Mapped[float] = mapped_column(Float, default=0)
    steps: Mapped[int] = mapped_column(Integer, default=0)
    per_node: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RunEvent(Base):
    __tablename__ = "run_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    node: Mapped[str] = mapped_column(String(60))
    kind: Mapped[str] = mapped_column(String(30))  # node_start | node_end | tool | interrupt | error | done
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuditLog(Base):
    """Append-only: user, server, tool, arguments, result, trace id."""

    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    user_id: Mapped[str] = mapped_column(String(80), index=True)
    server: Mapped[str] = mapped_column(String(40))
    tool: Mapped[str] = mapped_column(String(80))
    args: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20))
    trace_id: Mapped[str] = mapped_column(String(64), default="", index=True)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency"
    key: Mapped[str] = mapped_column(String(200), primary_key=True)  # user:tool:client_key
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class EditLog(Base):
    """Raw user edits to drafts: input to the style-memory promotion rule, never memory itself."""

    __tablename__ = "edit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    job_id: Mapped[str] = mapped_column(String(80))
    before: Mapped[str] = mapped_column(Text)
    after: Mapped[str] = mapped_column(Text)
    diff: Mapped[str] = mapped_column(Text)
    patterns: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CalendarHold(Base):
    __tablename__ = "calendar_holds"
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(80), index=True)
    start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    minutes: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    tentative: Mapped[bool] = mapped_column(Boolean, default=True)
    idempotency_key: Mapped[str] = mapped_column(String(120))


class EmailDraft(Base):
    __tablename__ = "email_drafts"
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(80), index=True)
    to: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class KV(Base):
    """Small per-user cursors (marketplace event seq, etc.)."""

    __tablename__ = "kv"
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)


@lru_cache
def engine():
    url = database_url()
    kw = {"connect_args": {"check_same_thread": False, "timeout": 30}} if url.startswith("sqlite") else {"pool_pre_ping": True}
    eng = create_engine(url, **kw)
    if url.startswith("sqlite"):
        @event.listens_for(eng, "connect")
        def _wal(dbapi_conn, _):  # concurrent API + worker + MCP processes
            dbapi_conn.execute("PRAGMA journal_mode=WAL")
            dbapi_conn.execute("PRAGMA busy_timeout=30000")
    Base.metadata.create_all(eng)
    if url.startswith("postgresql"):
        with eng.begin() as c:
            c.execute(text("""
                CREATE OR REPLACE FUNCTION audit_log_append_only() RETURNS trigger AS $$
                BEGIN RAISE EXCEPTION 'audit_log is append-only'; END; $$ LANGUAGE plpgsql;
                DROP TRIGGER IF EXISTS audit_log_no_update ON audit_log;
                CREATE TRIGGER audit_log_no_update BEFORE UPDATE OR DELETE ON audit_log
                FOR EACH ROW EXECUTE FUNCTION audit_log_append_only();"""))
    return eng


@lru_cache
def _factory():
    return sessionmaker(engine(), expire_on_commit=False)


@contextmanager
def session() -> Session:
    s = _factory()()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()

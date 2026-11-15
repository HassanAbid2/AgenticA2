"""LangGraph long-term memory store + checkpointer factories (Postgres in compose, SQLite locally).

Namespaces (C2):
  ("style", <user_id>)    style rules learned from the user's edits      -> promotion_rules.promote_style
  ("outcome", <user_id>)  per-category stats of what won / got replies   -> promotion_rules.promote_outcomes
Nothing else is ever written to the store; raw tool output stays in the execution trace.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from shared.db import ROOT, database_url

STYLE, OUTCOME = "style", "outcome"


def _pg_url() -> str | None:
    url = database_url()
    if url.startswith("postgresql"):
        return url.replace("postgresql+psycopg://", "postgresql://")
    return None


_setup_done: set[str] = set()
_setup_lock = asyncio.Lock()


async def _setup_once(name: str, obj) -> None:
    """Concurrent jobs racing on CREATE TABLE IF NOT EXISTS hit a Postgres unique violation on pg_type,
    so each process runs the migrations once, serialised."""
    if name in _setup_done:
        return
    async with _setup_lock:
        if name not in _setup_done:
            await obj.setup()
            _setup_done.add(name)


def _sqlite_path(name: str) -> str:
    p = os.getenv("CHECKPOINT_DB") if name == "checkpoints" else os.getenv("MEMORY_DB")
    if p:
        return p
    (ROOT / "var").mkdir(exist_ok=True)
    return str(ROOT / "var" / f"{name}.db")


@asynccontextmanager
async def open_checkpointer():
    if pg := _pg_url():
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        async with AsyncPostgresSaver.from_conn_string(pg) as cp:
            await _setup_once("pg_checkpointer", cp)
            yield cp
    else:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        async with AsyncSqliteSaver.from_conn_string(_sqlite_path("checkpoints")) as cp:
            yield cp


@asynccontextmanager
async def open_store():
    if pg := _pg_url():
        from langgraph.store.postgres.aio import AsyncPostgresStore

        async with AsyncPostgresStore.from_conn_string(pg) as st:
            await _setup_once("pg_store", st)
            yield st
    else:
        from langgraph.store.sqlite.aio import AsyncSqliteStore

        async with AsyncSqliteStore.from_conn_string(_sqlite_path("memory")) as st:
            await st.setup()
            yield st


@contextmanager
def open_store_sync():
    """For the API's memory viewer (list / delete)."""
    if pg := _pg_url():
        from langgraph.store.postgres import PostgresStore

        with PostgresStore.from_conn_string(pg) as st:
            st.setup()
            yield st
    else:
        from langgraph.store.sqlite import SqliteStore

        with SqliteStore.from_conn_string(_sqlite_path("memory")) as st:
            st.setup()
            yield st


async def load_memory(store, user_id: str, category: str | None) -> dict:
    style = [i.value for i in await store.asearch((STYLE, str(user_id)), limit=50)]
    outcome = None
    if category:
        item = await store.aget((OUTCOME, str(user_id)), category)
        outcome = item.value if item else None
    return {"style_rules": style, "outcome": outcome}


def memory_path_hint() -> Path:
    return Path(_sqlite_path("memory"))

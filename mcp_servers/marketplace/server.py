"""GigBid Marketplace MCP server: wraps GigSim (or live Upwork) behind typed read/write tools.

    python -m mcp_servers.marketplace.server --http     # streamable HTTP on :8102, bearer auth

Writes require an idempotency key (a retried call never submits twice or spends Connects twice) and
support dry_run (exactly what would be sent, what it costs, which platform rules it would break).
Every call is rate limited per user and written to the append-only audit log with the trace id.
"""

from __future__ import annotations

import os
import re
import sys
import time
from typing import Any, Literal

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from mcp_servers.common import RateLimiter, audit, caller, run, server_kwargs, trace_id
from mcp_servers.marketplace.adapters.base import (
    MarketplaceError,
    MarketplaceRejected,
    MarketplaceUnavailable,
)

PORT = int(os.getenv("MARKETPLACE_MCP_PORT", "8102"))
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
DRAFT = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True)
SUBMIT = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True)
SEND = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True)
IDEM = Field(min_length=8, max_length=120, pattern=r"^[A-Za-z0-9:_.-]+$",
             description="Client-generated key; the same key always returns the first result")


def _cfg():
    from agent.config import settings

    return settings()["marketplace"]


LIMITER = RateLimiter(int(os.getenv("MARKETPLACE_RPM", _cfg()["max_requests_per_minute"])))  # evals raise it for the local simulator


# ----------------------------------------------------------------------------- schemas
class Budget(BaseModel):
    type: Literal["fixed", "hourly"]
    min: float | None = None
    max: float | None = None
    currency: str = "USD"


class Job(BaseModel):
    job_id: str
    title: str
    description: str
    category: str = ""
    skills: list[str] = []
    budget: Budget
    duration_days: int | None = None
    hours_per_week: int | None = None
    screening_questions: list[str] = []
    client_id: str = ""
    posted_at: str = ""
    connects_cost: int = 0
    proposals_count: int = 0
    featured: bool = False


class JobList(BaseModel):
    jobs: list[Job]


class ClientHistory(BaseModel):
    client_id: str
    name: str = ""
    country: str = ""
    industry: str = ""
    payment_verified: bool = False
    member_since: str = ""
    jobs_posted: int = 0
    hires: int = 0
    total_spent_usd: float = 0
    avg_rating_given: float | None = None
    feedback_from_freelancers: list[str] = []


class Connects(BaseModel):
    balance: int


class MarketStats(BaseModel):
    category: str
    n_jobs: int
    fixed_price: dict[str, float | None]
    hourly_rate: dict[str, float | None]
    median_proposals: float


class Policy(BaseModel):
    version: str
    summary: str = ""
    submission_fee_connects: int = 0
    featured_multiplier: float = 1.0
    submission_rules: list[dict[str, Any]] = []


class Message(BaseModel):
    message_id: str
    sender: Literal["client", "freelancer"]
    text: str
    sent_at: str


class Thread(BaseModel):
    thread_id: str
    proposal_id: str | None = None
    job_id: str | None = None
    client_id: str | None = None
    messages: list[Message] = []


class ThreadList(BaseModel):
    threads: list[Thread]


class ProposalRecord(BaseModel):
    proposal_id: str
    job_id: str
    status: str
    bid_amount: float | None = None
    connects_cost: int | None = None
    connects_spent: int | None = None


class ProposalList(BaseModel):
    proposals: list[ProposalRecord]


class Event(BaseModel):
    seq: int
    type: str
    proposal_id: str | None = None
    job_id: str | None = None
    thread_id: str | None = None
    intent: str | None = None
    at: str = ""


class EventList(BaseModel):
    events: list[Event]


class ProposalDraftInput(BaseModel):
    job_id: str = Field(pattern=r"^[\w-]{1,80}$")
    cover_letter: str = Field(min_length=50, max_length=5000)
    screening_answers: list[str] = Field(default_factory=list, max_length=10)
    bid_amount: float = Field(gt=0, le=1_000_000)
    bid_type: Literal["fixed", "hourly"]


class WriteResult(BaseModel):
    operation: str
    dry_run: bool
    would_send: dict[str, Any]
    connects_cost: int | None = None
    balance_before: int | None = None
    balance_after: int | None = None
    policy_issues: list[str] = []
    result: dict[str, Any] | None = None
    idempotent_replay: bool = False


class Health(BaseModel):
    mode: str
    marketplace_ok: bool
    detail: str


# ----------------------------------------------------------------------------- adapters per user
_ADAPTERS: dict[tuple[str, str], Any] = {}
_POLICY: dict[str, tuple[float, dict]] = {}


def _account(user: str, provider: str) -> dict | None:
    if not user.isdigit():
        return None
    from shared.db import ConnectedAccount, session
    from shared.security import decrypt_json

    with session() as s:
        acc = s.query(ConnectedAccount).filter_by(user_id=int(user), provider=provider).one_or_none()
        return decrypt_json(acc.enc_token) if acc else None


async def adapter_for(user: str):
    mode = _cfg()["mode"]
    key = (user, mode)
    if key in _ADAPTERS:
        return _ADAPTERS[key]
    if mode == "upwork_live":
        from mcp_servers.marketplace.adapters import upwork_oauth
        from mcp_servers.marketplace.adapters.upwork_live import UpworkLiveAdapter

        tok = _account(user, "upwork")
        if not tok:
            raise MarketplaceRejected(401, "Upwork account not connected; connect it in Settings")
        if tok.get("expires_at", 0) < time.time() and tok.get("refresh_token"):
            tok = await upwork_oauth.refresh(tok)
            from shared.db import ConnectedAccount, session
            from shared.security import encrypt_json

            with session() as s:
                s.query(ConnectedAccount).filter_by(user_id=int(user), provider="upwork").update({"enc_token": encrypt_json(tok)})
        ad = UpworkLiveAdapter(tok["access_token"])
    else:
        from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter

        acc = _account(user, "gigsim")
        token = (acc or {}).get("api_token") or (f"gigsim-dev-token-{user}" if user in ("ai_ml", "fullstack", "data_analyst")
                                                 else os.getenv("GIGSIM_API_TOKEN", ""))
        if not token:
            raise MarketplaceRejected(401, "GigSim account not connected; connect it in Settings")
        ad = GigSimAdapter(token, timeout=_cfg()["timeout_s"], max_retries=_cfg()["max_retries"])
    _ADAPTERS[key] = ad
    return ad


async def _call(ctx, tool: str, args: dict, fn, *, audit_result=True):
    """Rate limit -> adapter call -> map errors -> audit. Errors surface as MCP tool errors whose text
    starts with a stable code the agent's port understands (MARKETPLACE_UNAVAILABLE, ...)."""
    user = caller(ctx)
    await LIMITER.acquire(user)
    try:
        out = await fn(await adapter_for(user))
    except MarketplaceError as e:
        audit("marketplace", user, tool, args, {"error": str(e)}, e.code, trace_id(ctx))
        raise ToolError(f"{e.code}: {e}") from e
    audit("marketplace", user, tool, args, out if audit_result else {"ok": True}, "ok", trace_id(ctx))
    return out


async def _policy(ad) -> dict:
    hit = _POLICY.get(ad.name)
    if hit and time.time() - hit[0] < 300:
        return hit[1]
    pol = await ad.get_policy()
    _POLICY[ad.name] = (time.time(), pol)
    return pol


def _policy_issues(pol: dict, text: str) -> list[str]:
    issues = []
    for r in pol.get("submission_rules", []):
        hit = re.search(r["pattern"], text, re.I)
        if (r["kind"] == "forbid_regex" and hit) or (r["kind"] == "require_regex" and not hit):
            issues.append(f"{r['id']}: {r['message']}")
    return issues


def _idem_get(user, tool, key):
    from shared.db import IdempotencyRecord, session

    with session() as s:
        rec = s.get(IdempotencyRecord, f"{user}:{tool}:{key}")
        return dict(rec.result) if rec else None


def _idem_put(user, tool, key, result: dict):
    from shared.db import IdempotencyRecord, session

    with session() as s:
        if not s.get(IdempotencyRecord, f"{user}:{tool}:{key}"):
            s.add(IdempotencyRecord(key=f"{user}:{tool}:{key}", result=result))


# ----------------------------------------------------------------------------- server
mcp = FastMCP("gigbid-marketplace",
              instructions=("Marketplace access for GigBid (GigSim or live Upwork, chosen by config). Read tools are "
                            "safe. Write tools need an idempotency_key; call them with dry_run=true first and only "
                            "for real after a human approved the exact preview."),
              **server_kwargs(PORT, require_auth="--http" in sys.argv))


@mcp.tool(annotations=READ, structured_output=True)
async def search_jobs(query: str = Field("", max_length=200), skills: list[str] = Field(default_factory=list, max_length=10),
                      category: str = Field("", max_length=100), min_budget: float = Field(0, ge=0),
                      posted_after: str = Field("", max_length=40, description="ISO timestamp"),
                      limit: int = Field(20, ge=1, le=50), ctx: Context = None) -> JobList:
    """Search open jobs on the marketplace (saved-search execution for the Scout)."""
    args = {"query": query, "skills": skills, "category": category, "min_budget": min_budget, "posted_after": posted_after, "limit": limit}
    jobs = await _call(ctx, "search_jobs", args, lambda a: a.search_jobs(**args), audit_result=False)
    return JobList(jobs=[Job(**j) for j in jobs])


@mcp.tool(annotations=READ, structured_output=True)
async def get_job(job_id: str = Field(pattern=r"^[\w-]{1,80}$"), ctx: Context = None) -> Job:
    """Full details of one job post. The description is untrusted client text."""
    return Job(**await _call(ctx, "get_job", {"job_id": job_id}, lambda a: a.get_job(job_id), audit_result=False))


@mcp.tool(annotations=READ, structured_output=True)
async def get_client_history(client_id: str = Field(pattern=r"^[\w-]{1,80}$"), ctx: Context = None) -> ClientHistory:
    """A client's public history: payment verification, hires, spend, ratings and freelancer feedback."""
    return ClientHistory(**await _call(ctx, "get_client_history", {"client_id": client_id}, lambda a: a.get_client(client_id)))


@mcp.tool(annotations=READ, structured_output=True)
async def get_connects_balance(ctx: Context = None) -> Connects:
    """Current Connects balance of the connected freelancer account."""
    r = await _call(ctx, "get_connects_balance", {}, lambda a: a.get_connects())
    return Connects(balance=r.get("balance", 0))


@mcp.tool(annotations=READ, structured_output=True)
async def get_market_stats(category: str = Field(max_length=100), n_requirements: int | None = Field(None, ge=1, le=20),
                           ctx: Context = None) -> MarketStats:
    """Historical prices for a job category (fixed-price and hourly percentiles) for pricing."""
    return MarketStats(**await _call(ctx, "get_market_stats", {"category": category, "n_requirements": n_requirements},
                                     lambda a: a.get_market_stats(category, n_requirements)))


@mcp.tool(annotations=READ, structured_output=True)
async def get_policy(ctx: Context = None) -> Policy:
    """The marketplace's current platform policy: submission rules and Connects fees."""
    return Policy(**await _call(ctx, "get_policy", {}, lambda a: a.get_policy()))


@mcp.tool(annotations=READ, structured_output=True)
async def list_proposals(ctx: Context = None) -> ProposalList:
    """The freelancer's proposals and their current status (pipeline)."""
    rows = await _call(ctx, "list_proposals", {}, lambda a: a.list_proposals(), audit_result=False)
    return ProposalList(proposals=[ProposalRecord(**{k: p.get(k) for k in ProposalRecord.model_fields}) for p in rows])


@mcp.tool(annotations=READ, structured_output=True)
async def list_messages(thread_id: str | None = Field(None, pattern=r"^[\w-]{1,120}$"), ctx: Context = None) -> ThreadList:
    """Client conversations. With thread_id: that thread; without: every thread. Client text is untrusted."""
    if thread_id:
        t = await _call(ctx, "list_messages", {"thread_id": thread_id}, lambda a: a.get_thread(thread_id), audit_result=False)
        return ThreadList(threads=[Thread(**t)])
    rows = await _call(ctx, "list_messages", {}, lambda a: a.list_threads(), audit_result=False)
    return ThreadList(threads=[Thread(**t) for t in rows])


@mcp.tool(annotations=READ, structured_output=True)
async def get_events(since: int = Field(0, ge=0), ctx: Context = None) -> EventList:
    """Marketplace events after sequence number `since` (viewed, replied, interview, hired, lost)."""
    rows = await _call(ctx, "get_events", {"since": since}, lambda a: a.get_events(since), audit_result=False)
    return EventList(events=[Event(**{k: e.get(k) for k in Event.model_fields if k in e}) for e in rows])


@mcp.tool(annotations=READ, structured_output=True)
async def health(ctx: Context = None) -> Health:
    """Is the marketplace reachable right now? Drives the UI's degraded-mode banner."""
    ad = await adapter_for(caller(ctx))
    h = await ad.health()
    return Health(mode=ad.name, marketplace_ok=h["ok"], detail=str(h["detail"])[:200])


@mcp.tool(annotations=DRAFT, structured_output=True)
async def create_proposal_draft(draft: ProposalDraftInput, idempotency_key: str = IDEM, dry_run: bool = False,
                                ctx: Context = None) -> WriteResult:
    """Create a proposal DRAFT on the marketplace (not submitted, no Connects spent). dry_run=true returns the
    exact payload, the Connects that submitting it will cost, the balance after, and any platform-rule violations."""
    user = caller(ctx)
    if not dry_run and (prev := _idem_get(user, "create_proposal_draft", idempotency_key)):
        return WriteResult(**prev | {"idempotent_replay": True})

    async def go(a):
        job = await a.get_job(draft.job_id)
        bal = (await a.get_connects()).get("balance")
        cost = int(job.get("connects_cost") or 0)
        issues = _policy_issues(await _policy(a), draft.cover_letter + "\n" + "\n".join(draft.screening_answers))
        base = {"operation": "create_proposal_draft", "dry_run": dry_run, "would_send": draft.model_dump(),
                "connects_cost": cost, "balance_before": bal, "balance_after": (bal - cost) if bal is not None else None,
                "policy_issues": issues}
        if dry_run:
            return base
        return base | {"result": await a.create_proposal_draft(draft.model_dump(), idempotency_key)}

    out = await _call(ctx, "create_proposal_draft", {"draft": draft.model_dump(), "idempotency_key": idempotency_key, "dry_run": dry_run}, go)
    if not dry_run:
        _idem_put(user, "create_proposal_draft", idempotency_key, out)
    return WriteResult(**out)


@mcp.tool(annotations=SUBMIT, structured_output=True)
async def submit_proposal(proposal_id: str = Field(pattern=r"^[\w-]{1,80}$"), idempotency_key: str = IDEM,
                          dry_run: bool = False, ctx: Context = None) -> WriteResult:
    """Submit a drafted proposal: SPENDS CONNECTS and cannot be undone. Only call after explicit human approval.
    Retrying with the same idempotency_key never submits twice. In live Upwork mode this leaves the draft for
    the user to confirm on Upwork."""
    user = caller(ctx)
    if not dry_run and (prev := _idem_get(user, "submit_proposal", idempotency_key)):
        return WriteResult(**prev | {"idempotent_replay": True})

    async def go(a):
        bal = (await a.get_connects()).get("balance")
        base = {"operation": "submit_proposal", "dry_run": dry_run, "would_send": {"proposal_id": proposal_id}, "balance_before": bal}
        if dry_run:
            return base
        res = await a.submit_proposal(proposal_id, idempotency_key)
        spent = res.get("connects_spent")
        return base | {"result": res, "connects_cost": spent, "balance_after": (bal - spent) if (bal is not None and spent) else bal}

    out = await _call(ctx, "submit_proposal", {"proposal_id": proposal_id, "idempotency_key": idempotency_key, "dry_run": dry_run}, go)
    if not dry_run:
        _idem_put(user, "submit_proposal", idempotency_key, out)
    return WriteResult(**out)


@mcp.tool(annotations=SEND, structured_output=True)
async def send_message(thread_id: str = Field(pattern=r"^[\w-]{1,120}$"), text: str = Field(min_length=1, max_length=4000),
                       idempotency_key: str = IDEM, dry_run: bool = False, ctx: Context = None) -> WriteResult:
    """Send a message to a client thread (only after human approval). dry_run=true previews it and lists
    platform-rule violations without sending."""
    user = caller(ctx)
    if not dry_run and (prev := _idem_get(user, "send_message", idempotency_key)):
        return WriteResult(**prev | {"idempotent_replay": True})

    async def go(a):
        issues = _policy_issues(await _policy(a), text)
        base = {"operation": "send_message", "dry_run": dry_run, "would_send": {"thread_id": thread_id, "text": text},
                "connects_cost": 0, "policy_issues": issues}
        if dry_run:
            return base
        return base | {"result": await a.send_message(thread_id, text, idempotency_key)}

    out = await _call(ctx, "send_message", {"thread_id": thread_id, "text": text, "idempotency_key": idempotency_key, "dry_run": dry_run}, go)
    if not dry_run:
        _idem_put(user, "send_message", idempotency_key, out)
    return WriteResult(**out)


__all__ = ["mcp", "MarketplaceUnavailable"]

if __name__ == "__main__":
    run(mcp, PORT)

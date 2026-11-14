"""GigBid Workspace MCP server: free calendar slots, tentative interview holds and email drafts.

Backed by a documented local mock (tables calendar_holds / email_drafts in the shared DB) rather than
Google Calendar + Gmail; the agent sees only these MCP tools either way, so swapping in the Google
APIs means replacing the three functions under "backend" and nothing else. Nothing here ever sends
an email: drafts only.

    python -m mcp_servers.workspace.server --http      # streamable HTTP on :8103
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from mcp_servers.common import audit, caller, run, server_kwargs, trace_id

PORT = int(os.getenv("WORKSPACE_MCP_PORT", "8103"))
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
IDEM = Field(min_length=8, max_length=120, pattern=r"^[A-Za-z0-9:_.-]+$")


def _ws():
    from agent.config import settings

    return settings()["workspace"]


class Slot(BaseModel):
    start: str
    end: str
    label: str


class SlotList(BaseModel):
    timezone: str
    slots: list[Slot]


class Hold(BaseModel):
    hold_id: int
    start: str
    minutes: int
    title: str
    tentative: bool
    idempotent_replay: bool = False


class Draft(BaseModel):
    draft_id: int
    to: str
    subject: str
    body: str
    idempotent_replay: bool = False


mcp = FastMCP("gigbid-workspace", instructions="Calendar availability, tentative interview holds and email drafts (never sends).",
              **server_kwargs(PORT, require_auth="--http" in sys.argv))


# ----------------------------------------------------------------------------- backend (local mock)
def _holds(user: str):
    from shared.db import CalendarHold, session

    with session() as s:
        return [(h.start, h.minutes) for h in s.query(CalendarHold).filter_by(user_id=user)]


@mcp.tool(annotations=READ, structured_output=True)
def free_slots(start_date: str = Field(description="YYYY-MM-DD, first day to search"),
               days: int = Field(5, ge=1, le=14), duration_minutes: int = Field(30, ge=15, le=120),
               max_slots: int = Field(6, ge=1, le=20), ctx: Context = None) -> SlotList:
    """Free interview slots inside the freelancer's working hours, skipping existing holds."""
    user = caller(ctx)
    ws = _ws()
    tz = ZoneInfo(ws["timezone"])
    try:
        d0 = date.fromisoformat(start_date)
    except ValueError as e:
        raise ToolError("start_date must be YYYY-MM-DD") from e
    busy = [(s.astimezone(tz) if s.tzinfo else s.replace(tzinfo=tz), m) for s, m in _holds(user)]
    now = datetime.now(tz)
    out = []
    for i in range(days):
        d = d0 + timedelta(days=i)
        if d.weekday() not in ws["working_days"]:
            continue
        t = datetime.combine(d, time(ws["working_hours"][0]), tz)
        end_day = datetime.combine(d, time(ws["working_hours"][1]), tz)
        while t + timedelta(minutes=duration_minutes) <= end_day and len(out) < max_slots:
            e = t + timedelta(minutes=duration_minutes)
            clash = any(b < e and t < b + timedelta(minutes=m) for b, m in busy)
            if t > now and not clash:
                out.append(Slot(start=t.isoformat(), end=e.isoformat(), label=t.strftime("%a %d %b, %H:%M") + f" ({ws['timezone']})"))
                t += timedelta(minutes=120)  # spread suggestions across the day
            else:
                t += timedelta(minutes=30)
    audit("workspace", user, "free_slots", {"start_date": start_date, "days": days}, {"n": len(out)}, "ok", trace_id(ctx))
    return SlotList(timezone=ws["timezone"], slots=out)


@mcp.tool(annotations=WRITE, structured_output=True)
def create_interview_hold(start: str = Field(description="ISO datetime of the slot"), duration_minutes: int = Field(30, ge=15, le=120),
                          title: str = Field(max_length=200), idempotency_key: str = IDEM, ctx: Context = None) -> Hold:
    """Place a TENTATIVE calendar hold for a proposed interview (only after the user approved the reply)."""
    from shared.db import CalendarHold, session

    user = caller(ctx)
    with session() as s:
        prev = s.query(CalendarHold).filter_by(user_id=user, idempotency_key=idempotency_key).one_or_none()
        if prev:
            return Hold(hold_id=prev.id, start=prev.start.isoformat(), minutes=prev.minutes, title=prev.title,
                        tentative=prev.tentative, idempotent_replay=True)
        h = CalendarHold(user_id=user, start=datetime.fromisoformat(start), minutes=duration_minutes, title=title,
                         idempotency_key=idempotency_key)
        s.add(h)
        s.flush()
        out = Hold(hold_id=h.id, start=h.start.isoformat(), minutes=h.minutes, title=title, tentative=True)
    audit("workspace", user, "create_interview_hold", {"start": start, "title": title}, out.model_dump(), "ok", trace_id(ctx))
    return out


@mcp.tool(annotations=WRITE, structured_output=True)
def create_email_draft(to: str = Field(max_length=200), subject: str = Field(max_length=300), body: str = Field(max_length=8000),
                       idempotency_key: str = IDEM, ctx: Context = None) -> Draft:
    """Save an email DRAFT (never sent) for the freelancer to review in their mail client."""
    from shared.db import EmailDraft, session

    user = caller(ctx)
    with session() as s:
        prev = s.query(EmailDraft).filter_by(user_id=user, idempotency_key=idempotency_key).one_or_none()
        if prev:
            return Draft(draft_id=prev.id, to=prev.to, subject=prev.subject, body=prev.body, idempotent_replay=True)
        d = EmailDraft(user_id=user, to=to, subject=subject, body=body, idempotency_key=idempotency_key)
        s.add(d)
        s.flush()
        out = Draft(draft_id=d.id, to=to, subject=subject, body=body)
    audit("workspace", user, "create_email_draft", {"to": to, "subject": subject}, {"draft_id": out.draft_id}, "ok", trace_id(ctx))
    return out


if __name__ == "__main__":
    run(mcp, PORT)

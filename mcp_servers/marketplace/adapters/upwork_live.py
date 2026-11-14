"""Live Upwork adapter: the official Upwork MCP server via MultiServerMCPClient (Streamable HTTP + OAuth).

The graph never sees this class - it talks to GigBid's marketplace port, which routes here when
`marketplace.mode: upwork_live`. Upwork tool names are mapped in config (upwork_tool_map.yaml) because
they are the vendor's to change; `python -m mcp_servers.marketplace.adapters.upwork_live --list-tools`
prints the live names so the map can be updated without touching code.

Live-mode rules enforced here:
- reads only, on the conservative schedule in config (marketplace.live_poll_minutes);
- proposals and messages are created as *drafts*; `submit_proposal` never submits - it returns the
  draft for the user to confirm on Upwork, as the platform requires;
- no browser automation, no cookies, no scraping.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

from mcp_servers.marketplace.adapters.base import MarketplaceRejected, MarketplaceUnavailable
from mcp_servers.marketplace.adapters.upwork_oauth import UPWORK_MCP_URL

TOOL_MAP = yaml.safe_load((Path(__file__).parent / "upwork_tool_map.yaml").read_text(encoding="utf-8"))


def _parse(result):
    if isinstance(result, list):
        result = "\n".join(r.get("text", "") if isinstance(r, dict) else getattr(r, "text", str(r)) for r in result)
    try:
        return json.loads(result)
    except (TypeError, ValueError):
        return {"text": str(result)}


def _norm_job(j: dict) -> dict:
    """Map Upwork's job shape onto GigBid's (fields named in the tool map's `job_fields`)."""
    f = TOOL_MAP["job_fields"]
    get = lambda k, d=None: j.get(f.get(k, k), d)  # noqa: E731
    budget = get("budget") or {}
    if not isinstance(budget, dict):
        budget = {"type": "fixed", "min": None, "max": budget}
    return {"job_id": str(get("job_id")), "title": get("title", ""), "description": get("description", ""),
            "category": get("category", ""), "skills": get("skills", []) or [],
            "budget": {"type": budget.get("type", "fixed"), "min": budget.get("min"), "max": budget.get("max"),
                       "currency": budget.get("currency", "USD")},
            "duration_days": get("duration_days"), "hours_per_week": get("hours_per_week"),
            "screening_questions": get("screening_questions", []) or [], "client_id": str(get("client_id", "")),
            "posted_at": get("posted_at", ""), "connects_cost": get("connects_cost", 0) or 0,
            "proposals_count": get("proposals_count", 0) or 0, "featured": bool(get("featured", False)), "status": "open"}


class UpworkLiveAdapter:
    name = "upwork_live"

    def __init__(self, access_token: str, url: str = UPWORK_MCP_URL):
        from langchain_mcp_adapters.client import MultiServerMCPClient

        self.client = MultiServerMCPClient({"upwork": {"transport": "streamable_http", "url": url,
                                                       "headers": {"Authorization": f"Bearer {access_token}"}}})
        self._tools = None

    async def tools(self):
        if self._tools is None:
            try:
                self._tools = {t.name: t for t in await self.client.get_tools(server_name="upwork")}
            except Exception as e:  # noqa: BLE001
                raise MarketplaceUnavailable(f"Upwork MCP unreachable: {type(e).__name__}") from e
        return self._tools

    async def _call(self, op: str, args: dict):
        name = TOOL_MAP["tools"].get(op)
        if not name:
            raise MarketplaceRejected(501, f"'{op}' has no Upwork equivalent in upwork_tool_map.yaml")
        tools = await self.tools()
        if name not in tools:
            raise MarketplaceRejected(501, f"Upwork MCP has no tool {name!r}; update upwork_tool_map.yaml")
        try:
            return _parse(await tools[name].ainvoke(args))
        except Exception as e:  # noqa: BLE001
            raise MarketplaceUnavailable(f"Upwork tool {name} failed: {type(e).__name__}") from e

    async def search_jobs(self, query="", skills=None, category="", min_budget=0, posted_after="", limit=20):
        r = await self._call("search_jobs", {"query": " ".join([query, *(skills or [])]).strip(), "limit": limit})
        jobs = r.get("jobs", r if isinstance(r, list) else [])
        return [_norm_job(j) for j in jobs][:limit]

    async def get_job(self, job_id):
        return _norm_job(await self._call("get_job", {"job_id": job_id}))

    async def get_client(self, client_id):
        return await self._call("get_client", {"client_id": client_id})

    async def get_connects(self):
        r = await self._call("get_connects", {})
        return {"balance": r.get("balance", r.get("connects", 0))}

    async def get_market_stats(self, category, n_requirements=None):
        raise MarketplaceRejected(501, "market statistics are not offered by Upwork MCP; pricing falls back to job budget")

    async def get_policy(self):
        return {"version": "upwork-live", "submission_rules": [], "submission_fee_connects": 0, "featured_multiplier": 1.0}

    async def create_proposal_draft(self, payload, idempotency_key):
        r = await self._call("create_proposal_draft", payload | {"client_reference": idempotency_key})
        return {"proposal_id": str(r.get("id", r.get("proposal_id", ""))), "status": "draft_on_upwork", **r}

    async def submit_proposal(self, proposal_id, idempotency_key):
        # Never submits in live mode: the user confirms the draft on Upwork itself.
        return {"proposal_id": proposal_id, "status": "awaiting_confirmation_on_upwork",
                "note": "Open Upwork and confirm this draft; GigBid does not submit in live mode."}

    async def list_proposals(self):
        r = await self._call("list_proposals", {})
        return r.get("proposals", r if isinstance(r, list) else [])

    async def list_threads(self):
        r = await self._call("list_threads", {})
        return r.get("rooms", r if isinstance(r, list) else [])

    async def get_thread(self, thread_id):
        return await self._call("get_thread", {"room_id": thread_id})

    async def send_message(self, thread_id, text, idempotency_key):
        r = await self._call("send_message", {"room_id": thread_id, "text": text})
        return {"thread_id": thread_id, "status": "draft_on_upwork", **r}

    async def get_events(self, since=0):
        return []  # live mode refreshes the pipeline from list_proposals on the scout schedule

    async def health(self):
        try:
            await self.tools()
            return {"ok": True, "detail": "upwork mcp reachable"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "detail": str(e)}


if __name__ == "__main__" and "--list-tools" in sys.argv:
    import asyncio
    import os

    async def _main():
        a = UpworkLiveAdapter(os.environ["UPWORK_ACCESS_TOKEN"])
        for n, t in (await a.tools()).items():
            print(n, "-", (t.description or "")[:100])

    asyncio.run(_main())

"""The single marketplace interface the graphs use (R1).

The graph only ever holds a `MarketplacePort`. Its one implementation calls GigBid's Marketplace MCP
server, which routes to the GigSim adapter or the live Upwork adapter according to
`marketplace.mode` in config (mcp_servers/marketplace/adapters/{gigsim,upwork_live}.py). Switching to
live mode therefore changes one config value; no graph or node code changes.
"""

from __future__ import annotations

from typing import Any, Protocol

from agent.mcp_client import MarketplaceRejected, MarketplaceUnavailable, MCPHub  # noqa: F401 (re-export)


class MarketplacePort(Protocol):
    async def search_jobs(self, query: str = "", skills: list[str] | None = None, category: str = "",
                          min_budget: float = 0, posted_after: str = "", limit: int = 20) -> list[dict[str, Any]]: ...
    async def get_job(self, job_id: str) -> dict[str, Any]: ...
    async def get_client_history(self, client_id: str) -> dict[str, Any]: ...
    async def get_connects_balance(self) -> int: ...
    async def get_market_stats(self, category: str, n_requirements: int | None = None) -> dict[str, Any]: ...
    async def get_policy(self) -> dict[str, Any]: ...
    async def preview_proposal(self, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]: ...
    async def create_proposal_draft(self, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]: ...
    async def submit_proposal(self, proposal_id: str, idempotency_key: str) -> dict[str, Any]: ...
    async def preview_message(self, thread_id: str, text: str, idempotency_key: str) -> dict[str, Any]: ...
    async def send_message(self, thread_id: str, text: str, idempotency_key: str) -> dict[str, Any]: ...
    async def list_messages(self, thread_id: str | None = None) -> list[dict[str, Any]]: ...
    async def list_proposals(self) -> list[dict[str, Any]]: ...
    async def get_events(self, since: int = 0) -> list[dict[str, Any]]: ...
    async def health(self) -> dict[str, Any]: ...


class MCPMarketplace:
    """MarketplacePort over MCP. `node` is the calling agent, so allowlists apply per agent."""

    def __init__(self, hub: MCPHub, node: str):
        self.hub, self.node = hub, node

    async def _c(self, tool, **args):
        return await self.hub.call(self.node, tool, {k: v for k, v in args.items() if v is not None})

    async def search_jobs(self, query="", skills=None, category="", min_budget=0, posted_after="", limit=20):
        return (await self._c("search_jobs", query=query, skills=skills or [], category=category, min_budget=min_budget,
                              posted_after=posted_after, limit=limit))["jobs"]

    async def get_job(self, job_id):
        return await self._c("get_job", job_id=job_id)

    async def get_client_history(self, client_id):
        return await self._c("get_client_history", client_id=client_id)

    async def get_connects_balance(self):
        return (await self._c("get_connects_balance"))["balance"]

    async def get_market_stats(self, category, n_requirements=None):
        return await self._c("get_market_stats", category=category, n_requirements=n_requirements)

    async def get_policy(self):
        return await self._c("get_policy")

    async def preview_proposal(self, payload, idempotency_key):
        return await self._c("create_proposal_draft", draft=payload, idempotency_key=idempotency_key, dry_run=True)

    async def create_proposal_draft(self, payload, idempotency_key):
        return await self._c("create_proposal_draft", draft=payload, idempotency_key=idempotency_key, dry_run=False)

    async def submit_proposal(self, proposal_id, idempotency_key):
        return await self._c("submit_proposal", proposal_id=proposal_id, idempotency_key=idempotency_key, dry_run=False)

    async def preview_message(self, thread_id, text, idempotency_key):
        return await self._c("send_message", thread_id=thread_id, text=text, idempotency_key=idempotency_key, dry_run=True)

    async def send_message(self, thread_id, text, idempotency_key):
        return await self._c("send_message", thread_id=thread_id, text=text, idempotency_key=idempotency_key, dry_run=False)

    async def list_messages(self, thread_id=None):
        return (await self._c("list_messages", thread_id=thread_id))["threads"]

    async def list_proposals(self):
        return (await self._c("list_proposals"))["proposals"]

    async def get_events(self, since=0):
        return (await self._c("get_events", since=since))["events"]

    async def health(self):
        return await self._c("health")

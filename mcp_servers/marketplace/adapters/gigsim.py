"""GigSim adapter: REST over httpx with timeouts, bounded retries, backoff and Retry-After handling."""

from __future__ import annotations

import asyncio
import os
import random

import httpx

from mcp_servers.marketplace.adapters.base import MarketplaceRejected, MarketplaceUnavailable


class GigSimAdapter:
    name = "gigsim"

    def __init__(self, api_token: str, base_url: str | None = None, timeout: float = 15, max_retries: int = 3,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = base_url or os.getenv("GIGSIM_BASE_URL", "http://localhost:8081")
        if transport is None and os.getenv("GIGSIM_INPROCESS") == "1":  # tests: GigSim runs in-process
            from gigsim.app import app

            transport = httpx.ASGITransport(app=app)
            self.base_url = "http://gigsim"
        self.client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout, transport=transport,
                                        headers={"Authorization": f"Bearer {api_token}"})
        self.max_retries = max_retries

    async def _req(self, method: str, path: str, *, idem: str | None = None, **kw):
        headers = {"Idempotency-Key": idem} if idem else {}
        delay = 0.5
        for attempt in range(self.max_retries + 1):
            try:
                r = await self.client.request(method, path, headers=headers, **kw)
            except (httpx.TransportError, httpx.TimeoutException) as e:
                if attempt == self.max_retries:
                    raise MarketplaceUnavailable(f"GigSim unreachable: {type(e).__name__}") from e
            else:
                if r.status_code == 429:
                    wait = min(float(r.headers.get("Retry-After", delay)), 10.0)
                    if attempt == self.max_retries:
                        raise MarketplaceUnavailable("GigSim rate limit persists")
                    await asyncio.sleep(wait)
                    continue
                if r.status_code >= 500:
                    if attempt == self.max_retries:
                        raise MarketplaceUnavailable(f"GigSim {r.status_code}: {r.text[:200]}")
                elif r.status_code >= 400:
                    raise MarketplaceRejected(r.status_code, r.json().get("detail", r.text) if r.content else "")
                else:
                    return r.json()
            await asyncio.sleep(delay + random.random() * 0.2)  # writes are safe to retry: idempotency key
            delay = min(delay * 2, 8)
        raise MarketplaceUnavailable("unreachable")  # pragma: no cover

    async def search_jobs(self, query="", skills=None, category="", min_budget=0, posted_after="", limit=20):
        params = {"q": query, "skills": ",".join(skills or []), "category": category, "min_budget": min_budget,
                  "posted_after": posted_after, "limit": limit}
        return (await self._req("GET", "/jobs", params={k: v for k, v in params.items() if v}))["jobs"]

    async def get_job(self, job_id):
        return await self._req("GET", f"/jobs/{job_id}")

    async def get_client(self, client_id):
        return await self._req("GET", f"/clients/{client_id}")

    async def get_connects(self):
        return await self._req("GET", "/connects")

    async def get_market_stats(self, category, n_requirements=None):
        params = {"category": category} | ({"n_requirements": n_requirements} if n_requirements else {})
        return await self._req("GET", "/market/stats", params=params)

    async def get_policy(self):
        return await self._req("GET", "/policy")

    async def create_proposal_draft(self, payload, idempotency_key):
        return await self._req("POST", "/proposals/drafts", json=payload, idem=idempotency_key)

    async def submit_proposal(self, proposal_id, idempotency_key):
        return await self._req("POST", f"/proposals/{proposal_id}/submit", idem=idempotency_key)

    async def list_proposals(self):
        return await self._req("GET", "/proposals")

    async def list_threads(self):
        return await self._req("GET", "/threads")

    async def get_thread(self, thread_id):
        return await self._req("GET", f"/threads/{thread_id}")

    async def send_message(self, thread_id, text, idempotency_key):
        return await self._req("POST", f"/threads/{thread_id}/messages", json={"text": text}, idem=idempotency_key)

    async def get_events(self, since=0):
        return await self._req("GET", "/events", params={"since": since})

    async def health(self):
        try:
            r = await self.client.get("/policy", timeout=3)  # authenticated + subject to outages, unlike /health
            return {"ok": r.status_code == 200, "detail": r.json() if r.status_code == 200 else r.text[:100]}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "detail": type(e).__name__}

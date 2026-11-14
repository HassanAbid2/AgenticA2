"""GigBid API (FastAPI). Serves the JSON API under /api and, in production, the built web app.

Every request gets a trace id (OpenTelemetry span; echoed as X-Trace-Id) that flows into queued work,
the agent graph, MCP calls (header) and the audit log.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from agent.config import settings
from apps.api.auth import token_store, users
from apps.api.auth.users import current_user
from apps.api.routers import analytics, approvals, jobs, messages, runs
from apps.api.routers import settings as settings_router
from apps.api.schemas import HealthOut
from apps.api.streaming import router as stream_router
from shared.db import User, engine
from shared.security import mask_pii
from shared.tracing import new_trace_id, setup_tracing

log = logging.getLogger("gigbid.api")
tracer = setup_tracing("gigbid-api")
app = FastAPI(title="GigBid API", version="1.0.0",
              description="Multi-agent freelancer copilot: inbox, proposal studio, approvals, pipeline, messages, runs, analytics.")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def trace_requests(request: Request, call_next):
    with tracer.start_as_current_span(f"{request.method} {request.url.path}") as span:
        tid = new_trace_id()
        request.state.trace_id = tid
        t0 = time.perf_counter()
        resp = await call_next(request)
        resp.headers["X-Trace-Id"] = tid
        span.set_attribute("http.status_code", resp.status_code)
        if request.url.path.startswith("/api") and not request.url.path.startswith("/api/stream"):
            log.info("%s %s %s %.0fms trace=%s", request.method, mask_pii(request.url.path), resp.status_code,
                     (time.perf_counter() - t0) * 1000, tid)
        return resp


@app.on_event("startup")
def _startup():
    engine()  # create tables
    if os.getenv("SEED_REVIEWER", "1") == "1":
        from apps.api.seed import ensure_reviewer

        ensure_reviewer()


for r in (users.router, token_store.router, settings_router.router, jobs.router, approvals.router, messages.router,
          runs.router, analytics.router, stream_router):
    app.include_router(r)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "gigbid-api"}


_HEALTH: dict[int, tuple[float, HealthOut]] = {}


@app.get("/api/health", response_model=HealthOut, tags=["health"])
async def api_health(u: User = Depends(current_user)):
    """Marketplace reachability through the marketplace MCP server (drives the degraded-mode banner)."""
    from agent.llm import llm_available
    from agent.marketplace_port import MCPMarketplace
    from agent.mcp_client import MCPHub, ToolCallError

    hit = _HEALTH.get(u.id)
    if hit and time.time() - hit[0] < 5:
        return hit[1]
    prof = settings()["models"]["profile"]
    try:
        h = await MCPMarketplace(MCPHub(str(u.id), "", timeout=6, retries=0), "pipeline").health()
        out = HealthOut(api="ok", marketplace_ok=h["marketplace_ok"], mode=h["mode"], detail=h["detail"], model_profile=prof, llm=llm_available())
    except ToolCallError as e:
        out = HealthOut(api="ok", marketplace_ok=False, mode=settings()["marketplace"]["mode"], detail=str(e)[:200],
                        model_profile=prof, llm=llm_available())
    _HEALTH[u.id] = (time.time(), out)
    return out


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error trace=%s", getattr(request.state, "trace_id", ""))
    return JSONResponse({"detail": "internal error", "trace_id": getattr(request.state, "trace_id", "")}, status_code=500)


# ---- built web app (single public URL in production)
WEB = Path(os.getenv("WEB_DIST", Path(__file__).resolve().parents[1] / "web" / "dist"))
if WEB.exists():
    app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        f = WEB / path
        return FileResponse(f if path and f.is_file() else WEB / "index.html")

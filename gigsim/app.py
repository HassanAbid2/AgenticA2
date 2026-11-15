"""GigSim - marketplace simulator (REST API).

The starter kit referenced an instructor-provided GigSim that was not shipped, so this is a
stand-in with the same responsibilities: jobs, clients with histories, Connects, proposals,
messages, events, rate limits, occasional 5xx errors, policy versions, and simulated clients with
hidden preferences that decide whether to reply, interview or hire.

Run:  uvicorn gigsim.app:app --port 8081
Env:  GIGSIM_DATASET (dev|holdout)  GIGSIM_POLICY_VERSION (2026-10|2026-11-02)
      GIGSIM_RATE_LIMIT_PER_MIN (60)  GIGSIM_ERROR_RATE (0.03)  GIGSIM_TIME_SCALE (1.0)
      GIGSIM_RELEASE_EVERY_S (120)  GIGSIM_CLIENT_MODE (heuristic|llm)
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import statistics
import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from gigsim.client_sim import decide_outcome, draft_client_message

SEED_DIR = Path(__file__).parent / "seed"
POLICIES = json.loads((Path(__file__).parent / "policies.json").read_text())


def env(name, default):
    return type(default)(os.getenv(name, default))


class World:
    """All mutable simulator state, guarded by one lock (ponytail: fine for a simulator)."""

    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        ds = SEED_DIR / env("GIGSIM_DATASET", "dev")
        load = lambda n: json.loads((ds / n).read_text(encoding="utf-8"))  # noqa: E731
        self.clients = {c["client_id"]: c for c in load("clients.json")}
        self.clients_hidden = load("clients_hidden.json")
        self.jobs = {j["job_id"]: j for j in load("jobs_open.json")}
        self.live_pool = deque(load("jobs_live_pool.json"))
        self.jobs_hidden = load("jobs_hidden.json")
        self.historical = load("jobs_historical.json")
        self.freelancers = {f["api_token"]: dict(f) for f in load("freelancers.json")}
        self.proposals: dict[str, dict] = {}
        self.idem: dict[tuple[str, str], str] = {}
        self.threads: dict[str, dict] = {}
        self.events: list[dict] = []
        self.pending: list[tuple[float, dict]] = []  # (due_time, event)
        self.rate: dict[str, deque] = defaultdict(deque)
        self.started = time.time()
        self.released = 0
        self.policy_version = env("GIGSIM_POLICY_VERSION", "2026-10")
        self.rng = random.Random(4016)
        self.forced_down = False


W = World()
app = FastAPI(title="GigSim", version="1.0.0", description="Marketplace simulator for GigBid (AI-4016)")


# ----------------------------------------------------------------------------- middleware
@app.middleware("http")
async def chaos_and_limits(request: Request, call_next):
    path = request.url.path.removeprefix(request.scope.get("root_path", ""))  # also correct when mounted
    if path.startswith("/admin") or path in ("/health", "/openapi.json", "/docs"):
        return await call_next(request)
    if W.forced_down:
        return JSONResponse({"detail": "service unavailable (forced)"}, status_code=503)
    token = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
    now = time.time()
    with W.lock:
        q = W.rate[token]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= env("GIGSIM_RATE_LIMIT_PER_MIN", 60):
            return JSONResponse({"detail": "rate limit exceeded"}, status_code=429,
                                headers={"Retry-After": str(int(60 - (now - q[0])) + 1)})
        q.append(now)
        flaky = W.rng.random() < env("GIGSIM_ERROR_RATE", 0.03)
    if flaky:
        return JSONResponse({"detail": "transient upstream error"}, status_code=503)
    _tick()
    return await call_next(request)


def freelancer(authorization: str = Header(default="")) -> dict:
    tok = authorization.removeprefix("Bearer ").strip()
    f = W.freelancers.get(tok)
    if not f:
        raise HTTPException(401, "invalid or missing API token")
    return f


def _now():
    return datetime.now(UTC).isoformat()


def _tick():
    """Release live jobs on schedule and deliver due events (proposal viewed/replied/...)."""
    with W.lock:
        scale = env("GIGSIM_TIME_SCALE", 1.0)
        due_releases = int((time.time() - W.started) * scale / env("GIGSIM_RELEASE_EVERY_S", 120.0)) * 3
        while W.released < due_releases and W.live_pool:
            j = dict(W.live_pool.popleft())
            j.pop("duplicate_of", None)
            j["posted_at"] = _now()
            W.jobs[j["job_id"]] = j
            W.released += 1
        now = time.time()
        keep = []
        for due, ev in W.pending:
            if due <= now:
                _apply_event(ev)
            else:
                keep.append((due, ev))
        W.pending = keep


def _apply_event(ev):
    p = W.proposals.get(ev.get("proposal_id"))
    if p and ev["type"] in ("viewed", "replied", "interview", "hired", "lost"):
        p["status"] = ev["type"]
    if ev["type"] in ("replied", "interview", "hired") and ev.get("message"):
        th = W.threads.setdefault(ev["thread_id"], {"thread_id": ev["thread_id"], "proposal_id": ev["proposal_id"],
                                                    "job_id": ev["job_id"], "client_id": ev["client_id"],
                                                    "freelancer_id": ev["freelancer_id"], "messages": []})
        th["messages"].append({"message_id": f"m-{len(th['messages'])+1}-{ev['thread_id']}", "sender": "client",
                               "text": ev["message"], "sent_at": _now()})
    ev["at"] = _now()
    ev["seq"] = len(W.events) + 1
    W.events.append(ev)


def _public_job(j):
    return {k: v for k, v in j.items() if k != "duplicate_of"} | {"connects_cost": _connects_cost(j)}


def _connects_cost(j):
    pol = POLICIES[W.policy_version]
    c = j["connects_cost"] + pol.get("submission_fee_connects", 0)
    if j.get("featured"):
        c = int(round(c * pol.get("featured_multiplier", 1.0)))
    return c


# ----------------------------------------------------------------------------- read API
@app.get("/health")
def health():
    return {"status": "ok", "jobs": len(W.jobs), "policy_version": W.policy_version}


@app.get("/policy")
def policy():
    return {"version": W.policy_version, **POLICIES[W.policy_version]}


@app.get("/jobs")
def search_jobs(q: str = "", skills: str = "", category: str = "", min_budget: float = 0,
                posted_after: str = "", limit: int = Query(20, le=50), offset: int = 0, f=Depends(freelancer)):
    terms = [t for t in re.split(r"\W+", q.lower()) if t]
    want = {s.strip().lower() for s in skills.split(",") if s.strip()}
    out = []
    for j in W.jobs.values():
        if j["status"] != "open":
            continue
        hay = (j["title"] + " " + j["description"] + " " + " ".join(j["skills"])).lower()
        if terms and not all(t in hay for t in terms):
            continue
        if want and not want & {s.lower() for s in j["skills"]}:
            continue
        if category and j["category"] != category:
            continue
        if min_budget and (j["budget"]["max"] or 0) < min_budget:
            continue
        if posted_after and j["posted_at"] <= posted_after:
            continue
        out.append(j)
    out.sort(key=lambda j: j["posted_at"], reverse=True)
    return {"total": len(out), "jobs": [_public_job(j) for j in out[offset: offset + limit]]}


@app.get("/jobs/{job_id}")
def get_job(job_id: str, f=Depends(freelancer)):
    j = W.jobs.get(job_id)
    if not j:
        raise HTTPException(404, "job not found")
    return _public_job(j)


@app.get("/clients/{client_id}")
def get_client(client_id: str, f=Depends(freelancer)):
    c = W.clients.get(client_id)
    if not c:
        raise HTTPException(404, "client not found")
    return c


@app.get("/market/stats")
def market_stats(category: str, n_requirements: int | None = None, f=Depends(freelancer)):
    rows = [h for h in W.historical if h["category"] == category]
    if n_requirements is not None:
        near = [h for h in rows if abs(h["n_requirements"] - n_requirements) <= 1]
        rows = near or rows
    if not rows:
        raise HTTPException(404, "no history for category")
    fixed = sorted(h["final_price_usd"] for h in rows if h["budget_type"] == "fixed")
    hourly = sorted(h["hourly_rate_usd"] for h in rows if h["budget_type"] == "hourly")
    q = lambda xs, p: xs[min(len(xs) - 1, int(p * len(xs)))] if xs else None  # noqa: E731
    return {"category": category, "n_jobs": len(rows),
            "fixed_price": {"p25": q(fixed, .25), "median": q(fixed, .5), "p75": q(fixed, .75)},
            "hourly_rate": {"p25": q(hourly, .25), "median": q(hourly, .5), "p75": q(hourly, .75)},
            "median_proposals": statistics.median(h["proposals_count"] for h in rows)}


@app.get("/me")
def me(f=Depends(freelancer)):
    return {"freelancer_id": f["freelancer_id"], "name": f["name"], "connects_balance": f["connects_balance"]}


@app.get("/connects")
def connects(f=Depends(freelancer)):
    return {"freelancer_id": f["freelancer_id"], "balance": f["connects_balance"]}


@app.get("/proposals")
def list_proposals(f=Depends(freelancer)):
    return [p for p in W.proposals.values() if p["freelancer_id"] == f["freelancer_id"]]


@app.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: str, f=Depends(freelancer)):
    p = W.proposals.get(proposal_id)
    if not p or p["freelancer_id"] != f["freelancer_id"]:
        raise HTTPException(404, "proposal not found")
    return p


@app.get("/threads")
def list_threads(f=Depends(freelancer)):
    return [t for t in W.threads.values() if t["freelancer_id"] == f["freelancer_id"]]


@app.get("/threads/{thread_id}")
def get_thread(thread_id: str, f=Depends(freelancer)):
    t = W.threads.get(thread_id)
    if not t or t["freelancer_id"] != f["freelancer_id"]:
        raise HTTPException(404, "thread not found")
    return t


@app.get("/events")
def events(since: int = 0, f=Depends(freelancer)):
    return [e for e in W.events if e["seq"] > since and e.get("freelancer_id") == f["freelancer_id"]]


# ----------------------------------------------------------------------------- write API
class ProposalIn(BaseModel):
    job_id: str
    cover_letter: str = Field(min_length=50, max_length=5000)
    screening_answers: list[str] = Field(default_factory=list, max_length=10)
    bid_amount: float = Field(gt=0, le=1_000_000)
    bid_type: str = Field(pattern="^(fixed|hourly)$")


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


def _idem(f, key: str | None):
    if not key:
        raise HTTPException(400, "Idempotency-Key header is required on writes")
    return (f["freelancer_id"], key)


def _policy_check(text: str):
    pol = POLICIES[W.policy_version]
    for rule in pol["submission_rules"]:
        if rule["kind"] == "forbid_regex" and re.search(rule["pattern"], text, re.I):
            raise HTTPException(422, f"policy_violation: {rule['id']} {rule['message']}")
        if rule["kind"] == "require_regex" and not re.search(rule["pattern"], text, re.I):
            raise HTTPException(422, f"policy_violation: {rule['id']} {rule['message']}")


@app.post("/proposals/drafts", status_code=201)
def create_draft(body: ProposalIn, f=Depends(freelancer), idempotency_key: str | None = Header(default=None)):
    key = _idem(f, idempotency_key)
    with W.lock:
        if key in W.idem:
            return W.proposals[W.idem[key]] | {"idempotent_replay": True}
        j = W.jobs.get(body.job_id)
        if not j or j["status"] != "open":
            raise HTTPException(404, "job not open")
        pid = "p-" + hashlib.sha1(f"{f['freelancer_id']}{key[1]}".encode()).hexdigest()[:10]
        W.proposals[pid] = {"proposal_id": pid, "freelancer_id": f["freelancer_id"], **body.model_dump(),
                            "status": "draft", "connects_cost": _connects_cost(j), "created_at": _now()}
        W.idem[key] = pid
        return W.proposals[pid]


@app.post("/proposals/{proposal_id}/submit")
def submit(proposal_id: str, f=Depends(freelancer), idempotency_key: str | None = Header(default=None)):
    key = _idem(f, idempotency_key)
    with W.lock:
        if key in W.idem:
            return W.proposals[W.idem[key]] | {"idempotent_replay": True}
        p = W.proposals.get(proposal_id)
        if not p or p["freelancer_id"] != f["freelancer_id"]:
            raise HTTPException(404, "proposal not found")
        if p["status"] != "draft":
            raise HTTPException(409, f"proposal already {p['status']}")
        if any(q["job_id"] == p["job_id"] and q["status"] not in ("draft",) and q["freelancer_id"] == f["freelancer_id"]
               for q in W.proposals.values()):
            raise HTTPException(409, "already applied to this job")
        _policy_check(p["cover_letter"] + "\n" + "\n".join(p["screening_answers"]))
        cost = _connects_cost(W.jobs[p["job_id"]])
        if f["connects_balance"] < cost:
            raise HTTPException(402, "insufficient connects")
        f["connects_balance"] -= cost
        p.update(status="submitted", submitted_at=_now(), connects_spent=cost)
        W.idem[key] = proposal_id
        _schedule_outcome(p, f)
        return p


def _schedule_outcome(p, f):
    j = W.jobs[p["job_id"]]
    hid_job = W.jobs_hidden.get(j["job_id"], {})
    hid_client = W.clients_hidden.get(j["client_id"], {})
    out = decide_outcome(j, hid_job, hid_client, p)
    p["_sim"] = out  # visible only through /admin
    scale = max(env("GIGSIM_TIME_SCALE", 1.0), 1e-6)
    t0 = time.time()
    base = {"proposal_id": p["proposal_id"], "job_id": j["job_id"], "client_id": j["client_id"],
            "freelancer_id": f["freelancer_id"], "thread_id": "t-" + p["proposal_id"]}
    W.pending.append((t0 + 20 / scale, base | {"type": "viewed"} if out["viewed"] else base | {"type": "lost"}))
    if out["viewed"]:
        if out["replied"]:
            msg = draft_client_message(j, hid_client, out, W.rng, p)
            W.pending.append((t0 + 60 / scale, base | {"type": "replied", "message": msg, "intent": out["intent"]}))
        else:
            W.pending.append((t0 + 90 / scale, base | {"type": "lost"}))


@app.post("/threads/{thread_id}/messages")
def send_message(thread_id: str, body: MessageIn, f=Depends(freelancer),
                 idempotency_key: str | None = Header(default=None)):
    key = _idem(f, idempotency_key)
    with W.lock:
        t = W.threads.get(thread_id)
        if not t or t["freelancer_id"] != f["freelancer_id"]:
            raise HTTPException(404, "thread not found")
        if key in W.idem:
            return {"thread_id": thread_id, "message_id": W.idem[key], "idempotent_replay": True}
        _policy_check(body.text)
        mid = f"m-{len(t['messages'])+1}-{thread_id}"
        t["messages"].append({"message_id": mid, "sender": "freelancer", "text": body.text, "sent_at": _now()})
        W.idem[key] = mid
        p = W.proposals[t["proposal_id"]]
        sim = p.get("_sim", {})
        scale = max(env("GIGSIM_TIME_SCALE", 1.0), 1e-6)
        base = {"proposal_id": p["proposal_id"], "job_id": p["job_id"], "client_id": t["client_id"],
                "freelancer_id": f["freelancer_id"], "thread_id": thread_id}
        mentions_slot = bool(re.search(r"\b(mon|tue|wed|thu|fri|sat|sun)\w*\b.*\d{1,2}(:\d{2})?", body.text, re.I))
        if p["status"] == "replied" and sim.get("interview"):
            W.pending.append((time.time() + 30 / scale, base | {"type": "interview",
                              "message": "Great, that works. Let's do the call at the first time you suggested."
                              if mentions_slot else "Thanks. Can you suggest two times for a 30-minute call?"}))
        elif p["status"] == "interview" and sim.get("hired"):
            W.pending.append((time.time() + 30 / scale, base | {"type": "hired",
                              "message": "Good call today. I'm sending you the contract now."}))
        elif p["status"] == "interview":
            W.pending.append((time.time() + 30 / scale, base | {"type": "lost"}))
        return {"thread_id": thread_id, "message_id": mid}


# ----------------------------------------------------------------------------- admin (graders / evals)
@app.post("/admin/fast_forward")
def fast_forward():
    """Deliver every pending event now (used by evals instead of waiting)."""
    for _ in range(4):
        with W.lock:
            pend, W.pending = W.pending, []
            for _, ev in sorted(pend, key=lambda x: x[0]):
                _apply_event(ev)
    return {"events": len(W.events)}


@app.post("/admin/reset")
def reset():
    W.reset()
    return {"ok": True}


@app.post("/admin/policy/{version}")
def set_policy(version: str):
    if version not in POLICIES:
        raise HTTPException(404, "unknown policy version")
    W.policy_version = version
    return {"version": version}


@app.post("/admin/down/{flag}")
def force_down(flag: bool):
    W.forced_down = flag
    return {"forced_down": flag}


@app.post("/admin/release/{n}")
def release(n: int):
    with W.lock:
        for _ in range(min(n, len(W.live_pool))):
            j = dict(W.live_pool.popleft())
            j.pop("duplicate_of", None)
            j["posted_at"] = _now()
            W.jobs[j["job_id"]] = j
            W.released += 1
    return {"released": W.released, "remaining": len(W.live_pool)}


@app.get("/admin/outcomes")
def outcomes() -> list[dict[str, Any]]:
    return [{"proposal_id": p["proposal_id"], "job_id": p["job_id"], "freelancer_id": p["freelancer_id"],
             "status": p["status"], **p.get("_sim", {})} for p in W.proposals.values()]

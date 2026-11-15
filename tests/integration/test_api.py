"""API end-to-end in inline task mode: signup -> onboarding -> scout -> analysis -> approval -> submitted."""

import os
import time

os.environ["MCP_INPROCESS"] = "1"
os.environ["TASK_MODE"] = "inline"
os.environ.pop("REDIS_URL", None)

from fastapi.testclient import TestClient  # noqa: E402

from apps.api.main import app  # noqa: E402
from gigsim.app import W  # noqa: E402


def wait(c, cond, timeout=400):  # inline mode runs tasks one at a time (SQLite)
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = cond()
        if r:
            return r
        time.sleep(0.5)
    raise AssertionError("timed out")


def test_full_flow_and_tenant_isolation():
    W.reset()
    with TestClient(app) as c:
        assert c.get("/api/jobs").status_code == 401
        r = c.post("/api/auth/signup", json={"email": "t1@example.com", "password": "password123", "name": "T"})
        assert r.status_code == 200
        r = c.post("/api/onboarding", json={"persona": "ai_ml", "hourly_rate": 45, "floor_hourly": 30, "min_fixed": 300,
                                             "weekly_connects_budget": 100})
        assert r.json()["onboarded"]
        for s in c.get("/api/searches").json():
            c.delete(f"/api/searches/{s['id']}")
        c.post("/api/searches", json={"name": "support bots", "query": "support tickets", "interval_minutes": 60})
        assert c.post("/api/scout/run").json()["queued"]
        jobs = wait(c, lambda: [j for j in c.get("/api/jobs").json()["jobs"] if j["status"] not in ("queued", "analysing")])
        assert jobs
        pend = wait(c, lambda: c.get("/api/approvals").json())
        a = pend[0]
        assert a["payload"]["preview"]["dry_run"] and a["payload"]["claims"]
        detail = c.get(f"/api/jobs/{a['payload']['job']['job_id']}").json()
        assert detail["analysis"]["fit_report"]["matrix"]
        assert c.post(f"/api/approvals/{a['id']}/decide", json={"action": "reject"}).status_code == 422  # reason required
        assert c.post(f"/api/approvals/{a['id']}/decide", json={"action": "approve"}).json()["queued"]
        sent_cols = ("submitted", "viewed", "replied", "interview", "hired", "lost")
        try:
            wait(c, lambda: any(c.get("/api/pipeline").json()["columns"][k] for k in sent_cols))
        except AssertionError as e:
            status = c.get(f"/api/approvals/{a['id']}").json()["status"]
            runs = [(r["id"], r["status"], r["error"]) for r in c.get("/api/runs").json()[:4]]
            raise AssertionError(f"not sent: approval={status} runs={runs}") from e
        run = c.get("/api/runs").json()[0]
        d = c.get(f"/api/runs/{run['id']}").json()
        assert d["events"] and d["audit"]  # node events + audit rows share the trace id
        assert c.get("/api/analytics").json()["funnel"]["submitted"] == 1
        # another user sees none of it
        c.post("/api/auth/logout")
        c.post("/api/auth/signup", json={"email": "t2@example.com", "password": "password123"})
        assert c.get("/api/jobs").json()["jobs"] == []
        assert c.get(f"/api/approvals/{a['id']}").status_code == 404

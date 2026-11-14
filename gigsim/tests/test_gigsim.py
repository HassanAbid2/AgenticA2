import os

from fastapi.testclient import TestClient  # noqa: E402

from gigsim.app import W, app  # noqa: E402

H = {"Authorization": "Bearer gigsim-dev-token-ai_ml"}
LETTER = ("You need an assistant that answers customer questions from your help-centre articles. I built HelpDesk "
          "Copilot with LangChain and Qdrant, which cut first-response time by 38% across 4,100 tickets a month. "
          "I would start with a short audit of your articles. What does success look like for you?")


def client():
    W.reset()
    return TestClient(app)


def test_auth_and_search():
    c = client()
    assert c.get("/jobs").status_code == 401
    r = c.get("/jobs", params={"q": "assistant"}, headers=H).json()
    assert r["total"] > 0 and "duplicate_of" not in r["jobs"][0]


def test_submit_is_idempotent_and_spends_connects_once():
    c = client()
    job = c.get("/jobs", headers=H).json()["jobs"][0]
    body = {"job_id": job["job_id"], "cover_letter": LETTER, "bid_amount": 900, "bid_type": "fixed"}
    assert c.post("/proposals/drafts", json=body, headers=H).status_code == 400  # missing key
    d = c.post("/proposals/drafts", json=body, headers=H | {"Idempotency-Key": "k1"}).json()
    d2 = c.post("/proposals/drafts", json=body, headers=H | {"Idempotency-Key": "k1"}).json()
    assert d["proposal_id"] == d2["proposal_id"] and d2["idempotent_replay"]
    before = c.get("/connects", headers=H).json()["balance"]
    s1 = c.post(f"/proposals/{d['proposal_id']}/submit", headers=H | {"Idempotency-Key": "s1"})
    s2 = c.post(f"/proposals/{d['proposal_id']}/submit", headers=H | {"Idempotency-Key": "s1"})
    assert s1.status_code == 200 and s2.json()["idempotent_replay"]
    assert c.get("/connects", headers=H).json()["balance"] == before - job["connects_cost"]


def test_policy_rejects_contact_details_and_v2_requires_disclosure():
    c = client()
    job = c.get("/jobs", headers=H).json()["jobs"][1]
    bad = {"job_id": job["job_id"], "cover_letter": LETTER + " Email me at a.b@gmail.com", "bid_amount": 500, "bid_type": "fixed"}
    d = c.post("/proposals/drafts", json=bad, headers=H | {"Idempotency-Key": "b1"}).json()
    r = c.post(f"/proposals/{d['proposal_id']}/submit", headers=H | {"Idempotency-Key": "b2"})
    assert r.status_code == 422 and "P1" in r.json()["detail"]
    c.post("/admin/policy/2026-11-02")
    ok = dict(bad, cover_letter=LETTER)
    d = c.post("/proposals/drafts", json=ok, headers=H | {"Idempotency-Key": "b3"}).json()
    r = c.post(f"/proposals/{d['proposal_id']}/submit", headers=H | {"Idempotency-Key": "b4"})
    assert r.status_code == 422 and "P8" in r.json()["detail"]


def test_rate_limit_and_forced_outage():
    os.environ["GIGSIM_RATE_LIMIT_PER_MIN"] = "5"
    c = client()
    codes = [c.get("/connects", headers=H).status_code for _ in range(7)]
    os.environ["GIGSIM_RATE_LIMIT_PER_MIN"] = "1000"
    assert 429 in codes
    c.post("/admin/down/true")
    assert c.get("/health").status_code == 200
    assert c.get("/connects", headers={"Authorization": "Bearer gigsim-dev-token-fullstack"}).status_code == 503
    c.post("/admin/down/false")


def test_outcomes_flow_to_events_and_threads():
    c = client()
    jobs = c.get("/jobs", params={"limit": 40}, headers=H).json()["jobs"]
    for i, job in enumerate(jobs):
        body = {"job_id": job["job_id"], "cover_letter": LETTER, "bid_amount": job["budget"]["min"] or 300,
                "bid_type": job["budget"]["type"], "screening_answers": ["See above."] * 2}
        d = c.post("/proposals/drafts", json=body, headers=H | {"Idempotency-Key": f"d{i}"}).json()
        c.post(f"/proposals/{d['proposal_id']}/submit", headers=H | {"Idempotency-Key": f"s{i}"})
    c.post("/admin/fast_forward")
    ev = c.get("/events", headers=H).json()
    assert any(e["type"] == "viewed" for e in ev)
    assert any(e["type"] == "replied" for e in ev)
    assert c.get("/threads", headers=H).json()

"""Onboarding, settings, saved searches, memory viewer and portfolio management."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from apps.api.auth.token_store import save_account
from apps.api.auth.users import current_user, out
from apps.api.schemas import (
    EvidenceOut,
    MemoryItem,
    MemoryOut,
    OnboardingIn,
    SavedSearchIn,
    SavedSearchOut,
    SettingsIn,
    UserOut,
)
from shared.db import SavedSearch, User, session

router = APIRouter(prefix="/api", tags=["settings"])
PERSONA_TOKENS = {"ai_ml": "gigsim-dev-token-ai_ml", "fullstack": "gigsim-dev-token-fullstack", "data_analyst": "gigsim-dev-token-data_analyst"}


@router.post("/onboarding", response_model=UserOut)
async def onboarding(body: OnboardingIn, u: User = Depends(current_user)):
    from agent.runner import persona_profile

    with session() as db:
        user = db.get(User, u.id)
        user.persona = body.persona
        user.settings = (user.settings or {}) | body.model_dump(exclude={"gigsim_token", "persona", "marketplace", "categories", "keywords"}) | {
            "autonomy": (user.settings or {}).get("autonomy", "suggest"), "marketplace": body.marketplace}
        user.onboarded = True
        cats = body.categories or (persona_profile(body.persona).get("categories", []) if body.persona != "own" else [])
        if not db.query(SavedSearch).filter_by(user_id=u.id).first():
            for c in cats[:5]:
                db.add(SavedSearch(user_id=u.id, name=c, category=c, interval_minutes=180))
            for k in body.keywords[:5]:
                db.add(SavedSearch(user_id=u.id, name=k, query=k, interval_minutes=180))
    if body.marketplace == "gigsim":
        tok = body.gigsim_token or PERSONA_TOKENS.get(body.persona) or "gigsim-dev-token-reviewer"
        save_account(u.id, "gigsim", {"api_token": tok}, {"label": "GigSim", "persona": body.persona})
    with session() as db:
        return out(db.get(User, u.id))


@router.put("/settings", response_model=UserOut)
def update_settings(body: SettingsIn, u: User = Depends(current_user)):
    with session() as db:
        user = db.get(User, u.id)
        user.settings = (user.settings or {}) | body.model_dump(exclude_none=True)
        return out(user)


@router.get("/searches", response_model=list[SavedSearchOut])
def list_searches(u: User = Depends(current_user)):
    with session() as db:
        return [SavedSearchOut(id=s.id, name=s.name, query=s.query, skills=s.skills, category=s.category, min_budget=s.min_budget,
                               interval_minutes=s.interval_minutes, enabled=s.enabled, last_run_at=s.last_run_at)
                for s in db.query(SavedSearch).filter_by(user_id=u.id)]


@router.post("/searches", response_model=SavedSearchOut)
def add_search(body: SavedSearchIn, u: User = Depends(current_user)):
    with session() as db:
        s = SavedSearch(user_id=u.id, **body.model_dump())
        db.add(s)
        db.flush()
        return SavedSearchOut(id=s.id, last_run_at=None, **body.model_dump())


@router.delete("/searches/{sid}")
def delete_search(sid: int, u: User = Depends(current_user)) -> dict:
    with session() as db:
        return {"deleted": db.query(SavedSearch).filter_by(user_id=u.id, id=sid).delete()}


# ----------------------------------------------------------------------------- memory viewer
@router.get("/memory", response_model=MemoryOut)
def memory(u: User = Depends(current_user)):
    from agent.memory.store import OUTCOME, STYLE, open_store_sync

    with open_store_sync() as st:
        style = [MemoryItem(namespace=STYLE, key=i.key, value=i.value) for i in st.search((STYLE, str(u.id)), limit=100)]
        outcome = [MemoryItem(namespace=OUTCOME, key=i.key, value=i.value) for i in st.search((OUTCOME, str(u.id)), limit=100)]
        edits = len(st.search(("edits", str(u.id)), limit=1000))
    return MemoryOut(style=style, outcome=outcome, edits_logged=edits)


@router.delete("/memory/{namespace}/{key:path}")
def forget(namespace: str, key: str, u: User = Depends(current_user)) -> dict:
    from agent.memory.store import open_store_sync

    if namespace not in ("style", "outcome"):
        raise HTTPException(400, "unknown namespace")
    with open_store_sync() as st:
        st.delete((namespace, str(u.id)), key)
        if namespace == "style":  # forget the evidence too, so the rule is not re-promoted from old edits
            for e in st.search(("edits", str(u.id)), limit=1000):
                pats = [p for p in e.value.get("patterns", []) if p.get("key") != key]
                st.put(("edits", str(u.id)), e.key, e.value | {"patterns": pats})
    return {"deleted": key}


# ----------------------------------------------------------------------------- portfolio
def _owners(u: User) -> list[str]:
    from mcp_servers.portfolio.tools import owners_for

    return owners_for(str(u.id))


@router.get("/portfolio", response_model=list[EvidenceOut])
def portfolio(u: User = Depends(current_user)):
    from rag.index.store import get_index

    excl = set((u.settings or {}).get("excluded_evidence", []))
    seen = {}
    for c in get_index("structured").docs_for(_owners(u)):
        seen.setdefault(c.evidence_id, EvidenceOut(evidence_id=c.evidence_id, type=c.type, title=c.title, project=c.project,
                                                   date=c.date, owner=c.owner, excluded=c.evidence_id in excl))
    return sorted(seen.values(), key=lambda e: (e.type, e.title))


@router.post("/portfolio/upload", response_model=list[EvidenceOut])
async def upload(file: UploadFile = File(...), meta: str = Form("{}"), u: User = Depends(current_user)):
    """Add work in the UI -> incremental re-index (only this document is chunked and embedded)."""
    from rag.index.store import get_index
    from rag.ingest.loaders import load_upload

    if Path(file.filename or "").suffix.lower() not in {".pdf", ".md", ".txt", ".py", ".ts", ".tsx", ".js", ".sql", ".r"}:
        raise HTTPException(415, "supported: pdf, md, txt and code files")
    data = await file.read()
    if len(data) > 5_000_000:
        raise HTTPException(413, "file too large (5 MB max)")
    tmp = Path(tempfile.mkdtemp()) / Path(file.filename).name
    tmp.write_bytes(data)
    try:
        doc = load_upload(tmp, f"user-{u.id}", u.persona or "own", json.loads(meta or "{}"))
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)
    for scheme in ("structured", "contextual", "naive"):
        get_index(scheme).upsert_docs([doc])
    return [EvidenceOut(evidence_id=doc.evidence_id, type=doc.type, title=doc.title, project=doc.project, date=doc.date,
                        owner=doc.owner, excluded=False)]


@router.post("/portfolio/{evidence_id}/exclude", response_model=UserOut)
def exclude(evidence_id: str, excluded: bool = True, u: User = Depends(current_user)):
    """Hide an evidence item from retrieval (own uploads can also be deleted). Regenerating a proposal
    afterwards drops any claim that relied on it, because claim verification no longer finds support."""
    from rag.index.store import get_index

    with session() as db:
        user = db.get(User, u.id)
        ex = set((user.settings or {}).get("excluded_evidence", []))
        ex = ex | {evidence_id} if excluded else ex - {evidence_id}
        user.settings = (user.settings or {}) | {"excluded_evidence": sorted(ex)}
        if excluded and evidence_id.startswith(f"user-{u.id}-"):
            for scheme in ("structured", "contextual", "naive"):
                get_index(scheme).delete_evidence(evidence_id, f"user-{u.id}")
        return out(user)

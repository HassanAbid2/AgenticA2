"""Reviewer login preloaded with a persona (E6). Credentials come from env, never the repo:
REVIEWER_EMAIL / REVIEWER_PASSWORD (defaults are for local dev only)."""

from __future__ import annotations

import os

from shared.db import SavedSearch, User, session
from shared.security import hash_password


def ensure_reviewer() -> int:
    from agent.runner import persona_profile
    from apps.api.auth.token_store import save_account

    email = os.getenv("REVIEWER_EMAIL", "reviewer@gigbid.dev").lower()
    pw = os.getenv("REVIEWER_PASSWORD", "reviewer-local-only")
    persona = os.getenv("REVIEWER_PERSONA", "ai_ml")
    with session() as db:
        u = db.query(User).filter_by(email=email).first()
        if u:
            return u.id
        p = persona_profile(persona)
        u = User(email=email, name="Reviewer", password_hash=hash_password(pw), persona=persona, onboarded=True,
                 settings={"hourly_rate": p["hourly_rate"], "floor_hourly": p["floor_hourly"], "min_fixed": p["min_fixed"],
                           "weekly_connects_budget": 120, "autonomy": "suggest", "marketplace": "gigsim"})
        db.add(u)
        db.flush()
        uid = u.id
        for c in p.get("categories", [])[:3]:
            db.add(SavedSearch(user_id=uid, name=c, category=c, interval_minutes=180))
    save_account(uid, "gigsim", {"api_token": os.getenv("REVIEWER_GIGSIM_TOKEN", "gigsim-dev-token-reviewer")},
                 {"label": "GigSim", "persona": persona})
    return uid

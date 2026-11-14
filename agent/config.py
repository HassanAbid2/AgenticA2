"""Loads agent/config.yaml once; env vars override a few top-level switches."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


@lru_cache
def settings() -> dict:
    cfg = yaml.safe_load((ROOT / "agent" / "config.yaml").read_text(encoding="utf-8"))
    if os.getenv("MODEL_PROFILE"):
        cfg["models"]["profile"] = os.environ["MODEL_PROFILE"]
    if os.getenv("MARKETPLACE_MODE"):
        cfg["marketplace"]["mode"] = os.environ["MARKETPLACE_MODE"]
    if os.getenv("RAG_VARIANT"):
        cfg["rag"]["variant"] = os.environ["RAG_VARIANT"]
    return cfg


def reload():
    settings.cache_clear()
    return settings()


def policy_pack() -> dict:
    return yaml.safe_load((ROOT / settings()["policy"]["pack"]).read_text(encoding="utf-8"))

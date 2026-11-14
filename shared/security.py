"""Secrets, encryption and PII masking.

- OAuth / marketplace tokens are stored Fernet-encrypted (key derived from APP_SECRET_KEY) and are
  never logged.
- Service tokens let the API/worker call our MCP servers as a specific user: "<user_id>.<hmac>".
- mask_pii() is applied to everything that reaches logs, traces and the audit log.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
from functools import lru_cache

from cryptography.fernet import Fernet


def app_secret() -> str:
    s = os.getenv("APP_SECRET_KEY", "")
    if not s or s == "replace_me":
        if os.getenv("APP_ENV", "development") == "production":
            raise RuntimeError("APP_SECRET_KEY must be set in production")
        s = "dev-only-secret-change-me"
    return s


@lru_cache
def _fernet() -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("fernet:" + app_secret()).encode()).digest()))


def encrypt_json(obj: dict) -> str:
    return _fernet().encrypt(json.dumps(obj).encode()).decode()


def decrypt_json(token: str) -> dict:
    return json.loads(_fernet().decrypt(token.encode()))


def service_token(user_id: str | int) -> str:
    sig = hmac.new(app_secret().encode(), f"mcp:{user_id}".encode(), hashlib.sha256).hexdigest()[:32]
    return f"{user_id}.{sig}"


def verify_service_token(token: str) -> str | None:
    uid, _, sig = token.rpartition(".")
    if uid and hmac.compare_digest(service_token(uid), token):
        return uid
    return None


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${dk.hex()}"


def check_password(pw: str, stored: str) -> bool:
    try:
        _, salt, dk = stored.split("$")
        return hmac.compare_digest(hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1).hex(), dk)
    except ValueError:
        return False


# --------------------------------------------------------------------------- PII masking
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE = re.compile(r"(?<![\w-])\+?(?:\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{3,4}(?![\w-])")
CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
HANDLE = re.compile(r"(?i)(telegram|whatsapp|skype)\s*[:@]?\s*@?[\w.+-]{3,}")
SECRET = re.compile(r"(?i)(bearer\s+[\w.-]{8,}|sk-[\w-]{10,}|gsk_[\w]{10,}|(api[_-]?key|token|password)\"?\s*[:=]\s*\"?[^\s\",]{6,})")


SECRET_KEY = re.compile(r"(?i)^(.*_)?(token|access_token|refresh_token|secret|password|authorization|api_key|enc_token)$")


def mask_pii(value):
    if isinstance(value, str):
        v = SECRET.sub("[SECRET]", value)
        v = EMAIL.sub("[EMAIL]", v)
        v = CARD.sub("[CARD]", v)
        v = IBAN.sub("[IBAN]", v)
        v = PHONE.sub("[PHONE]", v)
        return HANDLE.sub(r"\1 [HANDLE]", v)
    if isinstance(value, dict):
        return {k: ("[SECRET]" if SECRET_KEY.match(str(k)) else mask_pii(v))
                for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [mask_pii(v) for v in value]
    return value

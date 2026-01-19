from __future__ import annotations

import hashlib


def normalize_token(token: str) -> str:
    return token.strip()


def token_last4(token: str) -> str:
    cleaned = normalize_token(token)
    return cleaned[-4:] if len(cleaned) >= 4 else cleaned


def hash_token(token: str, salt: str) -> str:
    cleaned = normalize_token(token)
    payload = f"{salt}:{cleaned}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()

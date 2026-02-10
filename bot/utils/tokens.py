from __future__ import annotations

import hashlib
import re

TOKEN_PREFIX_RE = re.compile(r"^(?:token|api\s*token|api|токен|api\s*токен)\s*[:\-–]\s*(.+)$", re.IGNORECASE)
TOKEN_QUOTE_CHARS = "\"'`“”«»"


def normalize_token(token: str) -> str:
    if not token:
        return ""
    cleaned = token.strip().strip(TOKEN_QUOTE_CHARS).strip()
    match = TOKEN_PREFIX_RE.match(cleaned)
    if match:
        cleaned = match.group(1).strip()
    elif ":" in cleaned:
        left, right = cleaned.split(":", 1)
        if "token" in left.lower() or "токен" in left.lower():
            cleaned = right.strip()
    cleaned = cleaned.strip().strip(TOKEN_QUOTE_CHARS).strip()
    cleaned = cleaned.replace("token=", "").replace("Token=", "").replace("TOKEN=", "")
    cleaned = re.sub(r"[\s\u200b\u200c\u200d]+", "", cleaned)
    return cleaned


def mask_token(token: str, head: int = 3, tail: int = 3) -> str:
    cleaned = normalize_token(token)
    if not cleaned:
        return ""
    if len(cleaned) <= head + tail:
        if len(cleaned) <= 2:
            return cleaned
        return f"{cleaned[:1]}…{cleaned[-1:]}"
    return f"{cleaned[:head]}…{cleaned[-tail:]}"


def token_last4(token: str) -> str:
    cleaned = normalize_token(token)
    return cleaned[-4:] if len(cleaned) >= 4 else cleaned


def hash_token(token: str, salt: str) -> str:
    cleaned = normalize_token(token)
    payload = f"{salt}:{cleaned}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()

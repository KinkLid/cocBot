from __future__ import annotations

import re

TAG_PATTERN = re.compile(r"^#[A-Z0-9]{3,12}$")


def normalize_tag(tag: str) -> str:
    tag = tag.strip().upper()
    if not tag.startswith("#"):
        tag = f"#{tag}"
    tag = tag.replace("O", "0")
    return tag


def is_valid_tag(tag: str) -> bool:
    return bool(TAG_PATTERN.match(tag))

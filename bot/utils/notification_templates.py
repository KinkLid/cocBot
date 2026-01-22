from __future__ import annotations

from typing import Iterable

TEMPLATE_PREFIX = "[tmpl:"

TEMPLATE_LABELS = {
    "war_preparation": "🧱 Начало подготовки",
    "war_start": "⚔️ Начало войны",
    "war_end": "🏁 Конец войны",
    "war_reminder": "⏰ Напоминание",
    "cwl_start": "⚔️ Начало войны ЛВК",
    "cwl_end": "🏁 Конец войны ЛВК",
    "cwl_reminder": "⏰ Напоминание ЛВК",
    "capital_start": "🚩 Начало рейдов",
    "capital_end": "🏁 Конец рейдов",
    "capital_reminder": "⏰ Напоминание рейдов",
}

TEMPLATE_OPTIONS = {
    "war": ("war_preparation", "war_start", "war_end", "war_reminder"),
    "cwl": ("cwl_start", "cwl_end", "cwl_reminder"),
    "capital": ("capital_start", "capital_end", "capital_reminder"),
}


def pack_rule_text(template: str | None, description: str | None) -> str:
    text = (description or "").strip()
    if template:
        return f"{TEMPLATE_PREFIX}{template}]{text}"
    return text


def unpack_rule_text(text: str | None) -> tuple[str | None, str]:
    if not text:
        return None, ""
    if text.startswith(TEMPLATE_PREFIX):
        end = text.find("]")
        if end > len(TEMPLATE_PREFIX):
            template = text[len(TEMPLATE_PREFIX) : end]
            description = text[end + 1 :].lstrip()
            return template or None, description
    return None, text


def template_label(template: str | None) -> str:
    if not template:
        return ""
    return TEMPLATE_LABELS.get(template, template)


def template_options(event_type: str) -> Iterable[tuple[str, str]]:
    for key in TEMPLATE_OPTIONS.get(event_type, ()):
        yield key, TEMPLATE_LABELS.get(key, key)

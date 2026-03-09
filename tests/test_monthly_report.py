from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from bot.services.notifications import (
    _aggregate_member_monthly_increments,
    _build_monthly_summary_text,
    _month_bounds,
    _sum_war_star_rows,
)
from bot.keyboards.common import admin_menu_reply
from bot.ui.labels import LABELS


def test_month_bounds_returns_calendar_month_window() -> None:
    start, end = _month_bounds(datetime(2026, 3, 9, 12, 0, tzinfo=timezone.utc))
    assert start == datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)


def test_sum_war_stars_combines_war_and_cwl_and_ignores_other_month() -> None:
    month_start = datetime(2026, 3, 1, tzinfo=timezone.utc)
    month_end = datetime(2026, 4, 1, tzinfo=timezone.utc)
    rows = [
        SimpleNamespace(player_tag="#A", player_name="Alpha", stars=5, war_at=datetime(2026, 3, 2, tzinfo=timezone.utc)),
        SimpleNamespace(player_tag="#A", player_name="Alpha", stars=4, war_at=datetime(2026, 3, 12, tzinfo=timezone.utc)),
        SimpleNamespace(player_tag="#A", player_name="Alpha", stars=99, war_at=datetime(2026, 2, 27, tzinfo=timezone.utc)),
        SimpleNamespace(player_tag="#B", player_name="Beta", stars=3, war_at=datetime(2026, 3, 3, tzinfo=timezone.utc)),
    ]

    result = _sum_war_star_rows(rows, month_start, month_end, current_tags={"#A"}, limit=10)

    assert result == [("Alpha", 9), ("Beta (не в клане)", 3)]


def test_aggregate_monthly_increments_uses_internal_snapshots_not_start_end_delta() -> None:
    month_start = datetime(2026, 3, 1, tzinfo=timezone.utc)
    month_end = datetime(2026, 4, 1, tzinfo=timezone.utc)
    snapshots = [
        SimpleNamespace(player_tag="#A", player_name="Alpha", donations_total=100, captured_at=datetime(2026, 3, 1, tzinfo=timezone.utc)),
        SimpleNamespace(player_tag="#A", player_name="Alpha", donations_total=130, captured_at=datetime(2026, 3, 5, tzinfo=timezone.utc)),
        SimpleNamespace(player_tag="#A", player_name="Alpha", donations_total=10, captured_at=datetime(2026, 3, 8, tzinfo=timezone.utc)),
        SimpleNamespace(player_tag="#A", player_name="Alpha", donations_total=40, captured_at=datetime(2026, 3, 25, tzinfo=timezone.utc)),
    ]

    # Считаем только положительные приращения внутри месяца: +30 и +30 => 60
    result = _aggregate_member_monthly_increments(
        snapshots=snapshots,
        month_start=month_start,
        month_end=month_end,
        value_attr="donations_total",
        current_tags={"#A"},
        limit=10,
    )

    assert result == [("Alpha", 60)]


def test_aggregate_monthly_increments_returns_empty_when_no_data() -> None:
    result = _aggregate_member_monthly_increments(
        snapshots=[],
        month_start=datetime(2026, 3, 1, tzinfo=timezone.utc),
        month_end=datetime(2026, 4, 1, tzinfo=timezone.utc),
        value_attr="capital_contributions_total",
        current_tags=set(),
        limit=10,
    )
    assert result == []


def test_monthly_summary_text_has_three_sections_and_fallbacks() -> None:
    text = _build_monthly_summary_text({"war_stars": [], "capital": [], "donations": []})
    assert "📅 Итоги месяца" in text
    assert "🏆 Лучшие по звёздам" in text
    assert "🏰 Лучшие по столице" in text
    assert "🎁 Лучшие по донатам" in text
    assert "пока нет данных" in text


def test_admin_menu_contains_monthly_report_button() -> None:
    assert "admin_monthly_report" in LABELS
    keyboard = admin_menu_reply().keyboard
    all_texts = [button.text for row in keyboard for button in row]
    assert any("Отчёт за месяц" in text for text in all_texts)

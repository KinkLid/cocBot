from __future__ import annotations

import html
from typing import Iterable


def _truncate(value: str, max_len: int) -> str:
    if len(value) <= max_len:
        return value
    if max_len <= 1:
        return value[:max_len]
    return f"{value[: max_len - 1]}…"


def build_pre_table(
    headers: Iterable[str],
    rows: Iterable[Iterable[str]],
    max_widths: Iterable[int] | None = None,
) -> str:
    header_list = list(headers)
    row_list = [list(row) for row in rows]
    if not row_list:
        return "<pre>нет данных</pre>"
    widths = [len(header) for header in header_list]
    for row in row_list:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))
    if max_widths:
        widths = [min(widths[index], max_widths[index]) for index in range(len(widths))]
    lines = [
        " | ".join(
            header_list[index].ljust(widths[index]) for index in range(len(header_list))
        ),
        "-+-".join("-" * widths[index] for index in range(len(widths))),
    ]
    for row in row_list:
        lines.append(
            " | ".join(
                _truncate(row[index], widths[index]).ljust(widths[index])
                for index in range(len(header_list))
            )
        )
    table = "\n".join(lines)
    return f"<pre>{html.escape(table)}</pre>"

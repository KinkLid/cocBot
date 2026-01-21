from __future__ import annotations

import html
from typing import Iterable


def build_pre_table(
    headers: Iterable[str],
    rows: Iterable[Iterable[str]],
    max_widths: Iterable[int] | None = None,
) -> str:
    header_list = [html.escape(str(header)) for header in headers]
    row_list = [[html.escape(str(value)) for value in row] for row in rows]
    if not row_list:
        return "нет данных"
    lines = [" / ".join(header_list)]
    for row in row_list:
        lines.append("• " + " — ".join(row))
    return "\n".join(lines)

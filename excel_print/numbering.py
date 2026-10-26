"""Consecutive renumbering of the printed rows (applied to the temporary copy only).

After filtering, the original item numbers have gaps (1, 2, 4, 5, 7, …). The printed rows that carry
a number in the index column are renumbered 1, 2, 3, … in print order. Nested numbers follow the
hierarchy: "34.1." becomes "<new number of its parent>.1." and sub-items count from 1 again under
each parent. Rows without a number (headings without numbers, decorative rows) are not touched, and
the original style of each number is kept ("34.1." keeps its trailing dot; a numeric cell stays a
number).
"""

from __future__ import annotations

from .row_filter import numbering_parts


def renumber(items: list[tuple[int, str]]) -> dict[int, tuple[str, int | str]]:
    """items: (row, displayed text of the index cell) for printed body rows, in print order.

    Returns {row: (new display text, value to write)} for rows whose number changes. A whole number
    is written as an int, a nested number as text.
    """
    out: dict[int, tuple[str, int | str]] = {}
    new_path: list[int] = []     # new number of the current item at each depth
    orig_path: list[int] = []    # original number of the current item at each depth
    for row, text in items:
        parsed = numbering_parts(text)
        if not parsed:
            continue
        parts, trailing = parsed
        k = len(parts)
        if k == 1 or len(new_path) < k - 1:
            # top level (or a nested number with no printed parent: count it at the top level)
            nxt = (new_path[0] + 1) if new_path else 1
            new = [nxt] if k == 1 else [nxt] + [1] * (k - 1)
        else:
            same_parent = orig_path[:k - 1] == parts[:k - 1]
            idx = new_path[k - 1] + 1 if same_parent and len(new_path) >= k else 1
            new = new_path[:k - 1] + [idx]
        new_path, orig_path = new, parts
        new_text = ".".join(str(p) for p in new) + trailing
        if new_text != text.strip():
            out[row] = (new_text, new[0] if len(new) == 1 and not trailing else new_text)
    return out

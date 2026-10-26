"""Row filtering by relevance, respecting the table's hierarchy.

A body row is *relevant* when it carries information worth printing:
  * a meaningful value in a filter column (e.g. BX or BY) — blank, 0 and formulas that evaluate to 0
    count as empty unless the user says zero is meaningful;
  * a comment (text in a comment column such as BZ) or an Excel note on any selected cell;
  * an error value (kept so it can be checked);
  * optionally (safer default) a non-zero value in another selected number column.

Formatting alone (fill, bold, larger font, merged cells), a section heading, a row number or a
description (e.g. columns D and E) never makes a row relevant.

Structural rows are kept only when needed: a row that is not relevant itself is printed when it is
an ancestor (parent, grandparent, …) of a relevant row, so a printed sub-item never appears without
its heading. Headings whose whole section is empty are left out together with that section.

Hierarchy, in order of preference:
  1. numbering in the index column: "34.1." belongs to "34";
  2. Excel's row outline levels (grouping): the nearest row above with a lower level;
  3. only if the sheet has no outline levels: formatting (rows styled as headings own the plain rows
     below them).

Rows hidden in the original workbook stay hidden. Every decision gets a reason.
"""

from __future__ import annotations

import re
from collections import Counter

from .columns import index_to_letter
from .model import OptimizeSettings, RowDecision, RowInfo, SheetData

TOTAL_WORDS = re.compile(
    r"\b(grand\s+total|sub-?total|totals?|sum)\b|итог|всего|сумма|gesamt|summe|totaal|totale|общий",
    re.IGNORECASE,
)
COMMENT_WORDS = re.compile(r"comment|remark|note|коммент|примеч|пояснен|замечан|bemerk|kommentar", re.IGNORECASE)
SUBTOTAL_FORMULA = re.compile(r"\b(SUBTOTAL|AGGREGATE)\s*\(", re.IGNORECASE)
RANGE_IN_SUM = re.compile(r"\bSUM\s*\(\s*\$?([A-Z]{1,3})\$?(\d+)\s*:\s*\$?([A-Z]{1,3})\$?(\d+)", re.IGNORECASE)
NUMBERING = re.compile(r"^\s*(\d{1,4}(?:\.[1-9]\d{0,3})*)(\.?)\s*$")   # 7, 34.1., 2.3.1 (not 1.00)


def is_total_formula(formula: str, visible_rows: set[int] | None = None) -> bool:
    """SUBTOTAL/AGGREGATE, or SUM over a vertical range (same column, several rows) of *printed* rows.

    * A horizontal SUM across one row (e.g. =SUM(BM10:BV10)) is an ordinary row calculation.
    * A SUM over rows that are all hidden (a collapsed outline group, e.g. =SUM(BW11:BW117) with
      rows 11–117 hidden) is the visible summary line of that group — in the printed view it is an
      ordinary row, not a total of the printed rows."""
    if not formula:
        return False
    if SUBTOTAL_FORMULA.search(formula):
        return True
    for c1, r1, c2, r2 in RANGE_IN_SUM.findall(formula):
        if c1.upper() != c2.upper() or r1 == r2:
            continue
        lo, hi = sorted((int(r1), int(r2)))
        if visible_rows is None or any(r in visible_rows for r in range(lo, hi + 1)):
            return True
    return False


def numbering_parts(text: str) -> tuple[list[int], str] | None:
    """'34.1.' -> ([34, 1], '.'); '7' -> ([7], ''); anything else -> None."""
    m = NUMBERING.match(text or "")
    if not m:
        return None
    return [int(p) for p in m.group(1).split(".")], m.group(2)


def column_roles(sheet: SheetData, body: list[RowInfo]) -> dict[int, str]:
    """'label' (text on most rows), 'comment' (sparse text, or a header saying 'comment'), 'index'
    (row numbers), 'number' or 'empty' for each selected column."""
    roles = {}
    n = max(len(body), 1)
    header_text = {c: " ".join(r.cell(c).text for r in sheet.rows if r.number in sheet.header_rows) for c in sheet.selected}
    for col in sheet.selected:
        kinds = Counter(r.cell(col).kind for r in body)
        nonempty = n - kinds["empty"]
        if nonempty == 0:
            roles[col] = "comment" if COMMENT_WORDS.search(header_text[col]) else "empty"
            continue
        width = sheet.columns[col].width_chars if col in sheet.columns else 99
        cells = [r.cell(col) for r in body if r.cell(col).kind != "empty"]
        numbering = [c for c in cells if (c.kind in ("number", "zero") and isinstance(c.value, (int, float))
                                          and float(c.value).is_integer() and 0 <= c.value < 10000)
                     or (c.kind == "text" and numbering_parts(c.text))]
        if cells and len(numbering) / len(cells) >= 0.85 and width <= 12:
            roles[col] = "index"   # item numbers such as 1, 2, 2.1, 2.2 (as numbers or text): not data
            continue
        text_share = kinds["text"] / nonempty
        if text_share >= 0.6:
            sparse = nonempty / n < 0.5
            roles[col] = "comment" if sparse or COMMENT_WORDS.search(header_text[col]) else "label"
            continue
        numbers = [r.cell(col).value for r in body if r.cell(col).kind in ("number", "zero")]
        small_ints = [v for v in numbers if isinstance(v, (int, float)) and float(v).is_integer() and 0 <= v < 10000]
        width = sheet.columns[col].width_chars if col in sheet.columns else 99
        if numbers and len(small_ints) / len(numbers) >= 0.9 and width <= 8:
            roles[col] = "index"   # row numbers / item codes: not financial values
        else:
            roles[col] = "number"
    return roles


def _style(row: RowInfo, cols: list[int]) -> tuple[float, bool, bool]:
    filled = [row.cell(c) for c in cols if row.cell(c).kind != "empty"]
    if not filled:
        return (0.0, False, False)
    return (max(c.font_size for c in filled), any(c.bold for c in filled), any(c.fill is not None for c in filled))


def _label(row: RowInfo, cols: list[int], roles: dict[int, str]) -> str:
    for kind in ("label", None):
        for col in cols:
            cell = row.cell(col)
            if (roles.get(col) == kind if kind else cell.kind == "text") and cell.text.strip():
                text = " ".join(cell.text.split())
                return text if len(text) <= 60 else text[:57] + "..."
    return ""


def find_parents(body: list[RowInfo], cols: list[int], index_col: int | None) -> dict[int, int | None]:
    """Parent row of each visible body row (None = top level). See the module docstring."""
    levels = {r.outline_level for r in body}
    use_outline = len(levels) > 1
    styles = Counter(_style(r, cols) for r in body if any(r.cell(c).kind != "empty" for c in cols))
    typical_font, typical_bold, typical_fill = styles.most_common(1)[0][0] if styles else (11.0, False, False)
    heading_fonts = sorted({_style(r, cols)[0] for r in body}, reverse=True)

    def depth(r: RowInfo) -> float:
        if use_outline:
            return r.outline_level
        font, bold, fill = _style(r, cols)
        heading = font > typical_font + 0.4 or (fill and not typical_fill) or (bold and not typical_bold)
        if not heading:
            return 100.0
        return heading_fonts.index(font) if font in heading_fonts else 50.0  # bigger font = higher level

    parents: dict[int, int | None] = {}
    stack: list[tuple[float, int]] = []          # (depth, row) of the open headings
    numbers: dict[tuple[int, ...], int] = {}     # numbering -> row, for "34.1" -> "34"
    for r in body:
        d = depth(r)
        while stack and stack[-1][0] >= d:
            stack.pop()
        parent = stack[-1][1] if stack else None
        parts = numbering_parts(r.cell(index_col).text)[0] if index_col and numbering_parts(r.cell(index_col).text) else None
        if parts and len(parts) > 1 and tuple(parts[:-1]) in numbers:
            parent = numbers[tuple(parts[:-1])]
        if parts:
            numbers[tuple(parts)] = r.number
        parents[r.number] = parent
        if any(r.cell(c).kind != "empty" for c in cols):   # an empty spacer row is nobody's heading
            stack.append((d, r.number))
    return parents


def decide_rows(sheet: SheetData, filter_cols: list[int], settings: OptimizeSettings) -> list[RowDecision]:
    cols = sheet.selected
    header = set(sheet.header_rows)
    body = [r for r in sheet.rows if not r.hidden and r.number not in header]
    roles = column_roles(sheet, body)
    filter_names = ", ".join(index_to_letter(c) for c in filter_cols)
    other_numeric = [c for c in cols if c not in filter_cols and roles.get(c) == "number"]
    comment_cols = [c for c in cols if roles.get(c) == "comment" and c not in filter_cols]
    index_cols = [c for c in cols if roles.get(c) == "index"]
    visible_numbers = {r.number for r in sheet.rows if not r.hidden}

    def meaningful(kind: str) -> bool:
        return kind in ("number", "text", "error") or (kind == "zero" and not settings.zero_is_empty)

    parents = find_parents(body, cols, index_cols[0] if index_cols else None)
    first: dict[int, RowDecision] = {}     # provisional decision for every body row
    relevant: set[int] = set()
    for row in body:
        label = _label(row, cols, roles)
        kinds = {c: row.cell(c).kind for c in dict.fromkeys(cols + list(filter_cols))}   # filter columns may be unprinted
        if all(k == "empty" for k in kinds.values()) and not any(row.cell(c).note for c in cols):
            first[row.number] = RowDecision(row.number, False, "empty", "Empty in all selected columns.", label=label)
            continue
        errors = [index_to_letter(c) for c, k in kinds.items() if k == "error"]
        has_values = [index_to_letter(c) for c in filter_cols if meaningful(kinds[c])]
        has_comment = sorted({index_to_letter(c) for c in comment_cols if kinds[c] != "empty"}
                             | {index_to_letter(c) for c in cols if row.cell(c).note})
        other = [index_to_letter(c) for c in other_numeric if kinds[c] == "number"]
        texts = " ".join(row.cell(c).text for c in cols if kinds[c] == "text")
        is_total = bool(TOTAL_WORDS.search(texts)) or any(is_total_formula(row.cell(c).formula, visible_numbers)
                                                          for c in filter_cols + other_numeric)
        if errors:
            d = RowDecision(row.number, True, "error", f"Kept: error value in {', '.join(errors)} — check the source.",
                            uncertain=True, label=label)
        elif has_values:
            d = RowDecision(row.number, True, "total" if is_total else "values",
                            f"Has values in {', '.join(has_values)}." + (" (total/subtotal row)" if is_total else ""), label=label)
        elif has_comment:
            d = RowDecision(row.number, True, "comment",
                            f"Kept: {filter_names} empty or zero, but there is a comment in {', '.join(has_comment)}.", label=label)
        elif other and settings.keep_rows_with_other_values:
            d = RowDecision(row.number, True, "other-values",
                            f"Kept: {filter_names} are empty or zero, but {', '.join(other)} has a value.",
                            uncertain=True, label=label)
        else:
            zero = " or zero" if settings.zero_is_empty else ""
            if is_total:
                reason = f"Total/subtotal row, but {filter_names} are empty{zero} — nothing to total."
            else:
                reason = f"{filter_names} {'are' if len(filter_cols) > 1 else 'is'} empty{zero} and there is no comment."
            uncertain = bool(other)  # excluded although another selected column has a value
            if uncertain:
                reason += f" Note: {', '.join(other)} has a value (keeping such rows is switched off)."
            d = RowDecision(row.number, False, "filtered", reason, uncertain=uncertain, label=label)
        first[row.number] = d
        if d.keep:
            relevant.add(row.number)

    # Keep every ancestor of a relevant row (no orphaned sub-items); count what each heading carries.
    needed_by: Counter = Counter()
    for r in relevant:
        p = parents.get(r)
        seen = set()
        while p is not None and p not in seen:
            seen.add(p)
            needed_by[p] += 1
            p = parents.get(p)
    children = Counter(p for p in parents.values() if p is not None)
    for r, n in needed_by.items():
        d = first[r]
        if not d.keep:
            first[r] = RowDecision(r, True, "parent",
                                   f"Kept as heading: {n} printed row(s) below it belong to it ({d.reason})", label=d.label)
    for r, d in first.items():
        d.parent = parents.get(r)
        d.has_printed_children = needed_by[r] > 0
        if not d.keep and d.category == "filtered" and children[r]:
            d.category = "empty-section"
            d.reason = f"Heading of a section with no relevant rows: {d.reason}"

    decisions: list[RowDecision] = []
    for row in sheet.rows:
        if row.hidden:
            decisions.append(RowDecision(row.number, False, "hidden", "Hidden in the original workbook (left hidden).",
                                         label=_label(row, cols, roles)))
        elif row.number in header:
            decisions.append(RowDecision(row.number, True, "header", "Table header (repeated on every page).",
                                         label=_label(row, cols, roles)))
        else:
            decisions.append(first[row.number])
    return decisions

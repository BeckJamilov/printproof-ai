"""Page fitting: choose orientation, text-column widths and print scale (zoom).

Works on geometry measured by Excel at 100 % scale (column widths and row heights in points).
Effective printed font size = font size × zoom / 100, so a 12 pt cell printed at 50 % is 6 pt.

* Readability First: find the smallest page count at which the minimum effective font size is
  still met, then use the largest zoom that keeps that page count.
* Page Count First: use the largest zoom that fits within the page limit; explain when impossible.

All columns are always printed one page wide (never split across pages horizontally).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

PAPER_PT = {"A3": (841.89, 1190.55), "A4": (595.28, 841.89)}  # portrait width, height
MARGINS_IN = {  # left/right, top, bottom, footer (inches)
    # compact: the smallest margins we consider safe for office printers (6–11 mm, footer 6 mm from
    # the edge); most printers cannot print closer than 4–5 mm to the edge.
    "compact": (0.25, 0.25, 0.45, 0.25),
    "narrow": (0.25, 0.4, 0.4, 0.2),
    "normal": (0.5, 0.6, 0.6, 0.3),
}
SAFE_EDGE_MM = 5.0                # verified in the PDF: nothing printed closer than this to an edge
ZOOM_MIN, ZOOM_MAX = 10, 120      # Excel allows 10–400 %; we never enlarge beyond 120 %
WIDTH_SAFETY = 0.985              # Excel's scaled column widths are rounded to pixels
HEIGHT_SAFETY = 0.985             # ...and so are printed row heights
SMALL_FONT_PT, TINY_FONT_PT = 6.0, 4.0


@dataclass
class Geometry:
    """One candidate arrangement, measured in Excel at 100 % scale."""

    name: str
    orientation: str                 # 'landscape' or 'portrait'
    col_widths_pt: dict[int, float]
    header_heights_pt: list[float]   # rows repeated at the top of every page
    body_rows: list[int]             # row numbers in print order
    body_heights_pt: list[float]
    keep_with_next: list[bool]       # e.g. section headings must not end a page
    text_widths_chars: dict[int, float] = field(default_factory=dict)

    @property
    def total_width(self) -> float:
        return sum(self.col_widths_pt.values())


@dataclass
class Plan:
    feasible: bool
    zoom: int = 0
    pages: int = 0
    geometry: Geometry | None = None
    page_starts: list[int] = field(default_factory=list)   # row numbers that start pages 2..n
    effective_font_pt: float = 0.0
    explanation: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def printable_area(paper: str, orientation: str, margins: str) -> tuple[float, float]:
    w, h = PAPER_PT[paper]
    if orientation == "landscape":
        w, h = h, w
    lr, top, bottom, _ = MARGINS_IN[margins]
    return w - 2 * lr * 72, h - (top + bottom) * 72


def paginate(heights: list[float], keep_next: list[bool], first_capacity: float,
             capacity: float) -> list[int] | None:
    """Indexes of rows that start a new page, or None if a single row is taller than a page.

    Rows are never split. A row flagged keep-with-next is moved to the next page together with the
    row that follows it when that row does not fit.
    """
    starts: list[int] = []
    used, cap = 0.0, first_capacity
    i, n = 0, len(heights)
    while i < n:
        h = heights[i]
        if h > capacity + 0.01:
            return None
        if used + h <= cap + 0.01:
            # keep-with-next: if this row fits but the next one does not, move both
            if keep_next[i] and i + 1 < n and used > 0 and used + h + heights[i + 1] > cap + 0.01 \
                    and h + heights[i + 1] <= capacity:
                starts.append(i)
                used, cap = 0.0, capacity
                continue
            used += h
            i += 1
        else:
            starts.append(i)
            used, cap = 0.0, capacity
    return starts


def pages_at(geom: Geometry, zoom: int, paper: str, margins: str, repeat_header: bool,
             safety: bool = True) -> tuple[int, list[int]] | None:
    """Predicted page count and page-start rows at a zoom (None if the columns are too wide or a row
    is taller than a page). safety=False predicts without the rounding allowance — used only to
    place page breaks for a candidate that is then checked in the real PDF."""
    pw, ph = printable_area(paper, geom.orientation, margins)
    s = zoom / 100
    ws, hs = (WIDTH_SAFETY, HEIGHT_SAFETY) if safety else (1.0, 1.0)
    if geom.total_width * s > pw * ws:
        return None
    header = sum(geom.header_heights_pt)
    first = ph * hs / s - header
    later = ph * hs / s - (header if repeat_header else 0)
    if first <= 0 or later <= 0:
        return None
    starts = paginate(geom.body_heights_pt, geom.keep_with_next, first, later)
    if starts is None:
        return None
    return len(starts) + 1, [geom.body_rows[i] for i in starts]


def max_width_zoom(geom: Geometry, paper: str, margins: str, safety: bool = True) -> int:
    pw, _ = printable_area(paper, geom.orientation, margins)
    if geom.total_width <= 0:
        return ZOOM_MAX
    return max(0, min(ZOOM_MAX, math.floor(100 * pw * (WIDTH_SAFETY if safety else 1.0) / geom.total_width)))


def _best_zoom(geom: Geometry, lo: int, hi: int, page_limit: int, paper: str, margins: str,
               repeat_header: bool) -> tuple[int, int, list[int]] | None:
    """Largest zoom in [lo, hi] whose page count is <= page_limit."""
    for z in range(hi, lo - 1, -1):
        res = pages_at(geom, z, paper, margins, repeat_header)
        if res and res[0] <= page_limit:
            return z, res[0], res[1]
    return None


def font_warnings(effective: float) -> list[str]:
    if effective < TINY_FONT_PT:
        return [f"Printed text is extremely small ({effective:.1f} pt). It may be hard to read even on A3."]
    if effective < SMALL_FONT_PT:
        return [f"Printed text is small ({effective:.1f} pt)."]
    return []


def plan_readability(geoms: list[Geometry], base_font: float, min_font: float, paper: str,
                     margins: str, repeat_header: bool, max_pages_search: int = 200) -> Plan:
    z_min = max(ZOOM_MIN, math.ceil(100 * min_font / base_font - 1e-9))
    if z_min > ZOOM_MAX:
        return Plan(False, explanation=[f"A {min_font:g} pt minimum needs {z_min} % scale for {base_font:g} pt text, "
                                        f"more than the {ZOOM_MAX} % allowed."])
    options, reasons = [], []
    for g in geoms:
        zw = max_width_zoom(g, paper, margins)
        if zw < z_min:
            reasons.append(f"{g.name} ({g.orientation}): the selected columns are too wide — at {min_font:g} pt "
                           f"they need {g.total_width * z_min / 100 / 72:.1f} in but the page allows "
                           f"{printable_area(paper, g.orientation, margins)[0] / 72:.1f} in.")
            continue
        res = pages_at(g, z_min, paper, margins, repeat_header)
        if res is None:
            reasons.append(f"{g.name} ({g.orientation}): a single row is taller than a page at {min_font:g} pt.")
            continue
        options.append((g, zw, res[0]))
    if not options:
        return Plan(False, explanation=reasons or ["No layout satisfies the minimum font size."])
    fewest = min(p for _, _, p in options)
    if fewest > max_pages_search:
        return Plan(False, explanation=[f"The selection would need {fewest} pages."])
    best: Plan | None = None
    for g, zw, p in options:
        if p != fewest:
            continue
        found = _best_zoom(g, z_min, zw, fewest, paper, margins, repeat_header)
        if not found:
            continue
        z, pages, starts = found
        cand = Plan(True, z, pages, g, starts, base_font * z / 100)
        if best is None or z > best.zoom:
            best = cand
    if best is None:
        return Plan(False, explanation=reasons or ["No layout satisfies the minimum font size."])
    best.explanation.append(
        f"Smallest page count that keeps every text at least {min_font:g} pt: {best.pages}. "
        f"Within {best.pages} page(s) the largest scale that fits is {best.zoom} %, so text prints at "
        f"{best.effective_font_pt:.1f} pt (layout “{best.geometry.name}”, {best.geometry.orientation}).")
    best.warnings += font_warnings(best.effective_font_pt)
    return best


def plan_page_count(geoms: list[Geometry], base_font: float, max_pages: int, paper: str, margins: str,
                    repeat_header: bool) -> Plan:
    best: Plan | None = None
    needed: list[str] = []
    for g in geoms:
        zw = max_width_zoom(g, paper, margins)
        if zw < ZOOM_MIN:
            needed.append(f"{g.name} ({g.orientation}): columns too wide even at {ZOOM_MIN} %.")
            continue
        found = _best_zoom(g, ZOOM_MIN, zw, max_pages, paper, margins, repeat_header)
        if not found:
            res = pages_at(g, ZOOM_MIN, paper, margins, repeat_header)
            if res:
                needed.append(f"{g.name} ({g.orientation}): needs {res[0]} pages even at {ZOOM_MIN} % "
                              f"({base_font * ZOOM_MIN / 100:.1f} pt text).")
            continue
        z, pages, starts = found
        cand = Plan(True, z, pages, g, starts, base_font * z / 100)
        if best is None or z > best.zoom:
            best = cand
    if best is None:
        return Plan(False, explanation=[f"The selection cannot fit on {max_pages} page(s) without cutting off "
                                        "content or going below Excel's 10 % minimum scale."] + needed)
    best.explanation.append(
        f"Largest scale that fits within {max_pages} page(s): {best.zoom} % on {best.pages} page(s), so text prints "
        f"at {best.effective_font_pt:.1f} pt (layout “{best.geometry.name}”, {best.geometry.orientation}).")
    best.warnings += font_warnings(best.effective_font_pt)
    return best


TEXT_CAPS = (("one line", 250), ("very wide text", 160), ("wider text", 120), ("wide text", 100), ("roomy", 85),
             ("medium-wide", 70), ("balanced", 60), ("medium", 50), ("compact", 42), ("narrow text", 30))


def widths_for_cap(natural_chars: dict[int, float], min_chars: dict[int, float], cap: float) -> dict[int, float]:
    """Each long-text column gets min(natural width, cap), never below the width of its longest word."""
    return {c: round(max(min_chars.get(c, 8), min(n, cap)), 1) for c, n in natural_chars.items()}


def text_width_profiles(natural_chars: dict[int, float], min_chars: dict[int, float],
                        caps=TEXT_CAPS) -> list[tuple[str, dict[int, float]]]:
    """Candidate widths (in Excel character units) for long-text columns, widest first.

    Wider text columns need fewer wrapped lines (a shorter table); narrower ones make the table less
    wide. Which one allows the largest print scale depends on the page shape, so all are measured and
    compared (and the best one is refined between its neighbours).
    """
    profiles, seen = [], set()
    for name, cap in caps:
        widths = widths_for_cap(natural_chars, min_chars, cap)
        key = tuple(sorted(widths.items()))
        if key not in seen:
            seen.add(key)
            profiles.append((name, widths))
    return profiles


def balanced_starts(heights: list[float], keep_next: list[bool], first_capacity: float, capacity: float,
                    pages: int) -> list[int] | None:
    """Indexes of rows that start pages 2..n when the rows are spread evenly over exactly `pages` pages
    (the tallest page as short as possible) — instead of filling pages from the top and leaving one or
    two rows (e.g. an isolated grand total) for the last page. A row flagged keep-with-next never ends a
    page. None if no such split exists."""
    if pages <= 1 or not heights:
        return []

    def pack(limit: float) -> list[int] | None:
        starts, used, cap = [], 0.0, min(first_capacity, limit)
        for i, h in enumerate(heights):
            if used + h > cap + 0.01 and used > 0:
                j = i
                while j > 0 and keep_next[j - 1] and (not starts or j - 1 > starts[-1]):
                    j -= 1                       # do not leave a heading alone at the bottom of a page
                if starts and j <= starts[-1] or j == 0:
                    j = i
                starts.append(j)
                used = sum(heights[j:i])
                cap = min(capacity, limit)
                if used + h > cap + 0.01:
                    return None
            used += h
            if h > cap + 0.01:
                return None
        return starts if len(starts) + 1 <= pages else None

    lo, hi = max(heights), max(first_capacity, capacity)
    if pack(hi) is None:
        return None
    for _ in range(40):
        mid = (lo + hi) / 2
        if pack(mid) is None:
            lo = mid
        else:
            hi = mid
    starts = pack(hi)
    return starts if starts is not None and len(starts) + 1 == pages else None

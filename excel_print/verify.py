"""Verify an exported PDF: what was printed, at what size, on which paper.

Measured: page size/orientation, page count, effective font size of every text span, presence of
every expected value/comment/heading, Excel's '###' overflow marks, text outside the page, and the
printed area (content box and unused margins, from the text and the drawn cell borders/fills).
Not measured (reported as such): colours, borders, exact visual appearance.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from dataclasses import dataclass

import numpy as np
import pymupdf

from .layout import PAPER_PT, SAFE_EDGE_MM
from .model import VerificationCheck

FOOTER = re.compile(r"^\s*Page \d+ of \d+\s*$")
SIZE_TOLERANCE_PT = 2.0


@dataclass
class ExpectedText:
    ref: str        # e.g. "BZ118"
    text: str
    kind: str       # value / comment / header / label


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text.replace(" ", " ")).casefold()


def _words(text: str) -> list[str]:
    return [w.casefold() for w in re.split(r"\s+", text.replace(" ", " ")) if w]


def content_box(page: pymupdf.Page) -> pymupdf.Rect | None:
    """Box around everything printed on the page except the page-number footer."""
    box = pymupdf.Rect()
    pw, ph = page.rect.width, page.rect.height
    for d in page.get_drawings():
        r = d["rect"]
        if r.width >= pw - 1 and r.height >= ph - 1:   # a page-sized background, not content
            continue
        box |= r
    for b in page.get_text("dict")["blocks"]:
        for line in b.get("lines", []):
            text = "".join(sp["text"] for sp in line["spans"])
            if text.strip() and not FOOTER.match(text):
                box |= pymupdf.Rect(line["bbox"])
    return None if box.is_empty else box


def horizontal_rules(page: pymupdf.Page) -> list[tuple[float, float, float]]:
    """Thin horizontal lines drawn on the page (cell borders): (y, x0, x1)."""
    rules = []
    for d in page.get_drawings():
        for item in d["items"]:
            if item[0] == "l":
                p1, p2 = item[1], item[2]
                if abs(p1.y - p2.y) < 0.3 and abs(p2.x - p1.x) > 2:
                    rules.append(((p1.y + p2.y) / 2, min(p1.x, p2.x), max(p1.x, p2.x)))
            elif item[0] == "re":
                r = item[1]
                if r.height <= 1.6 and r.width > 2:
                    rules.append(((r.y0 + r.y1) / 2, r.x0, r.x1))
    return rules


def cut_text_lines(page: pymupdf.Page, rules=None) -> list[str]:
    """Text lines crossed by a cell border through the body of the letters — text that the cell cuts
    off (the PDF still contains it, so a plain text search would not notice)."""
    rules = horizontal_rules(page) if rules is None else rules
    cut = []
    for b in page.get_text("dict")["blocks"]:
        for line in b.get("lines", []):
            for span in line["spans"]:
                text = span["text"].strip()
                if not text or FOOTER.match(text):
                    continue
                base, size = span["origin"][1], span["size"]
                x0, x1 = span["bbox"][0], span["bbox"][2]
                top, bottom = base - 0.68 * size, base - 0.08 * size   # the letters' body (x-height/cap area)
                for y, rx0, rx1 in rules:
                    if top < y < bottom and min(x1, rx1) - max(x0, rx0) > 0.5 * (x1 - x0):
                        cut.append(text)
                        break
    return cut


def hidden_text(page: pymupdf.Page, dpi: int = 110, skipped: list | None = None) -> list[str]:
    """Text that is in the PDF but not (fully) visible: Excel clips text to its cell, yet the clipped
    letters stay in the file. A span counts as cut when its letter bodies have no ink over a large part
    of its width (cut at the side) or of its height (cut at the top or bottom of the cell)."""
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False, annots=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)[:, :pix.width * 3]
    dark = img.reshape(pix.height, pix.width, 3).min(axis=2) < 110          # black or coloured text
    k = dpi / 72
    out = []
    for b in page.get_text("rawdict")["blocks"]:
        for line in b.get("lines", []):
            for sp in line["spans"]:
                chars = [c for c in sp.get("chars", []) if c["c"].strip()]
                text = "".join(c["c"] for c in sp.get("chars", []))
                if len(chars) < 3 or FOOTER.match(text):
                    continue
                x0 = min(c["bbox"][0] for c in chars)
                x1 = max(c["bbox"][2] for c in chars)
                base, size = sp["origin"][1], sp["size"]
                y0, y1 = base - 0.68 * size, base - 0.08 * size
                r = dark[max(int(y0 * k), 0):max(int(y1 * k), int(y0 * k) + 1), max(int(x0 * k), 0):max(int(x1 * k), int(x0 * k) + 1)]
                if r.size == 0 or size * k < 8:          # too small to judge at this resolution
                    if skipped is not None:
                        skipped.append(text.strip())
                    continue
                cols = r.any(axis=0)
                if not cols.any():
                    out.append(text.strip())
                    continue
                first, last = int(np.argmax(cols)), int(len(cols) - 1 - np.argmax(cols[::-1]))
                blank_side = max(first, len(cols) - 1 - last) / k
                # top edge: capitals/digits reach ~0.68 em above the baseline, lowercase ~0.45 em
                tall = any(ch.isupper() or ch.isdigit() for ch in text)
                top = base - (0.62 if tall else 0.40) * size
                t0, l0 = int(top * k), int((base - 0.18 * size) * k)
                band_top = dark[max(t0, 0):max(int((top + 0.14 * size) * k), t0 + 2), int(x0 * k):int(x1 * k) + 1]
                band_low = dark[max(l0, 0):max(int((base - 0.03 * size) * k), l0 + 2), int(x0 * k):int(x1 * k) + 1]
                cut_top = band_top.size and not band_top.any()   # no letter reaches its normal top: cut at the top
                cut_low = band_low.size and not band_low.any()   # no letter reaches the baseline: cut at the bottom
                if blank_side > max(4 * size, 0.35 * (x1 - x0)) or cut_top or cut_low:
                    out.append(text.strip())
    return out


def layout_stats(doc: pymupdf.Document) -> dict:
    """Measured use of the first page: table/content size and the unused space around it (mm)."""
    page = doc[0]
    box = content_box(page)
    if box is None:
        return {}
    mm = 25.4 / 72
    pw, ph = page.rect.width, page.rect.height
    return {"content_width_mm": round(box.width * mm, 1), "content_height_mm": round(box.height * mm, 1),
            "margin_left_mm": round(box.x0 * mm, 1), "margin_right_mm": round((pw - box.x1) * mm, 1),
            "margin_top_mm": round(box.y0 * mm, 1), "margin_bottom_mm": round((ph - box.y1) * mm, 1),
            "page_area_used_percent": round(100 * box.width * box.height / (pw * ph), 1)}


def verify_pdf(pdf_bytes: bytes, paper: str, orientation: str, expected_pages: int | None,
               expected: list[ExpectedText], min_font_pt: float | None,
               page_limit: int | None = None) -> tuple[list[VerificationCheck], dict]:
    checks: list[VerificationCheck] = []
    stats: dict = {}
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:  # broken output from the renderer
        return [VerificationCheck("PDF can be opened", False, f"The exported file is not a valid PDF ({exc}).")], stats
    with doc:
        n = doc.page_count
        stats["pages"] = n
        if n == 0:
            return [VerificationCheck("PDF has pages", False, "The PDF has no pages.")], stats

        # 1. Paper size and orientation
        w, h = PAPER_PT[paper]
        if orientation == "landscape":
            w, h = h, w
        wrong = [p.number + 1 for p in doc if abs(p.rect.width - w) > SIZE_TOLERANCE_PT or abs(p.rect.height - h) > SIZE_TOLERANCE_PT]
        first = doc[0].rect
        checks.append(VerificationCheck(
            f"Paper is {paper} {orientation}", not wrong,
            f"All pages {first.width:.0f} × {first.height:.0f} pt ({first.width / 72 * 25.4:.0f} × {first.height / 72 * 25.4:.0f} mm)."
            if not wrong else f"Pages with a different size: {wrong[:10]}"))

        # 2. Page count
        if expected_pages is not None:
            checks.append(VerificationCheck("Page count as planned", n == expected_pages,
                                            f"{n} page(s); planned {expected_pages}."))
        if page_limit is not None:
            checks.append(VerificationCheck(f"At most {page_limit} page(s)", n <= page_limit,
                                            f"{n} page(s) in the PDF; limit {page_limit}."))

        # Printed area and safe distance from the paper edges
        stats.update(layout_stats(doc))
        too_close = []
        for page in doc:
            box = content_box(page)
            if box is None:
                continue
            edge = min(box.x0, box.y0, page.rect.width - box.x1, page.rect.height - box.y1) * 25.4 / 72
            if edge < SAFE_EDGE_MM - 0.05:
                too_close.append(f"page {page.number + 1}: {edge:.1f} mm")
        boxes = [content_box(pg) for pg in doc]
        heights = [bx.height if bx else 0.0 for bx in boxes]
        stats["page_fill"] = [round(h / max(heights), 3) if max(heights) else 0.0 for h in heights]
        widths = [bx.width for bx in boxes if bx]
        if n > 1 and widths:
            split = [i + 1 for i, bx in enumerate(boxes) if bx and bx.width < 0.8 * max(widths)]
            checks.append(VerificationCheck("Table not split across pages horizontally", not split,
                                            "Every page shows the full table width." if not split else
                                            f"Page(s) {split} show only part of the table width (columns split across pages)."))
        if "margin_left_mm" in stats:
            checks.append(VerificationCheck(
                f"Safe margins (table at least {SAFE_EDGE_MM:g} mm from every paper edge)", not too_close,
                (f"Page 1: left {stats['margin_left_mm']} mm, right {stats['margin_right_mm']} mm, top "
                 f"{stats['margin_top_mm']} mm, bottom {stats['margin_bottom_mm']} mm (to the table, footer excluded)."
                 if not too_close else "Too close to the edge: " + "; ".join(too_close[:5]))))

        # 3. Text, sizes, overflow, out-of-page
        sizes: list[float] = []
        page_texts: list[str] = []
        overflow, outside = [], []
        for page in doc:
            page_texts.append(page.get_text("text"))
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        t = span["text"]
                        if not t.strip() or FOOTER.match(t):
                            continue
                        sizes.append(round(span["size"], 2))
                        if "###" in t:
                            overflow.append(page.number + 1)
                        b = pymupdf.Rect(span["bbox"])
                        if b.x0 < -1 or b.y0 < -1 or b.x1 > page.rect.width + 1 or b.y1 > page.rect.height + 1:
                            outside.append(page.number + 1)
        if sizes:
            stats["min_font_pt"] = min(sizes)
            stats["median_font_pt"] = statistics.median(sizes)
            stats["font_sizes"] = dict(Counter(round(s, 1) for s in sizes).most_common(6))
            if min_font_pt is not None:
                ok = min(sizes) >= min_font_pt - 0.05
                checks.append(VerificationCheck(
                    f"Effective printed text ≥ {min_font_pt:g} pt", ok,
                    f"Measured in the PDF: smallest {min(sizes):.2f} pt, typical {stats['median_font_pt']:.2f} pt."))
            else:
                checks.append(VerificationCheck("Effective printed text size measured", True,
                                                f"Smallest {min(sizes):.2f} pt, typical {stats['median_font_pt']:.2f} pt."))
        else:
            checks.append(VerificationCheck("Text found in PDF", False, "No text could be extracted from the PDF."))

        # Text cut off by its cell (row too low for the wrapped text at this print scale)
        cut: list[str] = []
        has_rules = False
        for page in doc:
            rules = horizontal_rules(page)
            has_rules = has_rules or bool(rules)
            cut += cut_text_lines(page, rules)
        invisible: list[str] = []
        ink_dpi = int(min(300, max(110, 110 * 8 / max(stats.get("min_font_pt") or 8, 1))))   # small text: more pixels
        too_small: list[str] = []
        for page in doc:
            invisible += hidden_text(page, dpi=ink_dpi, skipped=too_small)
        measured = sum(len(page.get_text("words")) > 0 for page in doc)
        if invisible:
            checks.append(VerificationCheck("All printed text fully visible (not clipped by its cell)", False,
                                            f"{len(invisible)} text line(s) partly hidden by their cell, e.g. “{invisible[0][:60]}”."))
        elif too_small and len(too_small) * 2 > len(sizes):
            checks.append(VerificationCheck("All printed text fully visible (not clipped by its cell)", None,
                                            f"Not measurable: {len(too_small)} text line(s) are too small to check in the rendered page."))
        else:
            checks.append(VerificationCheck("All printed text fully visible (not clipped by its cell)", True,
                                            "Every text line is fully drawn."
                                            + (f" ({len(too_small)} very small line(s) could not be checked.)" if too_small else "")))
        cut += [t for t in invisible if t not in cut]
        if has_rules:
            checks.append(VerificationCheck(
                "No text cut off at cell borders", not [c for c in cut if c not in invisible],
                "No text line is crossed by a cell border." if not cut else
                f"{len(cut)} text line(s) cut by a cell border, e.g. “{cut[0][:50]}”."))
        else:
            checks.append(VerificationCheck("No text cut off at cell borders", None,
                                            "Not measurable: the table has no drawn cell borders."))
        stats["cut_lines"] = cut

        checks.append(VerificationCheck("No ‘###’ (number too wide for its column)", not overflow,
                                        "None found." if not overflow else f"Found on page(s) {sorted(set(overflow))}."))
        checks.append(VerificationCheck("No text outside the page", not outside,
                                        "None found." if not outside else f"Text beyond the page edge on page(s) {sorted(set(outside))}."))

        # 4. Every expected value / comment / heading is present
        all_norm = _norm("".join(page_texts))
        all_words = Counter(w for t in page_texts for w in _words(t))
        missing: list[ExpectedText] = []
        for e in expected:
            target = _norm(e.text)
            if not target or target in all_norm:
                continue
            need = Counter(_words(e.text))
            if all(all_words[w] >= c for w, c in need.items()):
                continue  # words present but broken across lines/cells differently
            missing.append(e)
        by_kind = Counter(e.kind for e in expected)
        miss_kind = Counter(e.kind for e in missing)
        summary = ", ".join(f"{by_kind[k] - miss_kind[k]}/{by_kind[k]} {k}s" for k in sorted(by_kind))
        checks.append(VerificationCheck(
            "All selected values, headings and comments are printed (nothing clipped)", not missing,
            f"Found {summary}." if not missing else
            f"Missing or cut off: " + "; ".join(f"{m.ref} ({m.kind})" for m in missing[:8])
            + (f" and {len(missing) - 8} more" if len(missing) > 8 else "") + "."))
        stats["missing"] = [m.ref for m in missing]
        # Which cells the cut-off lines belong to (so the optimizer can make those rows taller)
        cut_refs = []
        for line in cut:
            key = _norm(line)
            refs = [e.ref for e in expected if key and key in _norm(e.text)]
            if 0 < len(refs) <= 3:
                cut_refs += refs
        stats["cut_refs"] = sorted(set(cut_refs))

        checks.append(VerificationCheck("Colours, borders and fills", None,
                                        "Not measured — they come from Excel's own rendering of the workbook formatting."))
    return checks, stats


def render_previews(pdf_bytes: bytes, max_pages: int = 4, zoom: float = 0.8) -> list[bytes]:
    out = []
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page in list(doc)[:max_pages]:
            out.append(page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).tobytes("png"))
    return out

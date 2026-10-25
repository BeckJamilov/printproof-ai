"""PDF checking logic for PrintProof AI.

This module reads a real PDF with PyMuPDF and compares it with the requirements
the user selected. Every check returns one of three statuses:

- PASS          the PDF clearly meets the requirement
- FAIL          the PDF clearly breaks the requirement (with measurements and pages)
- NEEDS_REVIEW  the PDF could not be measured reliably, so we do not guess

All measurements use PDF points internally (72 points = 1 inch).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pymupdf

PASS = "Pass"
FAIL = "Fail"
NEEDS_REVIEW = "Needs Review"

POINTS_PER_INCH = 72.0
MM_PER_INCH = 25.4

# Standard paper sizes in points (portrait width, height).
PAPER_SIZES = {
    "US Letter": (612.0, 792.0),
    "A4": (595.28, 841.89),
    "US Legal": (612.0, 1008.0),
    "A3": (841.89, 1190.55),
    "A5": (419.53, 595.28),
    "Tabloid": (792.0, 1224.0),
}

# Small tolerances so rounding inside PDF files does not cause false failures.
PAPER_TOLERANCE_PT = 3.0  # about 1 mm
FONT_TOLERANCE_PT = 0.05
MARGIN_TOLERANCE_PT = 0.5

# A page whose images cover this share of the page is treated as a scan/picture.
SCANNED_PAGE_IMAGE_SHARE = 0.85
# Drawings this large are usually page backgrounds, not content.
BACKGROUND_DRAWING_SHARE = 0.95


class PDFCheckError(Exception):
    """Raised when the uploaded file cannot be opened as a usable PDF."""


@dataclass
class Requirements:
    """Requirements chosen by the user. Use None to skip a check."""

    max_pages: int | None = None
    paper_size: str | None = None  # "US Letter" or "A4"
    min_font_size_pt: float | None = None
    min_margin_in: float | None = None


@dataclass
class Highlight:
    """A rectangle on a page that caused a problem (used for previews)."""

    page: int  # 1-based page number
    rect: tuple[float, float, float, float]
    kind: str  # "font" or "margin"


@dataclass
class CheckResult:
    name: str
    status: str
    requirement: str
    actual: str
    details: list[str] = field(default_factory=list)
    problem_pages: list[int] = field(default_factory=list)
    review_pages: list[int] = field(default_factory=list)
    highlights: list[Highlight] = field(default_factory=list)
    limit: float | str | None = None  # the requirement value (pages, paper name, pt or inches)


@dataclass
class PageInfo:
    number: int
    width_pt: float
    height_pt: float
    size_name: str
    smallest_font_pt: float | None
    margins_in: dict[str, float] | None  # left, right, top, bottom
    has_text: bool
    looks_scanned: bool


@dataclass
class PDFReport:
    file_name: str
    page_count: int
    pages: list[PageInfo]
    results: list[CheckResult]

    @property
    def overall_status(self) -> str:
        statuses = [r.status for r in self.results]
        if FAIL in statuses:
            return FAIL
        if NEEDS_REVIEW in statuses:
            return NEEDS_REVIEW
        return PASS


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def pt_to_in(points: float) -> float:
    return points / POINTS_PER_INCH


def format_size(width_pt: float, height_pt: float) -> str:
    w_in, h_in = pt_to_in(width_pt), pt_to_in(height_pt)
    return (
        f"{w_in:.2f} × {h_in:.2f} in "
        f"({w_in * MM_PER_INCH:.0f} × {h_in * MM_PER_INCH:.0f} mm)"
    )


def format_pages(pages: list[int]) -> str:
    """Turn [1, 2, 3, 5] into 'pages 1–3, 5'."""
    if not pages:
        return ""
    pages = sorted(set(pages))
    ranges = []
    start = prev = pages[0]
    for p in pages[1:]:
        if p == prev + 1:
            prev = p
            continue
        ranges.append(f"{start}–{prev}" if start != prev else str(start))
        start = prev = p
    ranges.append(f"{start}–{prev}" if start != prev else str(start))
    label = "page" if len(pages) == 1 else "pages"
    return f"{label} {', '.join(ranges)}"


def identify_paper_size(width_pt: float, height_pt: float) -> str:
    """Return the standard name of a page size, or 'Custom'."""
    for name, (w, h) in PAPER_SIZES.items():
        portrait = abs(width_pt - w) <= PAPER_TOLERANCE_PT and abs(height_pt - h) <= PAPER_TOLERANCE_PT
        landscape = abs(width_pt - h) <= PAPER_TOLERANCE_PT and abs(height_pt - w) <= PAPER_TOLERANCE_PT
        if portrait:
            return name
        if landscape:
            return f"{name} (landscape)"
    return "Custom"


def _to_page_space(page: pymupdf.Page, rect) -> pymupdf.Rect:
    """PyMuPDF reports content in unrotated coordinates; convert to what the reader sees."""
    r = pymupdf.Rect(rect)
    if page.rotation:
        r = r * page.rotation_matrix
        r.normalize()
    return r


def _clip(rect: pymupdf.Rect, page_rect: pymupdf.Rect) -> pymupdf.Rect | None:
    """Clip a rectangle to the page; thin lines (zero width or height) are kept."""
    x0, y0 = max(rect.x0, page_rect.x0), max(rect.y0, page_rect.y0)
    x1, y1 = min(rect.x1, page_rect.x1), min(rect.y1, page_rect.y1)
    if x0 > x1 or y0 > y1:
        return None
    return pymupdf.Rect(x0, y0, x1, y1)


def _is_white(color) -> bool:
    return color is not None and all(c >= 0.98 for c in color)


# ---------------------------------------------------------------------------
# Page analysis
# ---------------------------------------------------------------------------

@dataclass
class _PageScan:
    """Raw measurements collected from one page."""

    info: PageInfo
    text_spans: list[tuple[float, pymupdf.Rect, str]]  # size, bbox, text
    content_rects: list[pymupdf.Rect]


def _scan_page(page: pymupdf.Page) -> _PageScan:
    page_rect = page.rect
    page_area = page_rect.width * page_rect.height

    spans: list[tuple[float, pymupdf.Rect, str]] = []
    # Accurate boxes follow the visible glyphs instead of the font's full line height,
    # so a heading placed exactly at 1 inch is not reported as 0.98 inch.
    text = page.get_text("dict", flags=pymupdf.TEXTFLAGS_DICT | pymupdf.TEXT_ACCURATE_BBOXES)
    for block in text.get("blocks", []):
        if block.get("type") != 0:  # 0 = text block
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                content = span.get("text", "")
                if not content.strip():
                    continue
                if span.get("alpha", 255) == 0:  # invisible text (e.g. OCR layer)
                    continue
                bbox = _to_page_space(page, span["bbox"]) & page_rect
                if bbox.is_empty:
                    continue
                spans.append((float(span["size"]), bbox, content.strip()))

    content_rects = [bbox for _, bbox, _ in spans]

    image_area = 0.0
    for image in page.get_image_info():
        bbox = _to_page_space(page, image["bbox"]) & page_rect
        if bbox.is_empty:
            continue
        image_area += bbox.width * bbox.height
        content_rects.append(bbox)

    for drawing in page.get_drawings():
        bbox = _clip(_to_page_space(page, drawing["rect"]), page_rect)
        if bbox is None:
            continue
        # Skip invisible white fills and full-page backgrounds.
        if _is_white(drawing.get("fill")) and drawing.get("color") is None:
            continue
        if bbox.width * bbox.height >= BACKGROUND_DRAWING_SHARE * page_area:
            continue
        content_rects.append(bbox)

    looks_scanned = page_area > 0 and image_area / page_area >= SCANNED_PAGE_IMAGE_SHARE

    margins = None
    if content_rects:
        box = pymupdf.Rect(content_rects[0])
        for r in content_rects[1:]:
            box |= r
        margins = {
            "left": pt_to_in(box.x0 - page_rect.x0),
            "right": pt_to_in(page_rect.x1 - box.x1),
            "top": pt_to_in(box.y0 - page_rect.y0),
            "bottom": pt_to_in(page_rect.y1 - box.y1),
        }

    info = PageInfo(
        number=page.number + 1,
        width_pt=page_rect.width,
        height_pt=page_rect.height,
        size_name=identify_paper_size(page_rect.width, page_rect.height),
        smallest_font_pt=min((s for s, _, _ in spans), default=None),
        margins_in=margins,
        has_text=bool(spans),
        looks_scanned=looks_scanned,
    )
    return _PageScan(info=info, text_spans=spans, content_rects=content_rects)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_page_count(page_count: int, max_pages: int) -> CheckResult:
    requirement = f"At most {max_pages} page{'s' if max_pages != 1 else ''}"
    if page_count == 0:
        return CheckResult("Page count", NEEDS_REVIEW, requirement, "0 pages",
                           ["The PDF has no pages that could be read."])
    if page_count <= max_pages:
        return CheckResult("Page count", PASS, requirement, f"{page_count} page{'s' if page_count != 1 else ''}")
    extra = list(range(max_pages + 1, page_count + 1))
    return CheckResult(
        "Page count", FAIL, requirement, f"{page_count} page{'s' if page_count != 1 else ''}",
        [f"{page_count - max_pages} page(s) over the limit ({format_pages(extra)})."],
        problem_pages=extra,
    )


def check_paper_size(scans: list[_PageScan], paper_size: str) -> CheckResult:
    target_w, target_h = PAPER_SIZES[paper_size]
    requirement = f"{paper_size} — {format_size(target_w, target_h)}"
    if not scans:
        return CheckResult("Paper size", NEEDS_REVIEW, requirement, "No pages",
                           ["The PDF has no pages to measure."])

    wrong, landscape, details = [], [], []
    for scan in scans:
        p = scan.info
        portrait_ok = abs(p.width_pt - target_w) <= PAPER_TOLERANCE_PT and abs(p.height_pt - target_h) <= PAPER_TOLERANCE_PT
        landscape_ok = abs(p.width_pt - target_h) <= PAPER_TOLERANCE_PT and abs(p.height_pt - target_w) <= PAPER_TOLERANCE_PT
        if portrait_ok:
            continue
        if landscape_ok:
            landscape.append(p.number)
            continue
        wrong.append(p.number)
        details.append(f"Page {p.number}: {p.size_name}, {format_size(p.width_pt, p.height_pt)}")

    sizes = sorted({s.info.size_name for s in scans})
    actual = ", ".join(sizes)
    if wrong:
        return CheckResult("Paper size", FAIL, requirement, actual, details, problem_pages=wrong)
    if landscape:
        return CheckResult(
            "Paper size", NEEDS_REVIEW, requirement, actual,
            [f"Correct paper size but landscape orientation on {format_pages(landscape)}. "
             "Check whether landscape pages are allowed."],
            review_pages=landscape,
        )
    return CheckResult("Paper size", PASS, requirement, actual)


def check_font_size(scans: list[_PageScan], min_font_pt: float) -> CheckResult:
    requirement = f"At least {min_font_pt:g} pt"
    text_pages = [s for s in scans if s.info.has_text]
    if not text_pages:
        return CheckResult(
            "Minimum font size", NEEDS_REVIEW, requirement, "No readable text found",
            ["No extractable text was found. The PDF may be scanned or made of images, "
             "so font sizes cannot be measured automatically."],
            review_pages=[s.info.number for s in scans],
        )

    smallest = min(s.info.smallest_font_pt for s in text_pages)
    actual = f"Smallest text: {smallest:.1f} pt"
    problem_pages, details, highlights = [], [], []
    for scan in text_pages:
        small = [(size, bbox, txt) for size, bbox, txt in scan.text_spans
                 if size < min_font_pt - FONT_TOLERANCE_PT]
        if not small:
            continue
        number = scan.info.number
        problem_pages.append(number)
        sizes = sorted({round(size, 1) for size, _, _ in small})
        example = small[0][2]
        if len(example) > 60:
            example = example[:57] + "..."
        details.append(
            f"Page {number}: {len(small)} text run(s) at {', '.join(f'{s:g}' for s in sizes)} pt "
            f"— e.g. \"{example}\""
        )
        highlights.extend(Highlight(number, tuple(bbox), "font") for _, bbox, _ in small)

    # Pages without text that look like images cannot be checked.
    review_pages = [s.info.number for s in scans if not s.info.has_text and s.info.looks_scanned]

    if problem_pages:
        return CheckResult("Minimum font size", FAIL, requirement, actual, details,
                           problem_pages=problem_pages, review_pages=review_pages,
                           highlights=highlights)
    if review_pages:
        return CheckResult(
            "Minimum font size", NEEDS_REVIEW, requirement, actual,
            [f"{format_pages(review_pages).capitalize()} look like scanned images with no "
             "readable text, so font size there could not be measured."],
            review_pages=review_pages,
        )
    return CheckResult("Minimum font size", PASS, requirement, actual)


def check_margins(scans: list[_PageScan], min_margin_in: float) -> CheckResult:
    requirement = f"At least {min_margin_in:.3g} in ({min_margin_in * MM_PER_INCH:.1f} mm) on every side"
    tolerance_in = pt_to_in(MARGIN_TOLERANCE_PT)
    measured = [s for s in scans if s.info.margins_in is not None and not s.info.looks_scanned]
    review_pages = [s.info.number for s in scans if s.info.looks_scanned]

    if not measured:
        return CheckResult(
            "Minimum margins", NEEDS_REVIEW, requirement, "Could not measure",
            ["No measurable content was found (pages are blank or scanned images)."],
            review_pages=review_pages or [s.info.number for s in scans],
        )

    tightest_side, tightest = None, None
    problem_pages, details, highlights = [], [], []
    for scan in measured:
        p = scan.info
        for side, value in p.margins_in.items():
            if tightest is None or value < tightest:
                tightest, tightest_side = value, side
        too_small = {side: v for side, v in p.margins_in.items() if v < min_margin_in - tolerance_in}
        if not too_small:
            continue
        problem_pages.append(p.number)
        sides = ", ".join(f"{side} {v:.2f} in" for side, v in too_small.items())
        details.append(f"Page {p.number}: content too close to the edge — {sides}")

        limit = min_margin_in * POINTS_PER_INCH
        safe = pymupdf.Rect(limit, limit, p.width_pt - limit, p.height_pt - limit)
        for rect in scan.content_rects:
            if not safe.contains(rect):
                highlights.append(Highlight(p.number, tuple(rect), "margin"))

    actual = f"Tightest margin: {tightest:.2f} in ({tightest_side})"
    if problem_pages:
        return CheckResult("Minimum margins", FAIL, requirement, actual, details,
                           problem_pages=problem_pages, review_pages=review_pages,
                           highlights=highlights)
    if review_pages:
        return CheckResult(
            "Minimum margins", NEEDS_REVIEW, requirement, actual,
            [f"{format_pages(review_pages).capitalize()} look like full-page scans; the white "
             "border inside the image cannot be measured reliably."],
            review_pages=review_pages,
        )
    return CheckResult("Minimum margins", PASS, requirement, actual)


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def open_pdf(pdf_bytes: bytes) -> pymupdf.Document:
    if not pdf_bytes:
        raise PDFCheckError("The file is empty.")
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:  # PyMuPDF raises several error types for bad files
        raise PDFCheckError("This file could not be opened as a PDF. It may be damaged.") from exc
    if doc.needs_pass:
        doc.close()
        raise PDFCheckError("This PDF is password-protected. Remove the password and upload it again.")
    return doc


def check_pdf(pdf_bytes: bytes, requirements: Requirements, file_name: str = "document.pdf") -> PDFReport:
    """Check a PDF (given as bytes) against the selected requirements."""
    if requirements.paper_size is not None and requirements.paper_size not in PAPER_SIZES:
        raise ValueError(f"Unknown paper size: {requirements.paper_size}")

    with open_pdf(pdf_bytes) as doc:
        scans = [_scan_page(page) for page in doc]
        page_count = doc.page_count

    results = []
    checks = [
        (requirements.max_pages, lambda v: check_page_count(page_count, v)),
        (requirements.paper_size, lambda v: check_paper_size(scans, v)),
        (requirements.min_font_size_pt, lambda v: check_font_size(scans, v)),
        (requirements.min_margin_in, lambda v: check_margins(scans, v)),
    ]
    for value, run in checks:
        if value is not None:
            result = run(value)
            result.limit = value
            results.append(result)

    return PDFReport(file_name=file_name, page_count=page_count,
                     pages=[s.info for s in scans], results=results)


def check_pdf_file(path: str, requirements: Requirements) -> PDFReport:
    with open(path, "rb") as f:
        data = f.read()
    return check_pdf(data, requirements, file_name=path.replace("\\", "/").split("/")[-1])


def render_page_preview(pdf_bytes: bytes, page_number: int, highlights: list[Highlight],
                        min_margin_in: float | None = None, zoom: float = 1.4) -> bytes:
    """Render one page as PNG with problem areas outlined (the original file is not changed)."""
    with open_pdf(pdf_bytes) as doc:
        page = doc[page_number - 1]
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
        width, height = page.rect.width, page.rect.height

    # Draw on a fresh one-page document holding the rendered image, so overlays
    # are in the same orientation the reader sees.
    with pymupdf.open() as canvas:
        out = canvas.new_page(width=width, height=height)
        out.insert_image(out.rect, pixmap=pix)
        if min_margin_in:
            m = min_margin_in * POINTS_PER_INCH
            out.draw_rect(pymupdf.Rect(m, m, width - m, height - m),
                          color=(1, 0.24, 0.6), width=0.8, dashes="[4 3] 0")
        for h in highlights:
            if h.page != page_number:
                continue
            color = (0.93, 0.1, 0.45) if h.kind == "font" else (1, 0.55, 0)
            out.draw_rect(pymupdf.Rect(h.rect) + (-1.5, -1.5, 1.5, 1.5),
                          color=color, fill=color, fill_opacity=0.18, width=1.2)
        return out.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).tobytes("png")

"""Standalone HTML report for PrintProof AI (Step 3).

build_html_report() turns real check results into one self-contained HTML file (CSS and page
previews are embedded), so it opens by double-clicking, without the app.

Rules:
- Every status, number and page number comes from CheckResult / PageInfo objects produced by
  pdf_checker.py. Nothing is estimated.
- Fix suggestions are written only for checks that failed or need review, from their measurements.
- Requirements that were not checked are listed as "Not checked", never as passed.
- All text (file names, PDF text excerpts, AI text) is HTML-escaped.
"""

from __future__ import annotations

import base64
import html
from dataclasses import dataclass, field
from datetime import datetime

from pdf_checker import (
    FAIL,
    MM_PER_INCH,
    NEEDS_REVIEW,
    PASS,
    PAPER_SIZES,
    CheckResult,
    PageInfo,
    format_pages,
    format_size,
    render_page_preview,
)

MAX_PREVIEW_PAGES = 6  # keep the HTML file small
PREVIEW_ZOOM = 0.9


@dataclass
class AIDetails:
    """Extra information shown when the report comes from AI mode."""

    requirements_text: str
    understood: list[dict]  # UnderstoodRequirement.model_dump()
    clarifications: list[str]
    summary: str
    explanations: dict[str, str]  # check name -> AI explanation
    model: str
    run_id: str
    usage: dict[str, int] = field(default_factory=dict)


def esc(value) -> str:
    return html.escape(str(value))


def overall_status(results: list[CheckResult], anything_unchecked_or_unclear: bool = False) -> str:
    statuses = [r.status for r in results]
    if FAIL in statuses:
        return FAIL
    if NEEDS_REVIEW in statuses or anything_unchecked_or_unclear or not statuses:
        return NEEDS_REVIEW
    return PASS


# ---------------------------------------------------------------------------
# Fix suggestions (only from measured results)
# ---------------------------------------------------------------------------

def suggestions_for(result: CheckResult, pages: list[PageInfo]) -> list[str]:
    """Concrete fixes for one check, using its real measurements. Empty for a Pass."""
    if result.status == PASS:
        return []
    by_number = {p.number: p for p in pages}
    tips: list[str] = []

    if result.name == "Page count":
        if result.status == FAIL:
            extra = len(result.problem_pages)
            tips.append(f"Shorten the document by at least {extra} page{'s' if extra != 1 else ''} "
                        f"(it has {len(pages)}, the limit is {result.limit}). Options: cut or merge "
                        "sections, or move supporting material to an appendix if the rules allow it.")
            tips.append("Do not shrink the text or margins to save space — that can break the font-size "
                        "and margin rules.")
        else:
            tips.append("The page count could not be read. Open the PDF and count the pages by hand.")

    elif result.name == "Paper size":
        target = str(result.limit)
        if result.status == FAIL:
            for number in result.problem_pages:
                p = by_number.get(number)
                if p:
                    tips.append(f"Page {number} is {p.size_name}, {format_size(p.width_pt, p.height_pt)}; "
                                f"it must be {target}.")
            w, h = PAPER_SIZES.get(target, (0, 0))
            tips.append(f"In the source document set the page size to {target} "
                        f"— {format_size(w, h)} — for every section, then export to PDF again. "
                        "In Word: Layout → Size. In Google Docs: File → Page setup.")
            tips.append("After re-exporting, check that the layout did not shift and run PrintProof again.")
        else:
            tips.append(f"{format_pages(result.review_pages).capitalize()} have the right paper size but "
                        "landscape orientation. Check whether landscape pages are allowed; if not, rotate "
                        "the content to portrait.")

    elif result.name == "Minimum font size":
        if result.status == FAIL:
            for number in result.problem_pages:
                p = by_number.get(number)
                if p and p.smallest_font_pt is not None:
                    tips.append(f"Page {number}: the smallest text is {p.smallest_font_pt:.1f} pt. "
                                f"Increase it to at least {result.limit:g} pt.")
            tips.append("Look at footnotes, tables, captions, headers/footers and text inside charts — "
                        "these are where the small text was measured (highlighted in the previews below).")
        if result.review_pages:
            tips.append(f"{format_pages(result.review_pages).capitalize()} have no readable text "
                        "(probably scanned), so font size could not be measured. Check them by eye, or "
                        "export the original document to PDF instead of scanning it.")

    elif result.name == "Minimum margins":
        if result.status == FAIL:
            limit = float(result.limit)
            for number in result.problem_pages:
                p = by_number.get(number)
                if not p or not p.margins_in:
                    continue
                short = [f"{side} edge by {limit - v:.2f} in / {(limit - v) * MM_PER_INCH:.0f} mm "
                         f"(now {v:.2f} in)"
                         for side, v in p.margins_in.items() if v < limit - 0.007]
                if short:
                    tips.append(f"Page {number}: move content further from the " + "; ".join(short) + ".")
            tips.append(f"Set the document margins to at least {limit:.3g} in ({limit * MM_PER_INCH:.1f} mm) "
                        "and check items placed outside the text area, such as headers, footers, page "
                        "numbers, images and logos.")
        if result.review_pages:
            tips.append(f"{format_pages(result.review_pages).capitalize()} look like full-page scans, so "
                        "margins could not be measured. Check the white border by eye or use the original "
                        "file.")
    return tips


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

CSS = """
:root { --ink:#16131a; --muted:#6b6472; --line:#e7e2ea; --bg:#faf8fb; --pink:#e2186f; --pink-soft:#fde7f1;
  --pass:#13804f; --pass-bg:#e6f6ee; --fail:#c8102e; --fail-bg:#fdebee; --review:#a35b00; --review-bg:#fff4e0; }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.55 -apple-system, "Segoe UI", Inter, Roboto, Arial, sans-serif; }
.wrap { max-width: 980px; margin: 0 auto; padding: 36px 28px 60px; }
header { background:#0d0b10; color:#fff; border-radius:18px; padding:26px 30px; display:flex; justify-content:space-between; gap:20px; align-items:center; }
.brand { font-size:24px; font-weight:800; letter-spacing:-.02em; } .brand span { color:#ff4d97; }
header .meta { color:#c9c3cf; font-size:13px; margin-top:6px; }
.badge { display:inline-block; padding:5px 12px; border-radius:999px; font-weight:800; font-size:12px; letter-spacing:.04em; text-transform:uppercase; white-space:nowrap; }
.b-pass { background:var(--pass-bg); color:var(--pass); } .b-fail { background:var(--fail-bg); color:var(--fail); }
.b-review { background:var(--review-bg); color:var(--review); } .b-none { background:#efedf1; color:var(--muted); }
.verdict { font-size:15px; padding:10px 16px; }
h2 { font-size:18px; margin:34px 0 12px; letter-spacing:-.01em; }
h2::before { content:""; display:inline-block; width:4px; height:15px; background:var(--pink); border-radius:2px; margin-right:9px; vertical-align:-1px; }
.tiles { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-top:20px; }
.tile { background:#fff; border:1px solid var(--line); border-radius:14px; padding:14px 16px; }
.tile .k { color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.08em; font-weight:700; }
.tile .v { font-size:20px; font-weight:800; margin-top:2px; } .tile .s { color:var(--muted); font-size:12px; }
table { width:100%; border-collapse:collapse; background:#fff; border:1px solid var(--line); border-radius:14px; overflow:hidden; }
th, td { text-align:left; padding:10px 12px; border-bottom:1px solid var(--line); vertical-align:top; font-size:14px; }
th { background:#f3eff5; font-size:12px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); }
tr:last-child td { border-bottom:none; }
.issue { background:#fff; border:1px solid var(--line); border-left:5px solid var(--fail); border-radius:14px; padding:16px 18px; margin-bottom:12px; }
.issue.review { border-left-color:#e59400; }
.issue h3 { margin:0 0 6px; font-size:16px; display:flex; justify-content:space-between; gap:10px; }
.issue .facts { color:var(--muted); font-size:13px; margin-bottom:8px; }
.issue ul { margin:6px 0 0 18px; padding:0; } .issue li { margin:4px 0; }
.issue .ai { margin-top:10px; background:var(--pink-soft); border-radius:10px; padding:8px 12px; font-size:13px; }
.issue .ai b { color:var(--pink); }
.none { background:#fff; border:1px dashed var(--line); border-radius:14px; padding:14px 18px; color:var(--muted); }
.note { background:#fff; border:1px solid var(--line); border-radius:14px; padding:14px 18px; }
.previews { display:grid; grid-template-columns:repeat(auto-fill,minmax(260px,1fr)); gap:14px; }
figure { margin:0; background:#fff; border:1px solid var(--line); border-radius:14px; padding:10px; }
figure img { width:100%; display:block; border-radius:6px; border:1px solid var(--line); }
figcaption { font-size:12px; color:var(--muted); margin-top:6px; }
.legend i { display:inline-block; width:10px; height:10px; border-radius:2px; margin:0 4px -1px 10px; }
.s { color:var(--muted); font-size:12.5px; }
footer { margin-top:40px; color:var(--muted); font-size:12px; border-top:1px solid var(--line); padding-top:14px; }
@media print { body { background:#fff; } .wrap { padding:0; } header { -webkit-print-color-adjust:exact; print-color-adjust:exact; }
  .issue, figure, table { break-inside:avoid; } }
@media (max-width:720px) { .tiles { grid-template-columns:repeat(2,1fr); } header { flex-direction:column; align-items:flex-start; } }
"""

BADGE = {PASS: "b-pass", FAIL: "b-fail", NEEDS_REVIEW: "b-review"}


def _tiles(pages: list[PageInfo], page_count: int) -> str:
    fonts = [p.smallest_font_pt for p in pages if p.smallest_font_pt is not None]
    margins = [(min(p.margins_in.values()), p.number) for p in pages if p.margins_in and not p.looks_scanned]
    sizes = sorted({p.size_name for p in pages})
    tiles = [
        ("Pages", str(page_count), ""),
        ("Paper size", sizes[0] if len(sizes) == 1 else f"{len(sizes)} sizes", ", ".join(sizes)),
        ("Smallest text", f"{min(fonts):.1f} pt" if fonts else "—", "" if fonts else "no readable text"),
        ("Tightest margin", f"{min(margins)[0]:.2f} in" if margins else "—",
         f"page {min(margins)[1]}" if margins else "not measurable"),
    ]
    return '<div class="tiles">' + "".join(
        f'<div class="tile"><div class="k">{esc(k)}</div><div class="v">{esc(v)}</div><div class="s">{esc(s)}</div></div>'
        for k, v, s in tiles) + "</div>"


def _previews(pdf_bytes: bytes, results: list[CheckResult], min_margin_in: float | None) -> str:
    flagged = sorted({p for r in results for p in r.problem_pages + r.review_pages})
    # Pages over the page limit are not layout problems; preview them only if flagged by other checks.
    layout = sorted({p for r in results if r.name != "Page count" for p in r.problem_pages + r.review_pages})
    pages = (layout or flagged)[:MAX_PREVIEW_PAGES]
    if not pages:
        return ""
    figs = []
    for number in pages:
        highlights = [h for r in results for h in r.highlights if h.page == number]
        png = render_page_preview(pdf_bytes, number, highlights, min_margin_in=min_margin_in, zoom=PREVIEW_ZOOM)
        b64 = base64.b64encode(png).decode("ascii")
        names = [r.name for r in results if number in r.problem_pages + r.review_pages]
        figs.append(f'<figure><img alt="Page {number}" src="data:image/png;base64,{b64}">'
                    f'<figcaption>Page {number} — {esc(", ".join(names))}</figcaption></figure>')
    more = len(layout or flagged) - len(pages)
    extra = f'<p class="s">{more} more flagged page(s) not shown.</p>' if more > 0 else ""
    return ('<h2>Flagged pages</h2><p class="legend">Highlights:<i style="background:#ee1a73"></i>small text'
            '<i style="background:#ff8c00"></i>outside the margin<i style="border:1.5px dashed #ff3d8b"></i>'
            'required margin</p><div class="previews">' + "".join(figs) + "</div>" + extra)


def build_html_report(*, file_name: str, pdf_bytes: bytes, mode: str, results: list[CheckResult],
                      pages: list[PageInfo], page_count: int, not_checked: list[str],
                      min_margin_in: float | None, overall: str, ai: AIDetails | None = None,
                      generated_at: datetime | None = None) -> str:
    """Return a complete, self-contained HTML report as a string."""
    generated_at = generated_at or datetime.now()
    when = generated_at.strftime("%Y-%m-%d %H:%M")
    counts = {s: sum(r.status == s for r in results) for s in (PASS, FAIL, NEEDS_REVIEW)}
    explanations = ai.explanations if ai else {}

    rows = "".join(
        f"<tr><td><b>{esc(r.name)}</b><br><span class='s'>{esc(r.requirement)}</span></td>"
        f"<td><span class='badge {BADGE[r.status]}'>{esc(r.status)}</span></td>"
        f"<td>{esc(r.actual)}</td>"
        f"<td>{esc(format_pages(r.problem_pages) or format_pages(r.review_pages) or '—')}</td></tr>"
        for r in results
    )
    rows += "".join(
        f"<tr><td><b>{esc(item)}</b></td><td><span class='badge b-none'>Not checked</span></td>"
        f"<td colspan='2'>Not measured in this run.</td></tr>"
        for item in not_checked
    )
    if not rows:
        rows = "<tr><td colspan='4'>No requirements were checked.</td></tr>"

    issues = []
    for r in results:
        if r.status == PASS:
            continue
        tips = "".join(f"<li>{esc(t)}</li>" for t in suggestions_for(r, pages))
        details = "".join(f"<li>{esc(d)}</li>" for d in r.details)
        ai_note = (f"<div class='ai'><b>AI explanation:</b> {esc(explanations[r.name])}</div>"
                   if r.name in explanations else "")
        issues.append(
            f"<div class='issue {'review' if r.status == NEEDS_REVIEW else ''}'>"
            f"<h3>{esc(r.name)} <span class='badge {BADGE[r.status]}'>{esc(r.status)}</span></h3>"
            f"<div class='facts'>Required: {esc(r.requirement)} · Measured: {esc(r.actual)}</div>"
            f"{'<b>What was found</b><ul>' + details + '</ul>' if details else ''}"
            f"<b>How to fix it</b><ul>{tips}</ul>{ai_note}</div>"
        )
    issues_html = "".join(issues) or "<div class='none'>No problems were found in the checks that were run.</div>"

    not_checked_html = ""
    if not_checked:
        items = "".join(f"<li>{esc(i)}</li>" for i in not_checked)
        not_checked_html = (f"<h2>Not checked</h2><div class='note'>These requirements were <b>not</b> "
                            f"verified by PrintProof and need a manual check:<ul>{items}</ul></div>")

    ai_html = ""
    if ai:
        understood = "".join(
            f"<tr><td>{esc(u['user_wording'])}</td><td>{esc(u['interpreted_as'])}</td>"
            f"<td>{'Checked' if u['checkable'] else 'Not checkable'}</td><td>{esc(u.get('note') or '')}</td></tr>"
            for u in ai.understood
        )
        clar = "".join(f"<li>{esc(c)}</li>" for c in ai.clarifications)
        tokens = ai.usage.get("total_tokens", 0)
        cached = ai.usage.get("tokens_from_portkey_cache", 0)
        ai_html = (
            "<h2>AI interpretation</h2>"
            f"<div class='note'><b>Requirements as written:</b> “{esc(ai.requirements_text)}”</div><br>"
            "<table><tr><th>User wording</th><th>Understood as</th><th>Checked?</th><th>Note</th></tr>"
            f"{understood}</table>"
            + (f"<br><div class='note'><b>Needs clarification</b><ul>{clar}</ul></div>" if clar else "")
            + f"<br><div class='note'><b>AI summary:</b> {esc(ai.summary)}</div>"
            f"<p class='s'>Model {esc(ai.model)} via Portkey · run {esc(ai.run_id)} · {tokens:,} tokens"
            + (f" ({cached:,} served from Portkey's cache)" if cached else "") + ". "
            "The AI only received the requirements text and the measurements below, never the PDF.</p>"
        )

    page_rows = "".join(
        f"<tr><td>{p.number}</td><td>{esc(p.size_name)}</td><td>{p.width_pt / 72:.2f} × {p.height_pt / 72:.2f}</td>"
        f"<td>{f'{p.smallest_font_pt:.1f}' if p.smallest_font_pt else '—'}</td>"
        + "".join(f"<td>{p.margins_in[s]:.2f}</td>" if p.margins_in else "<td>—</td>"
                  for s in ("left", "right", "top", "bottom"))
        + f"<td>{'Yes' if p.looks_scanned else 'No'}</td></tr>"
        for p in pages
    )

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>PrintProof report — {esc(file_name)}</title><style>{CSS}</style></head>
<body><div class="wrap">
<header><div><div class="brand">Print<span>Proof</span> AI · Print readiness report</div>
<div class="meta">{esc(file_name)} · {page_count} page{'s' if page_count != 1 else ''} · {esc(mode)} mode · generated {esc(when)}</div></div>
<span class="badge verdict {BADGE[overall]}">{esc(overall)}</span></header>
{_tiles(pages, page_count)}
<h2>Requirements</h2>
<p class="s">{counts[PASS]} passed · {counts[FAIL]} failed · {counts[NEEDS_REVIEW]} need review{f" · {len(not_checked)} not checked" if not_checked else ""}</p>
<table><tr><th>Requirement</th><th>Status</th><th>Measured</th><th>Pages</th></tr>{rows}</table>
<h2>Issues and how to fix them</h2>{issues_html}
{not_checked_html}
{ai_html}
{_previews(pdf_bytes, results, min_margin_in)}
<h2>Page-by-page measurements</h2>
<table><tr><th>Page</th><th>Paper</th><th>Size (in)</th><th>Smallest font (pt)</th><th>Left</th><th>Right</th><th>Top</th><th>Bottom</th><th>Scanned?</th></tr>{page_rows}</table>
<p class="s">Margins in inches, from the page edge to the nearest visible text, image or drawing.</p>
<footer>Measured automatically by PrintProof AI with PyMuPDF. “Needs Review” means the file could not be measured
reliably and should be checked by a person. PrintProof only checks page count, paper size, minimum font size and
minimum margins; it does not check spelling, content, line spacing, font family or colors.</footer>
</div></body></html>"""

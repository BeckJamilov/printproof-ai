"""PrintProof AI — Streamlit interface.

Run from the Final Project folder (PowerShell, no activation needed):
    .\\.venv\\Scripts\\python.exe -m streamlit run app.py
"""

from __future__ import annotations

import hashlib
import html
import os
from pathlib import Path

import streamlit as st

from agent import MAX_REQUIREMENTS_CHARS, MODEL_NAME, USAGE_LIMITS, load_project_env, run_ai_check
from report import AIDetails, build_html_report
from pdf_checker import (
    FAIL,
    MM_PER_INCH,
    NEEDS_REVIEW,
    PASS,
    PDFCheckError,
    Requirements,
    check_pdf,
    format_pages,
    format_size,
    render_page_preview,
)

PROJECT_DIR = Path(__file__).resolve().parent
SAMPLE_DIR = PROJECT_DIR / "sample_pdfs"
MAX_UPLOAD_MB = 50
AI_EXAMPLE = "maximum 5 pages, US Letter paper, at least 10 pt font and 1 inch margins"

ENV_FILES = load_project_env()

st.set_page_config(page_title="PrintProof AI", page_icon="🖨️", layout="wide")

# ---------------------------------------------------------------------------
# Styling (black-and-pink theme)
# ---------------------------------------------------------------------------
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

:root {
  --bg: #0a0a0d; --panel: #131318; --panel-2: #1b1b22; --line: #2a2a33;
  --pink: #ff3d8b; --pink-soft: #ff8cbc; --text: #f5f3f7; --muted: #a4a1ad;
  --pass: #3ddc97; --fail: #ff4d6d; --review: #ffb547;
}
html, body, [class*="css"], .stApp { font-family: 'Inter', system-ui, sans-serif; }
.stApp { background: radial-gradient(1200px 500px at 85% -10%, rgba(255,61,139,.16), transparent 60%), var(--bg); color: var(--text); }
header[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 2.2rem; max-width: 1250px; }
h1, h2, h3, h4, p, label, span, li { color: var(--text); }

section[data-testid="stSidebar"] { background: #0f0f13; border-right: 1px solid var(--line); }
section[data-testid="stSidebar"] * { color: var(--text); }
section[data-testid="stSidebar"] small, .muted { color: var(--muted) !important; }

/* Inputs */
[data-baseweb="input"], [data-baseweb="input"] *, [data-baseweb="base-input"], [data-baseweb="select"] > div {
  background-color: var(--panel-2) !important; border-color: var(--line) !important; }
input { color: var(--text) !important; -webkit-text-fill-color: var(--text) !important; }
input:disabled { opacity: .45; }
.react-aria-ComboBox > div, .react-aria-Select button { background-color: var(--panel-2) !important; border-color: var(--line) !important; color: var(--text) !important; }
.react-aria-ComboBox svg path { fill: var(--muted); }
.react-aria-Popover, [role="listbox"] { background-color: var(--panel-2) !important; border: 1px solid var(--line); }
[role="option"] { background-color: var(--panel-2) !important; color: var(--text) !important; }
[role="option"]:hover, [role="option"][data-focused], [role="option"][aria-selected="true"] { background-color: #2a1520 !important; }
[data-testid="stNumberInputContainer"] { background-color: var(--panel-2) !important; border-color: var(--line) !important; }
[data-testid="stNumberInputContainer"]:focus-within { border-color: var(--pink) !important; }
[data-testid="stNumberInput"] button { background: var(--panel-2) !important; color: var(--text) !important; border-color: var(--line) !important; }
[data-testid="stNumberInput"] button svg { fill: var(--text); }
[data-baseweb="popover"] ul, [data-baseweb="popover"] li { background: var(--panel-2) !important; color: var(--text) !important; }
[data-baseweb="popover"] li:hover, [data-baseweb="popover"] li[aria-selected="true"] { background: #2a1520 !important; }
[data-testid="stFileUploaderDropzone"] { background: var(--panel) !important; border: 1.5px dashed rgba(255,61,139,.55) !important; border-radius: 16px; padding: 22px 20px; }
[data-testid="stFileUploaderDropzone"] * { color: var(--muted) !important; }
[data-testid="stFileUploaderDropzone"] svg { fill: var(--pink) !important; }
[data-testid="stFileUploaderDropzone"] button { background: var(--pink) !important; color: #fff !important; border: none !important; }
[data-testid="stFileUploaderDropzone"] button * { color: #fff !important; }
[data-testid="stFileUploaderFile"] * { color: var(--text) !important; }
[data-testid="stDataFrame"] { border: 1px solid var(--line); border-radius: 12px; overflow: hidden; }

.stButton > button { background: var(--panel-2); color: var(--text); border: 1px solid var(--line); border-radius: 12px; font-weight: 600; transition: all .15s; }
.stButton > button:hover { border-color: var(--pink); color: var(--pink-soft); }
.stButton > button[kind="primary"] { background: linear-gradient(135deg, #ff3d8b, #c2185b); border: none; color: #fff; }
[data-testid="stDownloadButton"] button { background: var(--panel-2) !important; color: var(--text) !important; border: 1px solid rgba(255,61,139,.55) !important; border-radius: 12px; font-weight: 600; }
[data-testid="stDownloadButton"] button * { color: var(--text) !important; }
[data-testid="stDownloadButton"] button:hover { border-color: var(--pink) !important; color: var(--pink-soft) !important; }

div[data-testid="stTabs"] button p { color: var(--muted); font-weight: 600; }
div[data-testid="stTabs"] button[aria-selected="true"] p { color: var(--pink); }
div[data-testid="stExpander"] { background: var(--panel); border: 1px solid var(--line); border-radius: 14px; }

/* Custom components */
.hero { display:flex; align-items:center; justify-content:space-between; gap:24px; padding: 28px 32px; border-radius: 22px;
  background: linear-gradient(135deg, #17171d 0%, #120d12 60%, #2a0f1e 100%); border: 1px solid var(--line); margin-bottom: 22px; }
.brand { font-size: 2.3rem; font-weight: 800; letter-spacing: -0.03em; margin: 0; line-height: 1.1; }
.brand span { color: var(--pink); }
.tagline { color: var(--muted); margin-top: 6px; font-size: 1rem; }
.chip { display:inline-block; padding: 5px 12px; border-radius: 999px; font-size: .78rem; font-weight: 700; letter-spacing: .04em;
  border: 1px solid rgba(255,61,139,.45); color: var(--pink-soft); background: rgba(255,61,139,.08); text-transform: uppercase; }

.verdict { border-radius: 18px; padding: 20px 24px; margin: 6px 0 18px; border: 1px solid; display:flex; align-items:center; gap: 18px; }
.verdict .icon { font-size: 2rem; width: 54px; height: 54px; border-radius: 14px; display:flex; align-items:center; justify-content:center; font-weight:800; }
.verdict h3 { margin: 0; font-size: 1.35rem; }
.verdict p { margin: 2px 0 0; color: var(--muted); }
.v-pass { background: rgba(61,220,151,.08); border-color: rgba(61,220,151,.4); } .v-pass .icon { background: rgba(61,220,151,.18); color: var(--pass); }
.v-fail { background: rgba(255,77,109,.08); border-color: rgba(255,77,109,.45); } .v-fail .icon { background: rgba(255,77,109,.18); color: var(--fail); }
.v-review { background: rgba(255,181,71,.08); border-color: rgba(255,181,71,.45); } .v-review .icon { background: rgba(255,181,71,.18); color: var(--review); }

.metric { background: var(--panel); border: 1px solid var(--line); border-radius: 16px; padding: 16px 18px; height: 100%; }
.metric .label { color: var(--muted); font-size: .75rem; text-transform: uppercase; letter-spacing: .08em; font-weight: 600; }
.metric .value { font-size: 1.45rem; font-weight: 800; margin-top: 4px; }
.metric .sub { color: var(--muted); font-size: .8rem; margin-top: 2px; }

.card { background: var(--panel); border: 1px solid var(--line); border-left: 4px solid var(--line); border-radius: 16px; padding: 18px 20px; margin-bottom: 14px; }
.card.pass { border-left-color: var(--pass); } .card.fail { border-left-color: var(--fail); } .card.review { border-left-color: var(--review); }
.card-head { display:flex; justify-content:space-between; align-items:center; gap: 12px; }
.card-title { font-weight: 700; font-size: 1.05rem; }
.pill { padding: 4px 11px; border-radius: 999px; font-size: .75rem; font-weight: 800; letter-spacing: .03em; white-space: nowrap; }
.pill.pass { background: rgba(61,220,151,.15); color: var(--pass); }
.pill.fail { background: rgba(255,77,109,.15); color: var(--fail); }
.pill.review { background: rgba(255,181,71,.15); color: var(--review); }
.grid2 { display:grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 12px; }
.kv .k { color: var(--muted); font-size: .72rem; text-transform: uppercase; letter-spacing: .07em; font-weight: 600; }
.kv .v { font-weight: 600; margin-top: 2px; }
.details { margin: 12px 0 0; padding: 0; list-style: none; }
.details li { padding: 7px 10px; margin-top: 6px; border-radius: 10px; background: var(--panel-2); font-size: .88rem; color: #dcd9e2; }
.pages { margin-top: 10px; font-size: .85rem; color: var(--pink-soft); font-weight: 600; }

.empty { text-align:center; padding: 54px 24px; border-radius: 20px; border: 1px dashed var(--line); background: var(--panel); color: var(--muted); }
.empty h3 { color: var(--text); margin-bottom: 6px; }
.steps { display:flex; gap: 14px; justify-content:center; margin-top: 20px; flex-wrap: wrap; }
.step { background: var(--panel-2); border: 1px solid var(--line); border-radius: 14px; padding: 12px 16px; font-size: .88rem; color: var(--text); }
.step b { color: var(--pink); margin-right: 6px; }
.legend { color: var(--muted); font-size: .82rem; margin-top: 6px; }
.legend i { display:inline-block; width: 11px; height: 11px; border-radius: 3px; margin: 0 5px -1px 12px; }

/* Step 2: AI mode */
textarea { background: var(--panel-2) !important; color: var(--text) !important; -webkit-text-fill-color: var(--text) !important;
  border-radius: 12px !important; font-size: .92rem !important; line-height: 1.45 !important; }
[data-testid="stTextArea"] [data-baseweb="textarea"], [data-testid="stTextAreaRootElement"] { background: var(--panel-2) !important; border-color: var(--line) !important; }
.section-title { font-weight: 700; font-size: 1rem; margin: 22px 0 10px; letter-spacing: -0.01em; }
.section-title::before { content: ""; display:inline-block; width: 4px; height: 14px; border-radius: 2px; background: var(--pink); margin-right: 9px; vertical-align: -1px; }
.req-grid { display:grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 12px; }
.req { background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 14px 16px; }
.req-kind { color: var(--pink-soft); font-size: .7rem; text-transform: uppercase; letter-spacing: .09em; font-weight: 700; }
.req-main { font-weight: 700; margin-top: 4px; }
.req-quote { color: var(--muted); font-size: .84rem; margin-top: 4px; font-style: italic; }
.req-note { color: #e9d7a8; font-size: .83rem; margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--line); }
.clarify { margin-top: 12px; border: 1px solid rgba(255,181,71,.45); background: rgba(255,181,71,.07); border-radius: 14px; padding: 12px 16px; }
.clarify b { color: var(--review); } .clarify ul { margin: 6px 0 0 18px; } .clarify li { color: #f1e4c6; font-size: .9rem; }
.ai-summary, .ai-note { margin-top: 12px; padding: 12px 14px; border-radius: 12px; background: linear-gradient(135deg, rgba(255,61,139,.10), rgba(255,61,139,.03));
  border: 1px solid rgba(255,61,139,.30); font-size: .9rem; color: #eee7ef; }
.ai-summary span, .ai-note span { display:block; color: var(--pink); font-size: .7rem; font-weight: 800; text-transform: uppercase; letter-spacing: .09em; margin-bottom: 4px; }
</style>
""",
    unsafe_allow_html=True,
)

STATUS_CLASS = {PASS: "pass", FAIL: "fail", NEEDS_REVIEW: "review"}
STATUS_ICON = {PASS: "✓", FAIL: "✕", NEEDS_REVIEW: "?"}


def esc(text) -> str:
    """Escape text before placing it inside HTML (PDF text comes from the user's file)."""
    return html.escape(str(text))


@st.cache_data(show_spinner=False, max_entries=20)
def run_check(pdf_bytes: bytes, file_name: str, max_pages, paper_size, min_font, min_margin):
    reqs = Requirements(max_pages=max_pages, paper_size=paper_size,
                        min_font_size_pt=min_font, min_margin_in=min_margin)
    return check_pdf(pdf_bytes, reqs, file_name=file_name)


@st.cache_data(show_spinner=False, max_entries=40)
def preview_png(pdf_bytes: bytes, page_number: int, _highlights, highlight_key: str, min_margin):
    return render_page_preview(pdf_bytes, page_number, _highlights, min_margin_in=min_margin)


@st.cache_data(show_spinner=False, max_entries=10)
def manual_report_html(pdf_bytes: bytes, file_name: str, max_pages, paper_size, min_font, min_margin,
                       not_checked: tuple[str, ...]) -> str:
    report = run_check(pdf_bytes, file_name, max_pages, paper_size, min_font, min_margin)
    return build_html_report(
        file_name=file_name, pdf_bytes=pdf_bytes, mode="Manual", results=report.results,
        pages=report.pages, page_count=report.page_count, not_checked=list(not_checked),
        min_margin_in=min_margin, overall=report.overall_status,
    )


def download_report(html_text: str, file_name: str, key: str) -> None:
    st.download_button(
        "⬇ Download HTML report", data=html_text.encode("utf-8"),
        file_name=f"{Path(file_name).stem}_printproof_report.html", mime="text/html",
        key=key, help="A standalone report with results, measurements, problem pages and fix suggestions.",
    )




# ---------------------------------------------------------------------------
# Reusable result views (used by both manual and AI modes)
# ---------------------------------------------------------------------------
HEADLINES = {
    PASS: "Ready to print",
    FAIL: "Not ready — fix the issues below",
    NEEDS_REVIEW: "Almost there — some items need a human look",
}


def render_verdict(overall: str, subtitle: str) -> None:
    st.markdown(
        f"""
<div class="verdict v-{STATUS_CLASS[overall]}">
  <div class="icon">{STATUS_ICON[overall]}</div>
  <div>
    <h3>{esc(HEADLINES[overall])}</h3>
    <p>{esc(subtitle)}</p>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def count_line(results) -> str:
    counts = {s: sum(r.status == s for r in results) for s in (PASS, FAIL, NEEDS_REVIEW)}
    return f"{counts[PASS]} passed · {counts[FAIL]} failed · {counts[NEEDS_REVIEW]} need review"


def render_metrics(tiles) -> None:
    for col, (label, value, sub) in zip(st.columns(len(tiles)), tiles):
        col.markdown(
            f'<div class="metric"><div class="label">{esc(label)}</div><div class="value">{esc(value)}</div>'
            f'<div class="sub">{esc(sub)}</div></div>',
            unsafe_allow_html=True,
        )


def document_tiles(report, page_limit) -> list[tuple[str, str, str]]:
    pages = report.pages
    fonts = [p.smallest_font_pt for p in pages if p.smallest_font_pt is not None]
    margins = [(min(p.margins_in.values()), p.number) for p in pages if p.margins_in and not p.looks_scanned]
    sizes = sorted({p.size_name for p in pages})
    first = pages[0] if pages else None
    return [
        ("Pages", str(report.page_count), f"limit {page_limit}" if page_limit else "no limit set"),
        ("Paper size", sizes[0] if len(sizes) == 1 else f"{len(sizes)} sizes",
         format_size(first.width_pt, first.height_pt) if first and len(sizes) == 1 else ", ".join(sizes)),
        ("Smallest text", f"{min(fonts):.1f} pt" if fonts else "—", "no readable text" if not fonts else "across all pages"),
        ("Tightest margin", f"{min(margins)[0]:.2f} in" if margins else "—",
         f"on page {min(margins)[1]}" if margins else "not measurable"),
    ]


def render_result_card(result, ai_explanation: str | None = None) -> None:
    cls = STATUS_CLASS[result.status]
    details = "".join(f"<li>{esc(d)}</li>" for d in result.details)
    page_bits = []
    if result.problem_pages:
        page_bits.append(f"Problems on {format_pages(result.problem_pages)}")
    if result.review_pages:
        page_bits.append(f"Review {format_pages(result.review_pages)}")
    ai_html = (f'<div class="ai-note"><span>AI explanation</span>{esc(ai_explanation)}</div>'
               if ai_explanation else "")
    st.markdown(
        f"""
<div class="card {cls}">
  <div class="card-head"><div class="card-title">{esc(result.name)}</div>
    <span class="pill {cls}">{STATUS_ICON[result.status]} {esc(result.status).upper()}</span></div>
  <div class="grid2">
    <div class="kv"><div class="k">Requirement</div><div class="v">{esc(result.requirement)}</div></div>
    <div class="kv"><div class="k">Actual</div><div class="v">{esc(result.actual)}</div></div>
  </div>
  {f'<div class="pages">{esc(" · ".join(page_bits))}</div>' if page_bits else ''}
  {f'<ul class="details">{details}</ul>' if details else ''}
  {ai_html}
</div>
""",
        unsafe_allow_html=True,
    )


def render_preview(pdf_bytes: bytes, report, results, min_margin_in, key_prefix: str) -> None:
    pages = report.pages
    flagged = sorted({p for r in results for p in r.problem_pages + r.review_pages if p <= report.page_count})
    default_page = flagged[0] if flagged else 1
    left, right = st.columns([1, 2.2], gap="large")
    with left:
        page_choice = st.selectbox(
            "Page", list(range(1, report.page_count + 1)), index=default_page - 1,
            format_func=lambda n: f"Page {n}" + ("  •  flagged" if n in flagged else ""),
            key=f"{key_prefix}_page",
        )
        info = pages[page_choice - 1]
        st.markdown(
            f'<div class="metric"><div class="label">Page {info.number}</div>'
            f'<div class="value" style="font-size:1.1rem">{esc(info.size_name)}</div>'
            f'<div class="sub">{esc(format_size(info.width_pt, info.height_pt))}</div></div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="legend"><i style="background:#ee1a73"></i>small text'
            '<i style="background:#ff8c00"></i>outside margin'
            '<i style="border:1.5px dashed #ff3d8b"></i>required margin</div>',
            unsafe_allow_html=True,
        )
    with right:
        highlights = [h for r in results for h in r.highlights if h.page == page_choice]
        key = repr([(h.rect, h.kind) for h in highlights])
        st.image(preview_png(pdf_bytes, page_choice, highlights, key, min_margin_in), width="stretch")


def render_page_table(report) -> None:
    rows = []
    for p in report.pages:
        rows.append({
            "Page": p.number,
            "Paper size": p.size_name,
            "Size (in)": f"{p.width_pt / 72:.2f} × {p.height_pt / 72:.2f}",
            "Smallest font (pt)": round(p.smallest_font_pt, 1) if p.smallest_font_pt else None,
            "Left (in)": round(p.margins_in["left"], 2) if p.margins_in else None,
            "Right (in)": round(p.margins_in["right"], 2) if p.margins_in else None,
            "Top (in)": round(p.margins_in["top"], 2) if p.margins_in else None,
            "Bottom (in)": round(p.margins_in["bottom"], 2) if p.margins_in else None,
            "Readable text": "Yes" if p.has_text else "No",
            "Looks scanned": "Yes" if p.looks_scanned else "No",
        })
    st.dataframe(rows, hide_index=True, width="stretch")
    st.caption("Margins are measured from the page edge to the nearest visible text, image or drawing.")


# ---------------------------------------------------------------------------
# Sidebar: mode and requirements
# ---------------------------------------------------------------------------
MANUAL, AI_MODE = "Manual", "AI · plain English"

with st.sidebar:
    mode = st.radio("Check mode", [MANUAL, AI_MODE], horizontal=True, key="mode")

    if mode == MANUAL:
        st.markdown("### Requirements")
        st.caption("Turn on the rules your printer, professor or submission portal requires.")

        use_pages = st.toggle("Maximum number of pages", value=True)
        max_pages = st.number_input("Max pages", min_value=1, max_value=2000, value=5, step=1,
                                    disabled=not use_pages, label_visibility="collapsed")

        use_paper = st.toggle("Paper size", value=True)
        paper_size = st.radio("Paper size", ["US Letter", "A4"], horizontal=True,
                              disabled=not use_paper, label_visibility="collapsed")

        use_font = st.toggle("Minimum font size", value=True)
        min_font = st.number_input("Minimum font size (pt)", min_value=1.0, max_value=72.0, value=10.0,
                                   step=0.5, format="%.1f", disabled=not use_font)

        use_margin = st.toggle("Minimum margins", value=True)
        min_margin = st.number_input("Minimum margin (inches)", min_value=0.0, max_value=3.0, value=1.0,
                                     step=0.125, format="%.3f", disabled=not use_margin)
        if use_margin:
            st.caption(f"= {min_margin * MM_PER_INCH:.1f} mm on every side")
    else:
        st.markdown("### Requirements in plain English")
        st.caption("Describe the rules the way your professor or print shop wrote them.")
        requirements_text = st.text_area(
            "Requirements", value=AI_EXAMPLE, height=140, max_chars=MAX_REQUIREMENTS_CHARS,
            label_visibility="collapsed", key="ai_text",
        )
        run_ai = st.button("✨ Run AI analysis", type="primary", width="stretch", key="run_ai")
        st.caption(
            f"Model {MODEL_NAME} via Portkey · max {USAGE_LIMITS.request_limit} API calls, "
            f"{USAGE_LIMITS.tool_calls_limit} tool calls and {USAGE_LIMITS.total_tokens_limit:,} tokens per run. "
            "Only your requirements and the checker's measurements are sent — never the PDF or its text."
        )

    st.divider()
    key_loaded = bool(os.getenv("PORTKEY_API_KEY"))
    env_note = ", ".join(p.parent.name for p in ENV_FILES) or "none found"
    st.caption(f"🔐 .env loaded from: {env_note} · Portkey key {'detected' if key_loaded else 'not found'}")

# ---------------------------------------------------------------------------
# Header and upload
# ---------------------------------------------------------------------------
st.markdown(
    """
<div class="hero">
  <div>
    <div class="brand">Print<span>Proof</span> AI</div>
    <div class="tagline">Upload a PDF and see, page by page, whether it is ready to print or submit.</div>
  </div>
  <div><span class="chip">Measured checks · AI agent</span></div>
</div>
""",
    unsafe_allow_html=True,
)

if "pdf" not in st.session_state:
    st.session_state.pdf = None  # (file_name, bytes)

up_col, sample_col = st.columns([3, 1.2], gap="medium")
with up_col:
    uploaded = st.file_uploader("Upload a PDF", type=["pdf"], max_upload_size=MAX_UPLOAD_MB,
                                label_visibility="collapsed")
with sample_col:
    st.markdown('<div class="muted" style="font-size:.85rem;margin-bottom:6px;">No file handy? Try a sample:</div>',
                unsafe_allow_html=True)
    if st.button("✅ Good sample", width="stretch", key="good_sample"):
        st.session_state.pdf = ("good_sample.pdf", (SAMPLE_DIR / "good_sample.pdf").read_bytes())
    if st.button("⚠️ Problem sample", width="stretch", key="bad_sample"):
        st.session_state.pdf = ("bad_sample.pdf", (SAMPLE_DIR / "bad_sample.pdf").read_bytes())

if uploaded is not None:
    if uploaded.size > MAX_UPLOAD_MB * 1024 * 1024:
        st.error(f"This file is larger than {MAX_UPLOAD_MB} MB. Please upload a smaller PDF.")
        st.stop()
    current = (uploaded.name, uploaded.getvalue())
else:
    current = st.session_state.pdf

if current is None:
    st.markdown(
        """
<div class="empty">
  <h3>Drop a PDF to start the preflight check</h3>
  <div>The PDF is measured locally. In AI mode only your requirements and the measurements go to the AI — never the file.</div>
  <div class="steps">
    <div class="step"><b>1</b>Set requirements or describe them in English</div>
    <div class="step"><b>2</b>Upload a PDF</div>
    <div class="step"><b>3</b>Review pass / fail / needs review</div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )
    st.stop()

file_name, pdf_bytes = current

# ---------------------------------------------------------------------------
# Manual mode (Step 1, unchanged behaviour)
# ---------------------------------------------------------------------------
if mode == MANUAL:
    selected = dict(
        max_pages=int(max_pages) if use_pages else None,
        paper_size=paper_size if use_paper else None,
        min_font=float(min_font) if use_font else None,
        min_margin=float(min_margin) if use_margin else None,
    )
    if not any(v is not None for v in selected.values()):
        st.info("Turn on at least one requirement in the sidebar to check this PDF.")
        st.stop()

    try:
        with st.spinner("Measuring pages, fonts and margins…"):
            report = run_check(pdf_bytes, file_name, **selected)
    except PDFCheckError as exc:
        st.error(str(exc))
        st.stop()

    render_verdict(report.overall_status, f"{file_name} · {count_line(report.results)}")
    render_metrics(document_tiles(report, selected["max_pages"]))
    not_checked = tuple(name for name, on in (("Maximum number of pages", use_pages), ("Paper size", use_paper),
                                              ("Minimum font size", use_font), ("Minimum margins", use_margin))
                        if not on)
    st.write("")
    download_report(manual_report_html(pdf_bytes, file_name, *selected.values(), not_checked), file_name,
                    "download_manual")
    tab_results, tab_preview, tab_pages = st.tabs(["Requirement results", "Page preview", "Page-by-page data"])
    with tab_results:
        for result in report.results:
            render_result_card(result)
    with tab_preview:
        render_preview(pdf_bytes, report, report.results, selected["min_margin"], "manual")
    with tab_pages:
        render_page_table(report)
    st.stop()

# ---------------------------------------------------------------------------
# AI mode (Step 2)
# ---------------------------------------------------------------------------
try:
    doc_report = run_check(pdf_bytes, file_name, None, None, None, None)  # page data only, no checks
except PDFCheckError as exc:
    st.error(str(exc))
    st.stop()

file_key = hashlib.sha256(pdf_bytes).hexdigest()
if run_ai:
    if not requirements_text.strip():
        st.warning("Describe at least one requirement before running the AI analysis.")
    elif not os.getenv("PORTKEY_API_KEY"):
        st.error("PORTKEY_API_KEY is missing. Add it to .env in this folder or the folder above.")
    else:
        with st.spinner(f"{MODEL_NAME} is reading your requirements and running the checks…"):
            try:
                outcome = run_ai_check(pdf_bytes, file_name, requirements_text)
            except (ValueError, PDFCheckError) as exc:
                st.error(str(exc))
                st.stop()
        st.session_state.ai_run = {"file_key": file_key, "text": requirements_text.strip(), "outcome": outcome}

ai_run = st.session_state.get("ai_run")
if not ai_run or ai_run["file_key"] != file_key:
    render_metrics(document_tiles(doc_report, None))
    st.markdown(
        '<div class="empty" style="margin-top:18px"><h3>Ready for AI analysis</h3>'
        '<div>Describe the requirements in the sidebar and click <b>Run AI analysis</b>. '
        'The AI calls our PDF checker as tools and explains only what it measured.</div></div>',
        unsafe_allow_html=True,
    )
    st.stop()

outcome = ai_run["outcome"]
if ai_run["text"] != requirements_text.strip():
    st.info("You edited the requirements. The results below are for the previous text — run the AI again to update.")

if outcome.error:
    st.error(f"The AI analysis did not finish: {outcome.error}")

checks = outcome.deps.checks_run()
check_results = [r.check_result for r in checks]
report_ai = outcome.report

if report_ai:
    overall = outcome.verified_overall
    verified = not outcome.mismatches
    render_verdict(overall, f"{file_name} · {count_line(check_results)} · "
                            + ("AI report matches the measured results" if verified
                               else "AI report differed from the measurements — showing measured results"))
elif checks:  # the AI report was rejected, but the measured results are still real
    render_verdict(outcome.verified_overall,
                   f"{file_name} · {count_line(check_results)} · measured results only (AI report rejected)")

usage = outcome.usage
render_metrics([
    ("API calls", str(usage.get("requests", 0)), f"limit {USAGE_LIMITS.request_limit}"),
    ("Tool calls", str(usage.get("tool_calls", 0)), f"limit {USAGE_LIMITS.tool_calls_limit}"),
    ("Tokens used", f"{usage.get('total_tokens', 0):,}",
     f"{usage.get('input_tokens', 0):,} in · {usage.get('output_tokens', 0):,} out"
     + (f" · {usage['tokens_from_portkey_cache']:,} from Portkey cache" if usage.get("tokens_from_portkey_cache") else "")),
    ("Run time", f"{outcome.seconds:.1f} s", f"run {outcome.run_id}"),
])

if report_ai:
    st.markdown('<div class="section-title">What the AI understood</div>', unsafe_allow_html=True)
    req_html = []
    for req in report_ai.understood_requirements:
        badge = ('<span class="pill pass">Checked</span>' if req.checkable
                 else '<span class="pill review">Not checkable</span>')
        note = f'<div class="req-note">{esc(req.note)}</div>' if req.note else ""
        req_html.append(
            f'<div class="req"><div class="card-head"><div><div class="req-kind">{esc(req.kind.replace("_", " "))}</div>'
            f'<div class="req-main">{esc(req.interpreted_as)}</div>'
            f'<div class="req-quote">“{esc(req.user_wording)}”</div></div>{badge}</div>{note}</div>'
        )
    st.markdown(f'<div class="req-grid">{"".join(req_html)}</div>', unsafe_allow_html=True)
    if report_ai.clarifications_needed:
        items = "".join(f"<li>{esc(c)}</li>" for c in report_ai.clarifications_needed)
        st.markdown(f'<div class="clarify"><b>Needs your input</b><ul>{items}</ul></div>', unsafe_allow_html=True)
    st.markdown(f'<div class="ai-summary"><span>AI summary</span>{esc(report_ai.summary)}</div>',
                unsafe_allow_html=True)

margin_record = outcome.deps.latest_check("check_min_margins")
margin_in = None
if margin_record:
    factor = {"in": 1.0, "mm": 1 / MM_PER_INCH, "cm": 10 / MM_PER_INCH}[margin_record.arguments["unit"]]
    margin_in = margin_record.arguments["min_margin"] * factor

if report_ai:
    reports = st.session_state.setdefault("ai_reports", {})
    if outcome.run_id not in reports:
        names = {r.tool_name: r.check_result.name for r in checks}
        reports[outcome.run_id] = build_html_report(
            file_name=file_name, pdf_bytes=pdf_bytes, mode="AI", results=check_results,
            pages=doc_report.pages, page_count=doc_report.page_count,
            not_checked=[u.user_wording for u in report_ai.understood_requirements if not u.checkable],
            min_margin_in=margin_in, overall=outcome.verified_overall,
            ai=AIDetails(
                requirements_text=ai_run["text"],
                understood=[u.model_dump() for u in report_ai.understood_requirements],
                clarifications=report_ai.clarifications_needed, summary=report_ai.summary,
                explanations={names[f.tool_name]: f.explanation for f in report_ai.findings if f.tool_name in names},
                model=MODEL_NAME, run_id=outcome.run_id, usage=outcome.usage,
            ),
        )
    st.write("")
    download_report(reports[outcome.run_id], file_name, "download_ai")

st.write("")
tab_results, tab_preview, tab_pages, tab_trace = st.tabs(
    ["AI results", "Page preview", "Page-by-page data", "Agent trace"])

with tab_results:
    explanations = {f.tool_name: f.explanation for f in report_ai.findings} if report_ai else {}
    if not checks:
        st.info("The AI did not run any checks. See “What the AI understood” and the clarifications above.")
    for record in checks:
        render_result_card(record.check_result, explanations.get(record.tool_name))
    if outcome.mismatches:
        st.warning("The AI's report did not fully match the measurements, so the cards above show the "
                   "measured results: " + " ".join(outcome.mismatches))

with tab_preview:
    render_preview(pdf_bytes, doc_report, check_results, margin_in, "ai")

with tab_pages:
    render_page_table(doc_report)

with tab_trace:
    st.markdown('<div class="section-title">Tools the agent used</div>', unsafe_allow_html=True)
    if outcome.deps.tool_records:
        st.dataframe([
            {"#": i, "Tool": r.tool_name,
             "Arguments": ", ".join(f"{k}={v}" for k, v in r.arguments.items()) or "—",
             "Result": r.output.get("status", "overview")}
            for i, r in enumerate(outcome.deps.tool_records, 1)
        ], hide_index=True, width="stretch")
    else:
        st.caption("No tools were called.")
    st.markdown('<div class="section-title">API calls (real usage reported by Portkey)</div>', unsafe_allow_html=True)
    if outcome.api_calls:
        st.dataframe([
            {"Call": i, "Model": c["model"], "Input tokens": c["input_tokens"], "Output tokens": c["output_tokens"],
             "Asked for": ", ".join(c["tools_requested"]) or ("rejected" if c.get("rejected") else "text answer"),
             "Portkey cache": c.get("portkey_cache_status") or "—",
             "HTTP": c.get("http_status", 200)}
            for i, c in enumerate(outcome.api_calls, 1)
        ], hide_index=True, width="stretch")
        st.caption("Portkey cache HIT means Portkey returned a saved answer for an identical request; "
                   "its token counts repeat the original call.")
    st.caption(f"Run {outcome.run_id} is recorded in output/audit_trail.json (new runs are appended).")

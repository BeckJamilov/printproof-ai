"""PrintProof AI — Excel Print Optimizer (Streamlit page).

Upload a workbook, choose the worksheet and columns, pick Readability First or Page Count First,
press Optimize for Printing, review the preview and download a verified, print-ready PDF.
"""

from __future__ import annotations

import hashlib
import html
import os
import sys
import tempfile
import time
from pathlib import Path

import streamlit as st

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from agent import load_project_env  # noqa: E402
from excel_print.columns import (ColumnInputError, check_against_sheet, format_columns, parse_area,  # noqa: E402
                                 parse_columns)
from excel_print.excel_engine import excel_available  # noqa: E402
from excel_print.model import OptimizeSettings  # noqa: E402
from excel_print.optimizer import optimize  # noqa: E402
from excel_print.verify import render_previews  # noqa: E402
from excel_print.workbook_info import WorkbookReadError, ai_metadata, read_workbook_info  # noqa: E402

load_project_env()
MAX_UPLOAD_MB = 50

st.markdown("""
<style>
:root { --bg:#0a0a0d; --panel:#131318; --panel-2:#1b1b22; --line:#2a2a33; --pink:#ff3d8b; --pink-soft:#ff8cbc;
  --text:#f5f3f7; --muted:#a4a1ad; --pass:#3ddc97; --fail:#ff4d6d; --review:#ffb547; }
.stApp { background: radial-gradient(1200px 500px at 85% -10%, rgba(255,61,139,.16), transparent 60%), var(--bg); color: var(--text); }
header[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 2rem; max-width: 1250px; }
h1, h2, h3, h4, p, label, span, li { color: var(--text); }
section[data-testid="stSidebar"] { background: #0f0f13; border-right: 1px solid var(--line); }
section[data-testid="stSidebar"] * { color: var(--text); }
[data-baseweb="input"], [data-baseweb="input"] *, [data-baseweb="base-input"], [data-baseweb="select"] > div,
[data-testid="stNumberInputContainer"], .react-aria-ComboBox > div { background-color: var(--panel-2) !important; border-color: var(--line) !important; }
/* Text inputs and text areas (Streamlit 1.66 paints the light background on the *RootElement) */
[data-testid="stTextInputRootElement"], [data-testid="stTextAreaRootElement"] {
  background-color: var(--panel-2) !important; border: 1px solid #3a3a46 !important; border-radius: 10px !important; }
[data-testid="stTextInputRootElement"]:focus-within, [data-testid="stTextAreaRootElement"]:focus-within {
  border-color: var(--pink) !important; box-shadow: 0 0 0 1px var(--pink) !important; }
input, textarea { color: var(--text) !important; -webkit-text-fill-color: var(--text) !important; caret-color: var(--pink) !important;
  background-color: transparent !important; font-size: 1rem !important; }
input::placeholder, textarea::placeholder { color: #8d8996 !important; -webkit-text-fill-color: #8d8996 !important; opacity: 1 !important; }
input::selection, textarea::selection { background: rgba(255,61,139,.45); color: #fff; }
textarea { background: var(--panel-2) !important; }
[data-testid="stTextInput"] input { font-family: ui-monospace, "Cascadia Mono", Consolas, monospace !important; letter-spacing: .02em; }
[data-testid="stNumberInput"] button { background: var(--panel-2) !important; color: var(--text) !important; border-color: var(--line) !important; }
.react-aria-Popover, [role="listbox"] { background-color: var(--panel-2) !important; }
[role="option"] { background-color: var(--panel-2) !important; color: var(--text) !important; }
[data-testid="stFileUploaderDropzone"] { background: var(--panel) !important; border: 1.5px dashed rgba(255,61,139,.55) !important; border-radius: 16px; }
[data-testid="stFileUploaderDropzone"] * { color: var(--muted) !important; }
[data-testid="stFileUploaderDropzone"] button { background: var(--pink) !important; border: none !important; }
[data-testid="stFileUploaderDropzone"] button * { color: #fff !important; }
.stButton > button, [data-testid="stDownloadButton"] button { background: var(--panel-2) !important; color: var(--text) !important; border: 1px solid var(--line) !important; border-radius: 12px; font-weight: 600; }
.stButton > button[kind="primary"], [data-testid="stDownloadButton"] button[kind="primary"] { background: linear-gradient(135deg, #ff3d8b, #c2185b) !important; border: none !important; color: #fff !important; }
[data-testid="stDownloadButton"] button * , .stButton > button * { color: inherit !important; }
div[data-testid="stExpander"] { background: var(--panel); border: 1px solid var(--line); border-radius: 14px; }
.hero { display:flex; justify-content:space-between; align-items:center; gap:20px; padding: 24px 28px; border-radius: 22px;
  background: linear-gradient(135deg, #17171d 0%, #120d12 60%, #2a0f1e 100%); border: 1px solid var(--line); margin-bottom: 18px; }
.brand { font-size: 2rem; font-weight: 800; letter-spacing: -0.03em; } .brand span { color: var(--pink); }
.tagline { color: var(--muted); margin-top: 4px; }
.chip.filter { border-color: rgba(61,220,151,.5); color: #8ef0c4; background: rgba(61,220,151,.08); }
.colnote { color: var(--muted); font-size: .8rem; margin-top: 2px; }
.chip { display:inline-block; padding: 4px 11px; border-radius: 999px; font-size: .75rem; font-weight: 700; letter-spacing: .05em;
  border: 1px solid rgba(255,61,139,.45); color: var(--pink-soft); background: rgba(255,61,139,.08); margin: 2px 4px 2px 0; }
.step { font-size: .78rem; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; color: var(--pink); margin: 14px 0 4px; }
.verdict { border-radius: 16px; padding: 16px 20px; margin: 8px 0 14px; border: 1px solid; }
.verdict h3 { margin: 0 0 4px; font-size: 1.2rem; } .verdict p { margin: 0; color: var(--muted); }
.v-pass { background: rgba(61,220,151,.08); border-color: rgba(61,220,151,.4); }
.v-fail { background: rgba(255,77,109,.08); border-color: rgba(255,77,109,.45); }
.v-review { background: rgba(255,181,71,.08); border-color: rgba(255,181,71,.45); }
.metric { background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 12px 14px; }
.metric .k { color: var(--muted); font-size: .72rem; text-transform: uppercase; letter-spacing: .08em; font-weight: 600; }
.metric .v { font-size: 1.35rem; font-weight: 800; margin-top: 2px; } .metric .s { color: var(--muted); font-size: .78rem; }
.note { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 10px 14px; color: #dcd9e2; font-size: .9rem; margin: 6px 0; }
.check { padding: 7px 10px; border-radius: 10px; background: var(--panel-2); margin: 5px 0; font-size: .88rem; }
.chip { white-space: nowrap; }
.tools { display:grid; grid-template-columns: 2fr 1fr; gap:12px; margin: 0 0 6px; }
.tool { background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 12px 16px; color: #dcd9e2; font-size: .92rem; }
.tool.main { border-color: rgba(255,61,139,.55); box-shadow: 0 0 0 1px rgba(255,61,139,.25) inset; }
.tool .req { display:block; margin-top:6px; color: var(--review); font-weight: 600; }
.ok { color: var(--pass); font-weight: 800; } .bad { color: var(--fail); font-weight: 800; } .na { color: var(--review); font-weight: 800; }
</style>
""", unsafe_allow_html=True)

esc = html.escape


def metric(col, k, v, s=""):
    col.markdown(f'<div class="metric"><div class="k">{esc(k)}</div><div class="v">{esc(str(v))}</div>'
                 f'<div class="s">{esc(s)}</div></div>', unsafe_allow_html=True)


# ---- defaults & AI-filled values (applied before widgets are created) ----------------------------
DEFAULTS = {"xl_cols": "D, E, J, BW, BX, BY, BZ", "xl_filter": "BX, BY", "xl_zero": True, "xl_other": True,
            "xl_mode": "Readability First", "xl_minfont": 6.0, "xl_maxpages": 1, "xl_paper": "A3",
            "xl_orient": "Landscape", "xl_margins": "Compact", "xl_extend": False, "xl_repeat": True, "xl_renumber": True}
# Streamlit drops (or returns a stale default for) a widget's value when the widget is not drawn in a
# run — e.g. before a workbook is uploaded, or after visiting the PDF Checker page. So every setting is
# saved under "_keep_<key>" the moment it changes (on_change runs before this script) and restored
# from there before the widgets are drawn.
def _remember(key: str) -> None:
    st.session_state["_keep_" + key] = st.session_state[key]


def keep(key: str) -> dict:
    """Widget arguments for a remembered setting."""
    return {"key": key, "on_change": _remember, "args": (key,)}


for k, v in DEFAULTS.items():
    st.session_state.setdefault("_keep_" + k, v)
for k, v in (st.session_state.pop("xl_pending", None) or {}).items():   # settings filled in by the AI helper
    st.session_state["_keep_" + k] = v
for k in DEFAULTS:
    st.session_state[k] = st.session_state["_keep_" + k]

with st.sidebar:
    st.page_link("pages/excel_print_optimizer.py", label="Excel Print Optimizer", icon="📊")
    st.page_link("pages/pdf_checker.py", label="PDF Checker", icon="🖨️")
    st.divider()
    ok, why = excel_available()
    st.caption(("✅ " if ok else "⚠️ ") + why)
    st.caption("Your workbook is processed on this computer by Microsoft Excel. The original file is never changed, "
               "and nothing from the workbook is sent to an AI service.")

st.markdown("""
<div class="hero"><div><div class="brand">PrintProof AI · Excel Print <span>Optimizer</span></div>
<div class="tagline">Turn a large Excel worksheet into a concise, readable, verified PDF: print only the columns and rows
that matter, keep titles, units, headings, subtotals and comments, and let the app find the layout.</div></div>
<div><span class="chip">Tool 1 of 2</span></div></div>""", unsafe_allow_html=True)
st.markdown(
    '<div class="tools"><div class="tool main"><b>📊 Excel Print Optimizer</b> — prepare a workbook for printing '
    '(this page). Deterministic Python + Microsoft Excel; every PDF is measured before it is called verified. '
    '<span class="req">Needs Windows with Microsoft Excel installed.</span></div>'
    '<div class="tool"><b>🖨️ PDF Checker</b> — already have a PDF? Check it against page, paper, font and margin '
    'requirements, optionally written in plain English for the AI agent. Works without Excel.</div></div>',
    unsafe_allow_html=True)
st.markdown(
    '<div class="note"><b>Why this tool exists.</b> PrintProof AI began as a PDF Checker for finished documents. When we '
    'showed it to a former colleague who works with large investment budgets, it became clear that his harder problem came '
    'earlier: turning a huge Excel workbook — many rows, many financial columns, sections, subtotals and comments — into a '
    'readable printout without hiding columns, filtering rows and reprinting by hand again and again. Excel Print Optimizer '
    'is our answer; the PDF Checker remains for documents that already exist.</div>', unsafe_allow_html=True)
st.page_link("pages/pdf_checker.py", label="Open the PDF Checker →", icon="🖨️")

if not ok:
    st.error(f"The spreadsheet rendering engine is not available: {why} This feature needs Microsoft Excel on Windows.")

# ---- Step 1: workbook --------------------------------------------------------------------------------
st.markdown('<div class="step">1 · Workbook</div>', unsafe_allow_html=True)
up = st.file_uploader("Excel workbook (.xlsx or .xlsm — macros are never run)", type=["xlsx", "xlsm"],
                      max_upload_size=MAX_UPLOAD_MB)
if up is None:
    st.markdown('<div class="note">Upload a workbook to start. Typical flow: choose the worksheet and the columns to print, '
                'pick <b>Readability First</b> or <b>Page Count First</b>, press <b>Optimize for printing</b>, check the '
                'preview and download the PDF.</div>', unsafe_allow_html=True)
    st.stop()

data = up.getvalue()
digest = hashlib.sha256(data).hexdigest()
tmp_dir = Path(tempfile.gettempdir()) / "printproof_uploads"
tmp_dir.mkdir(exist_ok=True)
for old in tmp_dir.iterdir():  # do not keep financial workbooks around: remove uploads older than 24 h
    try:
        if old.is_file() and time.time() - old.stat().st_mtime > 24 * 3600:
            old.unlink()
    except OSError:
        pass
src_path = tmp_dir / f"{digest[:16]}{Path(up.name).suffix.lower()}"
if not src_path.exists():
    src_path.write_bytes(data)
try:
    sheets = read_workbook_info(src_path)
except WorkbookReadError as exc:
    st.error(str(exc))
    st.stop()
names = [s.name for s in sheets]
default_sheet = next((i for i, s in enumerate(sheets) if s.state == "visible"), 0)
sheet_name = st.selectbox("Worksheet", names, index=default_sheet,
                          format_func=lambda n: n + ("" if next(s for s in sheets if s.name == n).state == "visible" else "  (hidden sheet)"))
info = next(s for s in sheets if s.name == sheet_name)
st.markdown(f'<div class="note">Print area: <b>{esc(info.print_area or "none — the used range " + info.dimension + " will be used")}</b>'
            f' · used range {esc(info.dimension or "?")} · {len(info.hidden_columns)} hidden column(s). '
            'Rows and columns hidden in the workbook stay hidden.</div>', unsafe_allow_html=True)

# ---- Step 2: what to print ----------------------------------------------------------------------------
st.markdown('<div class="step">2 · Columns and rows</div>', unsafe_allow_html=True)
try:
    used_last = parse_area(info.dimension)[2] if info.dimension and ":" in info.dimension else None
except ColumnInputError:
    used_last = None
try:
    pa = parse_area(info.print_area) if info.print_area else None
except ColumnInputError:
    pa = None
area_cols = (pa[0], pa[2]) if pa else ((1, used_last) if used_last else None)
area_name = info.print_area or (f"used range {info.dimension}" if info.dimension else "the sheet")


def column_field(label: str, key: str, help_text: str, chip_class: str):
    """Text input + exactly what was understood (chips in the order typed) + problems. Returns the selection."""
    text = st.text_input(label, **keep(key), help=help_text, placeholder="e.g. D, E, J, BW, BX, BY, BZ")
    try:
        sel = parse_columns(text)
    except ColumnInputError as exc:
        st.error(str(exc))
        return None, []
    errors, outside = check_against_sheet(sel, used_last, area_cols)
    st.markdown("".join(f'<span class="chip {chip_class}">{esc(l)}</span>' for l in sel.entered_letters) +
                f'<div class="colnote">{len(sel.indexes)} column(s): {esc(format_columns(sel.indexes))}'
                + (" · printed left to right in worksheet order" if sel.entered != sel.indexes else "")
                + ("<br>" + esc(" ".join(sel.notes)) if sel.notes else "") + "</div>", unsafe_allow_html=True)
    for e in errors:
        st.error(e)
    return (None if errors else sel), outside


c1, c2 = st.columns(2)
with c1:
    sel, outside_print = column_field("Columns to print", "xl_cols",
                                      "Excel letters separated by commas, e.g. D, E, J, BW, BX, BY, BZ. Ranges like BW-BZ "
                                      "are fine. Lower case and extra spaces are accepted.", "")
    cols_ok = sel is not None
    st.checkbox("Extend the print area to include selected columns outside it", **keep("xl_extend"))
    if cols_ok and outside_print:
        msg = (f"Column(s) {', '.join(outside_print)} are outside the existing print area ({area_name}). ")
        if st.session_state.xl_extend:
            st.info(msg + "They will be printed because “Extend the print area” is ticked (only in the temporary copy).")
        else:
            st.warning(msg + "Tick “Extend the print area” to print them, or remove them from the list.")
            cols_ok = False
with c2:
    filt, _ = column_field("Columns that decide whether a row is relevant", "xl_filter",
                           "A row is left out when all of these are empty (or zero, if ticked below) and it has no "
                           "comment. They do not have to be printed — their values are read from the worksheet.", "filter")
    filt_ok = filt is not None
    if filt_ok and cols_ok:
        unprinted = [c for c in filt.entered_letters if c not in set(sel.letters)]
        if unprinted:
            st.caption(f"{', '.join(unprinted)} will be used for filtering but not printed.")
    st.checkbox("Treat 0 like an empty cell in these columns", **keep("xl_zero"),
                help="Untick if a zero is a meaningful figure in your report.")
    st.checkbox("Keep rows that have values in other selected number columns (safer)", **keep("xl_other"))
    st.checkbox("Renumber the printed rows 1, 2, 3, … (nested numbers like 4.1 follow their parent)", **keep("xl_renumber"),
                help="Only the temporary copy is changed — the original workbook keeps its numbers.")
st.caption("A row is printed when its filter columns have a non-zero value or it has a comment/note (or an error). "
           "Headings and totals are printed only when rows below them are printed — formatting alone never keeps a row. "
           "Every decision is listed after optimizing.")

with st.expander("✨ Describe what you want in your own words (optional AI help)"):
    st.caption("The AI only receives your text and the sheet's structure (print area, column letters, row counts) — "
               "never any figures, names or comments. It fills in the form; you check it before printing.")
    instr = st.text_area("Instructions", placeholder="e.g. Show D, E, J and BW to BZ. Leave out rows where BX and BY are empty. "
                         "Fit everything on one A3 landscape page.", height=90, key="xl_instr")
    if st.button("Fill the settings from my instructions", key="xl_ai"):
        if not os.getenv("PORTKEY_API_KEY"):
            st.error("PORTKEY_API_KEY is missing (.env in the project folder or the folder above).")
        else:
            from excel_print.ai_settings import interpret_instructions
            with st.spinner("Asking gpt-6-luna to interpret your instructions…"):
                req, rec = interpret_instructions(instr, ai_metadata(info, len(sheets)))
            st.session_state["xl_ai_result"] = (req.model_dump() if req else None, rec)
            if req:
                pending = {}
                if req.columns: pending["xl_cols"] = req.columns
                if req.filter_columns: pending["xl_filter"] = req.filter_columns
                if req.zero_is_empty is not None: pending["xl_zero"] = req.zero_is_empty
                if req.keep_rows_with_other_values is not None: pending["xl_other"] = req.keep_rows_with_other_values
                if req.mode: pending["xl_mode"] = "Readability First" if req.mode == "readability" else "Page Count First"
                if req.min_font_pt: pending["xl_minfont"] = float(req.min_font_pt)
                if req.max_pages: pending["xl_maxpages"] = int(req.max_pages)
                if req.paper: pending["xl_paper"] = req.paper
                if req.orientation: pending["xl_orient"] = req.orientation.capitalize()
                st.session_state["xl_pending"] = pending
                st.rerun()
    if st.session_state.get("xl_ai_result"):
        req, rec = st.session_state["xl_ai_result"]
        if rec.get("error"):
            st.error(rec["error"])
        if req:
            if req.get("assumptions"):
                st.markdown('<div class="note"><b>Assumptions:</b> ' + esc(" ".join(req["assumptions"])) + "</div>", unsafe_allow_html=True)
            if req.get("unclear"):
                st.warning("Please check: " + " ".join(req["unclear"]))
        u = rec.get("usage") or {}
        st.caption(f"AI run {rec.get('run_id')} · {u.get('total_tokens', 0):,} tokens · Portkey cache {rec.get('portkey_cache')} · "
                   f"sent only: {rec.get('metadata_sent', '').replace(chr(10), '; ')}")

# ---- Step 3: requirements ------------------------------------------------------------------------------
st.markdown('<div class="step">3 · Printing requirements</div>', unsafe_allow_html=True)
m1, m2, m3, m4 = st.columns([1.3, 1, 1, 1])
with m1:
    mode = st.radio("Optimization mode", ["Readability First", "Page Count First"], **keep("xl_mode"),
                    help="Readability First: never print text smaller than your minimum; use more pages if needed. "
                         "Page Count First: fit within your page limit with the largest text possible.")
    if mode == "Readability First":
        st.number_input("Minimum printed font size (pt)", min_value=3.0, max_value=20.0, step=0.5, **keep("xl_minfont"))
    else:
        st.number_input("Maximum number of pages", min_value=1, max_value=50, step=1, **keep("xl_maxpages"))
with m2:
    st.radio("Paper", ["A3", "A4"], **keep("xl_paper"), horizontal=True)
with m3:
    st.selectbox("Orientation", ["Landscape", "Portrait", "Auto"], **keep("xl_orient"))
with m4:
    st.selectbox("Margins", ["Compact", "Narrow", "Normal"], **keep("xl_margins"),
                 help="Compact: the smallest safe margins (about 6 mm at the sides and top). Every PDF is checked to "
                      "keep the table at least 5 mm from the paper edge.")
    st.checkbox("Repeat the table header on every page", **keep("xl_repeat"))

ready = ok and cols_ok and filt_ok
go = st.button("Optimize for printing", type="primary", disabled=not ready, width="stretch")

if go:
    s = OptimizeSettings(
        columns_text=st.session_state.xl_cols, filter_columns_text=st.session_state.xl_filter,
        zero_is_empty=st.session_state.xl_zero, keep_rows_with_other_values=st.session_state.xl_other,
        paper=st.session_state.xl_paper, orientation=st.session_state.xl_orient.lower(),
        mode="readability" if st.session_state.xl_mode == "Readability First" else "pages",
        min_font_pt=float(st.session_state.xl_minfont), max_pages=int(st.session_state.xl_maxpages),
        margins=st.session_state.xl_margins.lower(), extend_print_area=st.session_state.xl_extend,
        repeat_header=st.session_state.xl_repeat, renumber=st.session_state.xl_renumber)
    with st.status("Optimizing for printing…", expanded=True) as status:
        result = optimize(src_path, sheet_name, s, progress=lambda m: status.write(m))
        status.update(label="Done" if result.success else "Finished with problems", state="complete" if result.success else "error",
                      expanded=False)
    st.session_state["xl_result"] = (digest, sheet_name, result, Path(up.name).stem)

saved = st.session_state.get("xl_result")
if not saved or saved[0] != digest or saved[1] != sheet_name:
    st.stop()
_, _, res, stem = saved
sm = res.summary

# ---- Results ---------------------------------------------------------------------------------------------
st.markdown('<div class="step">4 · Result</div>', unsafe_allow_html=True)
if res.success and sm.get("readability", "ok") != "ok":
    cls, title = "v-review", f"Verified, but the printed text is {sm['readability']}"
elif res.success:
    cls, title = "v-pass", "Print-ready PDF created and verified"
elif res.pdf_bytes:
    cls, title = "v-review", "PDF created, but it did not pass every check"
else:
    cls, title = "v-fail", "No print-ready PDF could be created"
st.markdown(f'<div class="verdict {cls}"><h3>{esc(title)}</h3><p>{esc(res.message)}</p></div>', unsafe_allow_html=True)
if sm.get("pages"):
    k = st.columns(5)
    metric(k[0], "Pages", sm["pages"], f"{sm.get('paper')} {sm.get('orientation', '')}")
    metric(k[1], "Print scale", f"{sm.get('zoom_percent')} %", sm.get("layout", ""))
    metric(k[2], "Smallest printed text", f"{sm.get('measured_min_font_pt', 0):.1f} pt" if sm.get("measured_min_font_pt") else "—",
           "measured in the PDF")
    metric(k[3], "Rows printed", sm.get("rows_printed"), f"{sm.get('rows_excluded_by_filter', 0)} left out by the filter")
    metric(k[4], "Columns", len(res.column_widths) or "—", sm.get("columns", ""))
for w in res.warnings:
    st.warning(w)
for line in sm.get("explanation", []):
    st.markdown(f'<div class="note">{esc(line)}</div>', unsafe_allow_html=True)

if res.pdf_bytes:
    name = f"{stem}_{sheet_name}_print.pdf"
    if res.success:
        st.download_button("⬇ Download print-ready PDF", data=res.pdf_bytes, file_name=name, mime="application/pdf", type="primary")
    else:
        st.download_button("⬇ Download anyway (NOT verified — see the problems below)", data=res.pdf_bytes,
                           file_name=name.replace(".pdf", "_UNVERIFIED.pdf"), mime="application/pdf")
    previews = render_previews(res.pdf_bytes, max_pages=4, zoom=1.0)
    st.markdown('<div class="step">Preview</div>', unsafe_allow_html=True)
    for i, png in enumerate(previews, 1):
        st.image(png, caption=f"Page {i} of {sm.get('pages', len(previews))}", width="stretch")
    if sm.get("pages", 0) > len(previews):
        st.caption(f"Showing the first {len(previews)} pages — download the PDF to see all {sm['pages']}.")

with st.expander("Verification checks"):
    for c in res.checks:
        mark = '<span class="ok">✓</span>' if c.passed else ('<span class="na">–</span>' if c.passed is None else '<span class="bad">✕</span>')
        st.markdown(f'<div class="check">{mark} <b>{esc(c.name)}</b> — {esc(c.detail)}</div>', unsafe_allow_html=True)
    for a in res.attempts:
        st.caption(a)

uncertain = [d for d in res.decisions if d.uncertain]
with st.expander(f"Rows that need a look ({len(uncertain)})"):
    if uncertain:
        st.dataframe([{"Row": d.row, "Printed": "yes" if d.keep else "no", "Why": d.reason, "Row text": d.label}
                      for d in uncertain], hide_index=True, width="stretch")
    else:
        st.caption("No uncertain decisions.")
with st.expander("All row decisions"):
    visible = [d for d in res.decisions if d.category != "hidden"]
    st.caption(f"{sm.get('rows_in_print_area', 0)} rows in the print area: {sm.get('rows_hidden_in_original', 0)} hidden in the "
               f"workbook (left hidden), {sm.get('rows_printed', 0)} printed, {sm.get('rows_excluded_by_filter', 0)} left out "
               f"by the filter, {sm.get('rows_excluded_empty', 0)} empty.")
    st.dataframe([{"Row": d.row, "Printed": "yes" if d.keep else "no", "New no.": d.printed_number, "Type": d.category,
                   "Why": d.reason, "Row text": d.label} for d in visible], hide_index=True, width="stretch")
with st.expander("Layout details and limitations"):
    if res.column_widths:
        st.write("Column widths at 100 % (mm): " + ", ".join(f"{k} {v}" for k, v in res.column_widths.items()))
    if sm.get("content_width_mm"):
        st.write(f"Measured on page 1: table {sm['content_width_mm']} × {sm['content_height_mm']} mm; unused space to the "
                 f"edges — left {sm['margin_left_mm']} mm, right {sm['margin_right_mm']} mm, top {sm['margin_top_mm']} mm, "
                 f"bottom {sm['margin_bottom_mm']} mm ({sm['page_area_used_percent']} % of the page area used).")
    for label in sm.get("metadata_carried_over", []):
        st.write(f"Header label kept although its column is not printed: {label}")
    if sm.get("rows_renumbered"):
        st.write(f"{sm['rows_renumbered']} printed row(s) were renumbered consecutively (temporary copy only).")
    for l in res.limitations:
        st.caption("• " + l)

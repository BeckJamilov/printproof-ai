"""Microsoft Excel as the rendering engine (Windows, via COM automation with pywin32).

Excel does what only a spreadsheet engine can do correctly: recalculate formulas, apply number
formats, fonts, fills, borders, merged cells and wrapping, measure row heights, paginate and export
the PDF. Python decides everything else.

Safety rules:
* The original workbook is never opened by Excel. A temporary copy is opened, never saved, and
  deleted afterwards.
* Macros are disabled, external links are not updated, alerts are suppressed.
* Cell values are never written. Only column widths, wrapping, row heights, hidden flags and page
  setup of the temporary copy are changed.
* Rows hidden in the original stay hidden; row heights are only changed on rows that will print.
* Excel is always closed; if it does not exit, its own process (and only that one) is ended.
"""

from __future__ import annotations

import math
import re
import shutil
import tempfile
import threading
import time
from pathlib import Path

from .columns import area_address, index_to_letter, parse_area
from .layout import Geometry
from .header_meta import MetaCell, MetaPlan
from .model import CellInfo, ColumnInfo, RowInfo, SheetData
from .workbook_info import frozen_rows

XL_VISIBLE = 12            # xlCellTypeVisible
XL_PAPER = {"A3": 8, "A4": 9}
XL_ORIENT = {"portrait": 1, "landscape": 2}
XL_NONE = -4142            # xlNone (no fill pattern)
WHITE = 16777215
MSO_DISABLE_MACROS = 3     # msoAutomationSecurityForceDisable
FOOTER = "&9Page &P of &N"

_EXCEL_LOCK = threading.Lock()   # one Excel job at a time


class ExcelUnavailableError(RuntimeError):
    """Microsoft Excel (or pywin32) is not available on this computer."""


class ExcelEngineError(RuntimeError):
    """Excel could not complete an operation on the workbook."""


XL_LEFT, XL_RIGHT = -4131, -4152
EDGE_LEFT, EDGE_TOP, EDGE_BOTTOM, EDGE_RIGHT = 7, 8, 9, 10


def _text_width_pt(text: str, size: float, bold: bool) -> float:
    """Generous estimate of the printed width of one line of text (Cyrillic capitals are wide)."""
    upper = sum(1 for ch in text if ch.isupper())
    factor = (0.62 if bold else 0.55) + 0.08 * upper / max(len(text), 1)
    return len(text) * size * factor


def excel_available() -> tuple[bool, str]:
    try:
        import pythoncom  # noqa: F401
        import win32com.client  # noqa: F401
    except ImportError:
        return False, "pywin32 is not installed (pip install pywin32), or this is not Windows."
    try:
        import winreg
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "Excel.Application"))
    except OSError:
        return False, "Microsoft Excel is not installed (Excel.Application is not registered)."
    return True, "Microsoft Excel found."


def _blocks(numbers: list[int]) -> list[tuple[int, int]]:
    """[3,4,5,9,10] -> [(3,5),(9,10)]"""
    out: list[tuple[int, int]] = []
    for n in sorted(numbers):
        if out and n == out[-1][1] + 1:
            out[-1] = (out[-1][0], n)
        else:
            out.append((n, n))
    return out


def _col_blocks(cols: list[int]) -> list[tuple[int, int]]:
    return _blocks(cols)


def _rows2d(value) -> list:
    """Normalise Range.Value2 / Formula of a single column to a flat list."""
    if not isinstance(value, tuple):
        return [value]
    return [row[0] if isinstance(row, tuple) else row for row in value]


class ExcelSession:
    """Open a temporary copy of a workbook in a private, invisible Excel instance."""

    def __init__(self, source: Path, timeout_s: float = 600):
        self.source = Path(source)
        self.timeout_s = timeout_s
        self.tmpdir: Path | None = None
        self.xl = None
        self.wb = None
        self.ws = None
        self.pid: int | None = None

    # ---- lifecycle -------------------------------------------------------------------------
    def __enter__(self) -> "ExcelSession":
        ok, why = excel_available()
        if not ok:
            raise ExcelUnavailableError(why)
        import pythoncom
        import win32com.client as win32
        import win32process
        _EXCEL_LOCK.acquire()
        try:
            pythoncom.CoInitialize()
            self.tmpdir = Path(tempfile.mkdtemp(prefix="printproof_xl_"))
            copy = self.tmpdir / ("workbook" + self.source.suffix.lower())
            shutil.copy2(self.source, copy)
            self.copy_path = copy
            self.meta_rows: list[int] = []
            try:
                self.xl = win32.DispatchEx("Excel.Application")
            except Exception as exc:
                raise ExcelUnavailableError(f"Excel could not be started: {exc}") from exc
            try:
                self.pid = win32process.GetWindowThreadProcessId(self.xl.Hwnd)[1]
            except Exception:
                self.pid = None
            for prop, val in (("Visible", False), ("DisplayAlerts", False), ("ScreenUpdating", False),
                              ("EnableEvents", False), ("AskToUpdateLinks", False),
                              ("AutomationSecurity", MSO_DISABLE_MACROS)):
                try:
                    setattr(self.xl, prop, val)
                except Exception:
                    pass
            try:
                self.wb = self.xl.Workbooks.Open(str(copy), UpdateLinks=0, ReadOnly=False, Password="",
                                                 IgnoreReadOnlyRecommended=True, AddToMru=False, Notify=False)
            except Exception as exc:
                raise ExcelEngineError(f"Excel could not open the workbook (it may be damaged or "
                                       f"password-protected): {exc}") from exc
            self._use_pdf_printer()
            return self
        except BaseException:
            self._shutdown()
            raise

    def __exit__(self, exc_type=None, exc=None, tb=None) -> None:
        # An exception raised inside the session keeps COM objects (worksheet, cells) alive in its traceback;
        # releasing them after Excel has quit fails with RPC errors (0x800706BE/0x800706BA). Release them first.
        if tb is not None:
            import traceback
            traceback.clear_frames(tb)
        import gc
        gc.collect()
        self._shutdown()

    def _use_pdf_printer(self) -> None:
        """Make this private Excel instance lay out pages for "Microsoft Print to PDF".

        Excel paginates and exports using the active printer's driver. With some drivers (e.g. Adobe
        PDF) a reduced print scale produces enlarged pages instead of smaller text, so the PDF would
        not be true A3. Microsoft Print to PDF (built into Windows 10/11) gives true paper sizes.
        Windows' default printer is not changed; Excel's previous active printer is restored on exit."""
        self.printer_note = ""
        try:
            self._original_printer = self.xl.ActivePrinter
        except Exception:
            self._original_printer = None
        if self._original_printer and self._original_printer.startswith("Microsoft Print to PDF"):
            return
        for i in range(0, 32):
            try:
                self.xl.ActivePrinter = f"Microsoft Print to PDF on Ne{i:02d}:"
                return
            except Exception:
                continue
        self.printer_note = ("“Microsoft Print to PDF” was not found, so Excel used its current printer "
                             f"({self._original_printer}); the paper-size check shows whether the result is true A3.")

    def _shutdown(self) -> None:
        try:
            if self.xl is not None and getattr(self, "_original_printer", None):
                self.xl.ActivePrinter = self._original_printer
        except Exception:
            pass
        try:
            if self.wb is not None:
                self.wb.Close(SaveChanges=False)
        except Exception:
            pass
        try:
            if self.xl is not None:
                self.xl.Quit()
        except Exception:
            pass
        self.ws = self.wb = self.xl = None
        import gc
        gc.collect()  # release COM references so Excel can exit
        if self.pid:
            self._wait_or_kill(self.pid)
        try:
            import pythoncom
            pythoncom.CoUninitialize()
        except Exception:
            pass
        if self.tmpdir:
            shutil.rmtree(self.tmpdir, ignore_errors=True)
        if _EXCEL_LOCK.locked():
            try:
                _EXCEL_LOCK.release()
            except RuntimeError:
                pass

    @staticmethod
    def _wait_or_kill(pid: int) -> None:
        try:
            import win32api
            import win32con
            import win32event
            handle = win32api.OpenProcess(win32con.SYNCHRONIZE | win32con.PROCESS_TERMINATE, False, pid)
        except Exception:
            return  # already gone
        try:
            if win32event.WaitForSingleObject(handle, 8000) == win32event.WAIT_TIMEOUT:
                try:
                    win32api.TerminateProcess(handle, 1)
                except Exception:
                    pass  # not allowed / already exiting: never let cleanup crash the app
        finally:
            win32api.CloseHandle(handle)

    # ---- reading -----------------------------------------------------------------------------
    def sheet_names(self) -> list[str]:
        return [self.wb.Worksheets(i).Name for i in range(1, self.wb.Worksheets.Count + 1)]

    def read_sheet(self, sheet: str, selected: list[int], extend_print_area: bool,
                   read_extra: list[int] | tuple = ()) -> SheetData:
        """Read the printed columns (`selected`) and, if given, extra columns that are only used for
        filtering (`read_extra`, e.g. BX/BY when they are not printed). Extra columns are read from the
        worksheet even outside the print area and are never shown in the PDF."""
        read_cols = list(dict.fromkeys(list(selected) + [c for c in read_extra if c not in selected]))
        names = self.sheet_names()
        if sheet not in names:
            raise ExcelEngineError(f"Worksheet '{sheet}' was not found. Available: {', '.join(names)}.")
        ws = self.wb.Worksheets(sheet)
        self.ws = ws
        self._selected = list(selected)
        notes: list[str] = []
        if ws.ProtectContents:
            try:
                ws.Unprotect()
                notes.append("The sheet was protected; the temporary copy was unprotected for printing (no password needed).")
            except Exception as exc:
                raise ExcelEngineError("The worksheet is password-protected, so its layout cannot be changed. "
                                       "Unprotect it in Excel and try again.") from exc
        if getattr(self, "printer_note", ""):
            notes.append(self.printer_note)
        t0 = time.time()
        self.xl.CalculateFull()
        notes.append(f"Excel recalculated all formulas ({time.time() - t0:.1f} s) — printed values are current results, not stale cached values.")
        # Freeze the results: hiding rows must not change any value (e.g. SUBTOTAL(109, …) ignores
        # hidden rows and would otherwise print different totals). Also avoids slow recalculation.
        try:
            self.xl.Calculation = -4135  # xlCalculationManual
        except Exception:
            pass
        try:
            links = self.wb.LinkSources(1)
            if links:
                notes.append(f"The workbook links to {len(links)} external file(s); those links were not updated, "
                             "so linked values are as last saved.")
        except Exception:
            pass

        area_text = ws.PageSetup.PrintArea or ""
        from_wb = bool(area_text)
        if not area_text:
            area_text = ws.UsedRange.Address
            notes.append(f"The sheet has no print area; the used range {area_text} was used.")
        c1, r1, c2, r2 = parse_area(area_text)
        if extend_print_area and (min(selected) < c1 or max(selected) > c2):
            notes.append(f"Print area widened from {index_to_letter(c1)}–{index_to_letter(c2)} to include the selected columns.")
            c1, c2 = min(c1, min(selected)), max(c2, max(selected))
        outside = [c for c in selected if c < c1 or c > c2]
        if outside:
            raise ExcelEngineError(
                f"Column(s) {', '.join(index_to_letter(c) for c in outside)} are outside the print area "
                f"{index_to_letter(c1)}{r1}:{index_to_letter(c2)}{r2}. Remove them or tick “Extend the print area”.")

        columns = {}
        for c in read_cols:
            col = ws.Columns(c)
            columns[c] = ColumnInfo(c, index_to_letter(c), float(col.ColumnWidth), float(col.Width), bool(col.Hidden))

        # Which rows are visible? Use one selected column, made visible on the temporary copy.
        probe = selected[0]
        ws.Columns(probe).Hidden = False
        visible: set[int] = set()
        try:
            vis = ws.Range(ws.Cells(r1, probe), ws.Cells(r2, probe)).SpecialCells(XL_VISIBLE)
            for a in range(1, vis.Areas.Count + 1):
                ar = vis.Areas(a)
                visible.update(range(ar.Row, ar.Row + ar.Rows.Count))
        except Exception:
            visible = set()  # no visible cells
        if columns[probe].hidden:
            ws.Columns(probe).Hidden = True

        values = {c: _rows2d(ws.Range(ws.Cells(r1, c), ws.Cells(r2, c)).Value2) for c in read_cols}
        formulas = {c: _rows2d(ws.Range(ws.Cells(r1, c), ws.Cells(r2, c)).Formula) for c in read_cols}
        notes_by_cell: dict[tuple[int, int], str] = {}
        try:
            for i in range(1, ws.Comments.Count + 1):
                cm = ws.Comments(i)
                notes_by_cell[(cm.Parent.Row, cm.Parent.Column)] = str(cm.Text() or "")
        except Exception:
            pass

        rows: list[RowInfo] = []
        for r in range(r1, r2 + 1):
            if r not in visible:
                rows.append(RowInfo(r, hidden=True))
                continue
            row_obj = ws.Rows(r)
            info = RowInfo(r, hidden=False, outline_level=int(row_obj.OutlineLevel), height_pt=float(row_obj.RowHeight))
            for c in read_cols:
                v = values[c][r - r1]
                f = formulas[c][r - r1]
                f = f if isinstance(f, str) and f.startswith("=") else ""
                cell = ws.Cells(r, c)
                if v is None and not f and not cell.MergeCells:
                    info.cells[c] = CellInfo(note=notes_by_cell.get((r, c), ""))
                    continue
                interior = cell.Interior
                fill = None
                if interior.Pattern != XL_NONE and int(interior.Color) != WHITE:
                    fill = int(interior.Color)
                info.cells[c] = CellInfo(
                    value=v, text=str(cell.Text), formula=f, font_size=float(cell.Font.Size or 11),
                    bold=bool(cell.Font.Bold), fill=fill, wrap=bool(cell.WrapText), merged=bool(cell.MergeCells),
                    merge_area=str(cell.MergeArea.Address) if cell.MergeCells else "",
                    note=notes_by_cell.get((r, c), ""))
            rows.append(info)

        header_rows = self._header_rows(ws, r1, r2, visible, read_cols, values)
        sheet_data = SheetData(ws.Name, (c1, r1, c2, r2), from_wb, header_rows, rows, columns, list(selected), notes)
        sheet_data.meta_candidates = self._meta_candidates(ws, header_rows, c1, c2, selected)
        return sheet_data

    def _meta_candidates(self, ws, header_rows: list[int], c1: int, c2: int, selected: list[int]) -> list[MetaCell]:
        """Text in header rows of columns that will not be printed (possible document metadata)."""
        out: list[MetaCell] = []
        sel = set(selected)
        for r in header_rows:
            raw = ws.Range(ws.Cells(r, c1), ws.Cells(r, c2)).Value2          # one row: ((v1, v2, …),)
            row_vals = raw[0] if isinstance(raw, tuple) and raw and isinstance(raw[0], tuple) else (raw,)
            for i, v in enumerate(row_vals):
                c = c1 + i
                if c in sel or v is None or (isinstance(v, str) and not v.strip()):
                    continue
                cell = ws.Cells(r, c)
                span = None
                if cell.MergeCells:
                    area = cell.MergeArea
                    span = (int(area.Column), int(area.Column + area.Columns.Count - 1))
                out.append(MetaCell(r, c, str(cell.Text), hidden_col=bool(ws.Columns(c).Hidden), merged=bool(cell.MergeCells),
                                    merge_cols=span, font_size=float(cell.Font.Size or 11), bold=bool(cell.Font.Bold),
                                    italic=bool(cell.Font.Italic)))
        return out

    def _header_rows(self, ws, r1, r2, visible, selected, values) -> list[int]:
        """Frozen rows inside the print area (read from the file), without frozen *data* rows at their
        end (rows with two or more numbers, e.g. a grand total pinned under the headings); otherwise the
        rows before the first numbers."""
        first_body = None
        frozen = frozen_rows(self.copy_path, ws.Name)
        if frozen:
            top, count = frozen
            first_body = top + count
            while first_body - 1 > r1 and sum(
                    1 for c in selected
                    if isinstance(values[c][first_body - 1 - r1], (int, float)) and not isinstance(values[c][first_body - 1 - r1], bool)) >= 2:
                first_body -= 1
        if first_body is None or not (r1 < first_body <= min(r2, r1 + 15)):
            first_body = None
            for r in range(r1, min(r2, r1 + 10) + 1):
                if r in visible and any(isinstance(values[c][r - r1], (int, float)) and not isinstance(values[c][r - r1], bool)
                                        for c in selected):
                    first_body = r
                    break
        if first_body is None or first_body <= r1:
            return []
        return [r for r in range(r1, first_body) if r in visible]

    # ---- layout --------------------------------------------------------------------------------
    def prepare(self, sheet: SheetData, kept_rows: list[int]) -> None:
        """Show only selected columns and kept rows inside the print area (on the temporary copy)."""
        ws = self.ws
        c1, r1, c2, r2 = sheet.print_area
        try:
            self.xl.ScreenUpdating = False
        except Exception:
            pass
        ws.Range(ws.Columns(c1), ws.Columns(c2)).Hidden = True
        for a, b in _col_blocks(sheet.selected):
            ws.Range(ws.Columns(a), ws.Columns(b)).Hidden = False
        kept = set(kept_rows)
        to_hide = [r.number for r in sheet.rows if not r.hidden and r.number not in kept]
        for a, b in _blocks(to_hide):
            ws.Range(f"{a}:{b}").EntireRow.Hidden = True

    def measure(self, sheet: SheetData, name: str, orientation: str, kept_body: list[int],
                keep_next: list[bool], text_widths: dict[int, float], numeric_cols: list[int],
                header_rows: list[int]) -> Geometry:
        """Apply column widths/wrapping, autofit row heights, and read the geometry at 100 %."""
        ws = self.ws
        body_blocks = _blocks(kept_body)
        # Numeric / short columns: width from the displayed text of printed rows (Excel's '###'
        # check afterwards widens any column that is still too narrow), plus room for header words.
        rows_by_number = {r.number: r for r in sheet.rows}
        for c in numeric_cols:
            w = 0.0
            for r in kept_body:
                cell = rows_by_number[r].cell(c)
                t = " ".join(cell.text.split())
                if t:
                    w = max(w, len(t) * cell.font_size / 11 * (1.12 if cell.bold else 1.0) + 2.0)
            w = max(w, self._header_word_chars(sheet, c, header_rows), 4.0)
            ws.Columns(c).ColumnWidth = min(w, 80)
        # Long-text columns: chosen width + wrap text on printed cells
        for c, w in text_widths.items():
            ws.Columns(c).ColumnWidth = w
            for a, b in body_blocks:
                ws.Range(ws.Cells(a, c), ws.Cells(b, c)).WrapText = True
        # Row heights: AutoFit printed body rows (never hidden ones), then a small safety margin
        heights = []
        for a, b in body_blocks:
            ws.Range(f"{a}:{b}").EntireRow.AutoFit()
        wrap_cols = list(text_widths)
        for r in kept_body:
            h = float(ws.Rows(r).RowHeight)
            if wrap_cols and any(rows_by_number[r].cell(c).text.strip() for c in wrap_cols):
                h2 = min(409.0, math.ceil(h * 1.06 + 1.5))
                if h2 != h:
                    ws.Rows(r).RowHeight = h2
                    h = h2
            heights.append(h)
        self._fit_meta_text(sheet)
        self._fit_header_heights(sheet, header_rows)
        header_heights = [float(ws.Rows(r).RowHeight) for r in header_rows]
        col_widths = {c: float(ws.Columns(c).Width) for c in sheet.selected}
        return Geometry(name, orientation, col_widths, header_heights, kept_body, heights, keep_next,
                        dict(text_widths))

    @staticmethod
    def _header_word_chars(sheet: SheetData, col: int, header_rows: list[int]) -> float:
        """Width (characters) needed so the longest header word of a single-column header fits."""
        best = 0.0
        rows = {r.number: r for r in sheet.rows}
        for hr in header_rows:
            cell = rows[hr].cell(col)
            if not cell.text.strip():
                continue
            if cell.merged:
                first, last = cell.merge_area.replace("$", "").split(":")
                if re.sub(r"\d", "", first) != re.sub(r"\d", "", last):
                    continue  # spans several columns: its words can use their combined width
            longest = max((len(w) for w in cell.text.split()), default=0)
            best = max(best, longest * cell.font_size / 11 * (1.18 if cell.bold else 1.08) + 2.0)
        return best

    def _fit_header_heights(self, sheet: SheetData, header_rows: list[int]) -> None:
        """Header rows exactly as tall as their (wrapped) text needs — no larger gaps between the title,
        the subtitle and the column headings (merged cells cannot AutoFit, so this is estimated from the
        live cells of the copy: merged areas, wrap settings and carried-over labels included)."""
        ws = self.ws
        rows = {r.number: r for r in sheet.rows}
        live = {}
        seen: set[str] = set()
        for hr in header_rows:
            for c in sheet.selected:
                cell = ws.Cells(hr, c)
                if cell.MergeCells:                      # merged area: its anchor holds the text (may be unprinted)
                    if cell.MergeArea.Row != hr:
                        continue
                    address = str(cell.MergeArea.Address)
                    if address in seen:
                        continue
                    seen.add(address)
                    cell = cell.MergeArea.Cells(1, 1)
                text = str(cell.Text or "")
                if not text.strip():
                    continue
                live[(hr, c)] = (text, float(cell.Font.Size or 11), bool(cell.Font.Bold), bool(cell.WrapText),
                                 str(cell.MergeArea.Address) if cell.MergeCells else f"${index_to_letter(c)}${hr}")
        # 1. Start each header row at the height of one line of its largest text (or a thin spacer).
        for hr in header_rows:
            fonts = [v[1] for (r, _), v in live.items() if r == hr]
            ws.Rows(hr).RowHeight = round(max(fonts) * 1.3 + 3, 1) if fonts else 3.0
        # 2. Wrapped text (and merged areas over several rows) gets the height it needs.
        for (hr, c), (text, size, bold, wrap, area) in live.items():
            rng = ws.Range(area)
            width_pt = sum(float(rng.Columns(i).Width) for i in range(1, rng.Columns.Count + 1) if not rng.Columns(i).Hidden)
            if width_pt <= 0:
                continue
            if wrap:   # Excel's own measurement: the same text, font and width in a scratch cell, AutoFit
                needed = self._wrapped_height(ws.Range(area).Cells(1, 1), text, width_pt) * 1.08 + 2
            else:
                needed = (1 + text.count("\n")) * size * 1.3 + 4
            row_nums = [r for r in range(rng.Row, rng.Row + rng.Rows.Count) if r in rows and not rows[r].hidden]
            have = sum(float(ws.Rows(r).RowHeight) for r in row_nums)
            if row_nums and needed > have:
                extra = (needed - have) / len(row_nums)
                for r in row_nums:
                    ws.Rows(r).RowHeight = min(409.0, float(ws.Rows(r).RowHeight) + extra)

    def _wrapped_height(self, src, text: str, width_pt: float) -> float:
        """Row height Excel needs for `text` wrapped in `width_pt` with the font of `src` (merged cells
        cannot AutoFit, so the text is measured in a scratch cell at the far right of the sheet)."""
        ws = self.ws
        col = ws.Columns.Count            # XFD: outside any print area
        scratch = ws.Cells(1, col)
        old_w = float(ws.Columns(col).ColumnWidth)
        old_h = float(ws.Rows(1).RowHeight)
        try:
            ws.Columns(col).ColumnWidth = 10
            per_char = float(ws.Columns(col).Width) / 10
            ws.Columns(col).ColumnWidth = min(255, max(1.0, (width_pt - 4) / per_char))
            for attr in ("Name", "Size", "Bold", "Italic"):
                setattr(scratch.Font, attr, getattr(src.Font, attr))
            scratch.WrapText = True
            scratch.Value = text
            ws.Rows(1).AutoFit()
            height = float(ws.Rows(1).RowHeight)
        finally:
            scratch.Clear()
            ws.Columns(col).ColumnWidth = old_w
            ws.Rows(1).RowHeight = old_h
        return height

    def apply_metadata(self, plan: MetaPlan) -> None:
        """Write carried-over document metadata into free printed header cells (temporary copy only)."""
        ws = self.ws
        self.meta_rows = list(plan.metadata_rows)
        for pl in plan.placements:
            src, tgt = ws.Cells(*pl.source), ws.Cells(*pl.target)
            tgt.NumberFormat = "@"
            tgt.Value = pl.text
            for attr in ("Name", "Size", "Bold", "Italic", "Color"):
                try:
                    setattr(tgt.Font, attr, getattr(src.Font, attr))
                except Exception:
                    pass
            tgt.WrapText = False
            tgt.HorizontalAlignment = {"right": XL_RIGHT, "left": XL_LEFT}.get(pl.align, src.HorizontalAlignment)
            try:
                tgt.VerticalAlignment = src.VerticalAlignment
            except Exception:
                pass

    def _fit_meta_text(self, sheet: SheetData) -> None:
        """Titles and labels of the metadata block must fit the printed table width: a merged title is
        clipped to the width of its *printed* columns, so wrap it there (and merge an unmerged long title
        across the free printed cells to its right first). The row height is set afterwards."""
        ws = self.ws
        printed = sorted(sheet.selected)
        seen: set[str] = set()
        for r in self.meta_rows:
            for c in printed:
                cell = ws.Cells(r, c)
                if cell.MergeCells:                      # use the merged area's anchor cell (may be unprinted)
                    if cell.MergeArea.Row != r:
                        continue
                    address = str(cell.MergeArea.Address)
                    if address in seen:
                        continue
                    seen.add(address)
                    cell = cell.MergeArea.Cells(1, 1)
                text = str(cell.Text or "")
                if not text.strip():
                    continue
                need = _text_width_pt(text, float(cell.Font.Size or 11), bool(cell.Font.Bold))
                if cell.MergeCells:
                    area = cell.MergeArea
                    have = sum(float(area.Columns(i).Width) for i in range(1, area.Columns.Count + 1) if not area.Columns(i).Hidden)
                else:
                    right = [x for x in printed if x > c]
                    free = []
                    for x in right:
                        if str(ws.Cells(r, x).Text or "").strip() or ws.Cells(r, x).MergeCells:
                            break
                        free.append(x)
                    have = float(ws.Columns(c).Width) + sum(float(ws.Columns(x).Width) for x in free)
                    if need > have - 6 and free:
                        ws.Range(ws.Cells(r, c), ws.Cells(r, free[-1])).Merge()
                if need > have - 6:
                    cell.MergeArea.WrapText = True

    def close_borders(self, sheet: SheetData, kept_body: list[int], header_rows: list[int]) -> int:
        """Borders that belonged to a now-hidden neighbour (row or column) or to the next row's top edge
        disappear at page breaks and around removed columns. Copy such shared edges onto the printed cells
        so every printed row/column keeps its own closed border (temporary copy only)."""
        ws = self.ws
        printed = sorted(sheet.selected)
        rows = list(header_rows) + list(kept_body)
        changed = 0

        def copy_edge(src_border, dst_border):
            nonlocal changed
            if src_border.LineStyle != XL_NONE and dst_border.LineStyle == XL_NONE:
                dst_border.LineStyle = src_border.LineStyle
                dst_border.Weight = src_border.Weight
                dst_border.Color = src_border.Color
                changed += 1

        # merged header areas that run past the last printed column into unprinted columns: their outer
        # border belongs to a hidden column and is not drawn -> end the area at the last printed column
        done: set[str] = set()
        for r in header_rows:
            for c in printed:
                cell = ws.Cells(r, c)
                if not cell.MergeCells:
                    continue
                area = cell.MergeArea
                address = str(area.Address)
                if address in done:
                    continue
                done.add(address)
                first_col, last_col = int(area.Column), int(area.Column + area.Columns.Count - 1)
                inside = [x for x in printed if first_col <= x <= last_col]
                if not inside or last_col in printed or inside[-1] == last_col:
                    continue
                top, nrows = int(area.Row), int(area.Rows.Count)
                edge = area.Cells(1, area.Columns.Count).Borders(EDGE_RIGHT)
                style, weight, color = edge.LineStyle, edge.Weight, edge.Color
                area.UnMerge()
                new = ws.Range(ws.Cells(top, first_col), ws.Cells(top + nrows - 1, inside[-1]))
                if new.Columns.Count > 1 or nrows > 1:
                    new.Merge()
                if style != XL_NONE:
                    b = new.Borders(EDGE_RIGHT)
                    b.LineStyle, b.Weight, b.Color = style, weight, color
                    changed += 1
        for i, r in enumerate(kept_body):                       # bottom edges (page breaks, removed rows)
            below = kept_body[i + 1] if i + 1 < len(kept_body) else r + 1
            for c in printed:
                copy_edge(ws.Cells(below, c).Borders(EDGE_TOP), ws.Cells(r, c).Borders(EDGE_BOTTOM))
        for j, c in enumerate(printed):                         # vertical edges next to removed columns
            right = printed[j + 1] if j + 1 < len(printed) else None
            for r in rows:
                if ws.Cells(r, c).MergeCells and ws.Cells(r, c).MergeArea.Columns.Count > 1:
                    continue
                if c + 1 not in printed:
                    copy_edge(ws.Cells(r, c + 1).Borders(EDGE_LEFT), ws.Cells(r, c).Borders(EDGE_RIGHT))
                    if right:
                        copy_edge(ws.Cells(r, right).Borders(EDGE_LEFT), ws.Cells(r, c).Borders(EDGE_RIGHT))
                if j == 0 and c > 1:
                    copy_edge(ws.Cells(r, c - 1).Borders(EDGE_RIGHT), ws.Cells(r, c).Borders(EDGE_LEFT))
        return changed

    def write_values(self, col: int, values: dict[int, object]) -> None:
        """Write new values (e.g. consecutive item numbers) into the temporary copy. Text that Excel
        could read as a number (e.g. "2.1") is written as text."""
        ws = self.ws
        for r, v in values.items():
            ws.Cells(r, col).Value = ("'" + v) if isinstance(v, str) else v

    def overflow_cells(self, rows: list[int], cols: list[int]) -> list[str]:
        """Cells that Excel would display as ### (number wider than its column)."""
        ws = self.ws
        bad = []
        for r in rows:
            for c in cols:
                t = str(ws.Cells(r, c).Text)
                if t and set(t.strip()) == {"#"}:
                    bad.append(f"{index_to_letter(c)}{r}")
        return bad

    def widen(self, col: int, factor: float = 1.15) -> None:
        self.ws.Columns(col).ColumnWidth = min(255, float(self.ws.Columns(col).ColumnWidth) * factor + 1)

    def grow_rows(self, rows: list[int], factor: float = 1.15) -> None:
        """Make rows taller (text was cut off): at least one more line of their largest font."""
        for r in rows:
            h = float(self.ws.Rows(r).RowHeight)
            try:
                font = max(float(self.ws.Cells(r, c).Font.Size or 11) for c in self._selected)
            except Exception:
                font = 11.0
            self.ws.Rows(r).RowHeight = min(409.0, max(h * factor, h + font * 1.25))

    def displayed_text(self, row: int, col: int) -> str:
        return str(self.ws.Cells(row, col).Text)

    def row_heights(self, rows: list[int]) -> list[float]:
        return [float(self.ws.Rows(r).RowHeight) for r in rows]

    def col_widths(self, cols: list[int]) -> dict[int, float]:
        return {c: float(self.ws.Columns(c).Width) for c in cols}

    # ---- page setup and export ---------------------------------------------------------------------
    def page_setup(self, sheet: SheetData, paper: str, orientation: str, margins_in: tuple[float, float, float, float],
                   zoom: int, header_rows: list[int], page_starts: list[int], repeat_header: bool) -> None:
        ws = self.ws
        ps = ws.PageSetup
        c1, r1, c2, r2 = sheet.print_area
        # Note: Application.PrintCommunication=False (batching) is deliberately NOT used — with it, Excel
        # reported the new Zoom but exported the PDF at the old scale.
        try:
            ps.PrintArea = area_address(c1, r1, c2, r2)
            ps.Orientation = XL_ORIENT[orientation]
            try:
                ps.PaperSize = XL_PAPER[paper]
            except Exception as exc:
                raise ExcelEngineError(f"Excel could not set the paper size to {paper} (the default printer may not "
                                       f"support it): {exc}") from exc
            ps.FitToPagesWide = False   # must be set before Zoom: changing it afterwards resets the scale
            ps.FitToPagesTall = False
            ps.Zoom = int(zoom)
            lr, top, bottom, foot = margins_in
            ps.LeftMargin = ps.RightMargin = self.xl.InchesToPoints(lr)
            ps.TopMargin = self.xl.InchesToPoints(top)
            ps.BottomMargin = self.xl.InchesToPoints(bottom)
            ps.HeaderMargin = self.xl.InchesToPoints(min(foot, top))
            ps.FooterMargin = self.xl.InchesToPoints(foot)
            ps.CenterHorizontally = True
            ps.CenterVertically = False
            try:
                ps.ScaleWithDocHeaderFooter = False
            except Exception:
                pass
            ps.CenterFooter = FOOTER
            ps.PrintTitleRows = (f"${header_rows[0]}:${header_rows[-1]}" if repeat_header and header_rows else "")
            ps.PrintTitleColumns = ""
        except ExcelEngineError:
            raise
        except Exception as exc:
            raise ExcelEngineError(f"Excel could not apply the page setup: {exc}") from exc
        ws.ResetAllPageBreaks()   # NB: this silently resets the print scale to 100 %, so Zoom is set afterwards
        for r in page_starts:
            ws.HPageBreaks.Add(Before=ws.Rows(r))
        ps.FitToPagesWide = False
        ps.FitToPagesTall = False
        ps.Zoom = int(zoom)
        if int(ps.Zoom or 0) != int(zoom):
            raise ExcelEngineError(f"Excel did not accept the print scale {zoom} % (it reports {ps.Zoom}).")

    def export_pdf(self, out_path: Path) -> bytes:
        try:
            self.ws.ExportAsFixedFormat(Type=0, Filename=str(out_path), Quality=0, IncludeDocProperties=False,
                                        IgnorePrintAreas=False, OpenAfterPublish=False)
        except Exception as exc:
            raise ExcelEngineError(f"Excel could not export the PDF: {exc}") from exc
        if not out_path.exists() or out_path.stat().st_size == 0:
            raise ExcelEngineError("Excel reported success but no PDF file was written.")
        return out_path.read_bytes()

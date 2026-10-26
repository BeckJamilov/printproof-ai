"""Fast, read-only workbook structure from the .xlsx package (no Excel needed).

Used by the interface to list worksheets and show the print area right after upload, and to build
the structural metadata for the optional AI helper. Reads only XML structure, never cell values.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

from .columns import index_to_letter, parse_area

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"


class WorkbookReadError(ValueError):
    pass


@dataclass
class SheetInfo:
    name: str
    state: str = "visible"
    print_area: str = ""          # e.g. "D3:BZ1690"
    dimension: str = ""           # used range from the sheet XML, e.g. "A1:KZ1747"
    hidden_columns: list[str] = field(default_factory=list)


def read_workbook_info(path: Path) -> list[SheetInfo]:
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise WorkbookReadError("This is not a valid .xlsx/.xlsm file (Excel 2007 or newer).") from exc
    with zf:
        try:
            wb = ET.fromstring(zf.read("xl/workbook.xml"))
            rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        except KeyError as exc:
            raise WorkbookReadError("The file does not look like an Excel workbook.") from exc
        targets = {r.get("Id"): r.get("Target") for r in rels.iter(f"{REL_NS}Relationship")}
        sheets: list[SheetInfo] = []
        for i, s in enumerate(wb.findall("m:sheets/m:sheet", NS)):
            rid = s.get(f"{{{NS['r']}}}id")
            info = SheetInfo(s.get("name"), s.get("state", "visible"))
            target = targets.get(rid, "")
            target = target.lstrip("/")
            target = target if target.startswith("xl/") else "xl/" + target
            info.dimension, info.hidden_columns = _sheet_structure(zf, target)
            sheets.append(info)
        for dn in wb.findall("m:definedNames/m:definedName", NS):
            if dn.get("name") == "_xlnm.Print_Area" and dn.get("localSheetId") is not None:
                idx = int(dn.get("localSheetId"))
                if 0 <= idx < len(sheets) and dn.text:
                    try:
                        c1, r1, c2, r2 = parse_area(dn.text)
                        sheets[idx].print_area = f"{index_to_letter(c1)}{r1}:{index_to_letter(c2)}{r2}"
                    except Exception:
                        sheets[idx].print_area = dn.text
        return sheets


def _sheet_structure(zf: zipfile.ZipFile, member: str) -> tuple[str, list[str]]:
    """Read only the start of the sheet XML (dimension and <cols>); stop before the cell data."""
    dimension, hidden = "", []
    try:
        with zf.open(member) as fh:
            for _, elem in ET.iterparse(fh, events=("end",)):
                tag = elem.tag.split("}")[-1]
                if tag == "dimension":
                    dimension = elem.get("ref", "")
                elif tag == "col" and elem.get("hidden") in ("1", "true"):
                    lo, hi = int(elem.get("min")), int(elem.get("max"))
                    hidden.extend(index_to_letter(c) for c in range(lo, min(hi, lo + 500) + 1))
                elif tag == "sheetData":
                    break
                elif tag in ("row", "c"):
                    break
    except KeyError:
        pass
    return dimension, hidden


def ai_metadata(sheet: SheetInfo, sheet_count: int) -> dict:
    meta = {"sheet_count": sheet_count, "print_area": sheet.print_area or "(none — used range)",
            "hidden_columns": ", ".join(sheet.hidden_columns[:60])}
    area = sheet.print_area or sheet.dimension
    if area and re.fullmatch(r"[A-Z]+\d+:[A-Z]+\d+", area):
        c1, r1, c2, r2 = parse_area(area)
        meta["columns_in_print_area"] = f"{index_to_letter(c1)}–{index_to_letter(c2)}"
        meta["rows_in_print_area"] = r2 - r1 + 1
    return meta


def frozen_rows(path: Path, sheet_name: str) -> tuple[int, int] | None:
    """(first frozen row, number of frozen rows) from the sheet's own XML, or None if no rows are frozen.

    Read from the file rather than from Excel's window: a hidden Excel instance with screen updating
    off can report scroll positions that are off by one."""
    try:
        with zipfile.ZipFile(path) as zf:
            wb = ET.fromstring(zf.read("xl/workbook.xml"))
            rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
            targets = {r.get("Id"): r.get("Target") for r in rels.iter(f"{REL_NS}Relationship")}
            member = None
            for s in wb.findall("m:sheets/m:sheet", NS):
                if s.get("name") == sheet_name:
                    t = targets.get(s.get(f"{{{NS['r']}}}id"), "").lstrip("/")
                    member = t if t.startswith("xl/") else "xl/" + t
            if not member:
                return None
            top_row, split = 1, 0
            with zf.open(member) as fh:
                for _, elem in ET.iterparse(fh, events=("start",)):
                    tag = elem.tag.split("}")[-1]
                    if tag == "sheetView":
                        m = re.match(r"[A-Z]+(\d+)", elem.get("topLeftCell", "A1") or "A1")
                        top_row = int(m.group(1)) if m else 1
                    elif tag == "pane" and elem.get("state") in ("frozen", "frozenSplit"):
                        split = int(float(elem.get("ySplit", "0") or 0))
                    elif tag in ("sheetFormatPr", "cols", "sheetData"):
                        break
            return (top_row, split) if split > 0 else None
    except (zipfile.BadZipFile, KeyError, ET.ParseError, ValueError):
        return None

"""Excel column letters: parsing user input such as "D, E, J, BW-BZ" and validation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_COLUMN = 16384  # XFD, the last column in Excel
MAX_SELECTED = 60   # more than this cannot be printed readably on one page width


class ColumnInputError(ValueError):
    """The user's column list cannot be understood."""


def letter_to_index(letters: str) -> int:
    """'A' -> 1, 'Z' -> 26, 'AA' -> 27, 'XFD' -> 16384."""
    letters = letters.strip().upper()
    if not re.fullmatch(r"[A-Z]{1,3}", letters):
        raise ColumnInputError(f"“{letters}” is not an Excel column letter.")
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    if n > MAX_COLUMN:
        raise ColumnInputError(f"Column {letters} is beyond Excel's last column (XFD).")
    return n


def index_to_letter(index: int) -> str:
    if not 1 <= index <= MAX_COLUMN:
        raise ValueError(f"column index out of range: {index}")
    out = ""
    while index:
        index, rem = divmod(index - 1, 26)
        out = chr(65 + rem) + out
    return out


@dataclass
class ColumnSelection:
    indexes: list[int]                                   # unique, in worksheet order (how Excel prints them)
    notes: list[str] = field(default_factory=list)
    entered: list[int] = field(default_factory=list)     # unique, in the order the user typed them

    @property
    def letters(self) -> list[str]:
        return [index_to_letter(i) for i in self.indexes]

    @property
    def entered_letters(self) -> list[str]:
        return [index_to_letter(i) for i in (self.entered or self.indexes)]


def parse_columns(text: str) -> ColumnSelection:
    """Parse 'D, E, J, BW-BZ' / 'D;E;BW:BZ' / 'd e j' into unique column indexes.

    Spaces and lower case are normalised; anything that is not a column letter or a range is an
    error (never guessed). A valid column is never changed: duplicates are used once and reported."""
    if not text or not text.strip():
        raise ColumnInputError("Enter at least one column letter, for example: D, E, J, BW-BZ.")
    notes: list[str] = []
    entered: list[int] = []
    duplicates: list[str] = []

    def add(i: int) -> None:
        if i in entered:
            duplicates.append(index_to_letter(i))
        else:
            entered.append(i)

    tokens = [t for t in re.split(r"[,;\s]+", text.strip()) if t]
    for token in tokens:
        token = token.replace("–", "-").replace("—", "-").replace(":", "-")
        if "-" in token:
            parts = [p for p in token.split("-")]
            if len(parts) != 2 or not parts[0] or not parts[1]:
                raise ColumnInputError(f"“{token}” is not a valid range. Use a form like BW-BZ.")
            a, b = letter_to_index(parts[0]), letter_to_index(parts[1])
            if a > b:
                notes.append(f"Range {parts[0].upper()}-{parts[1].upper()} was reversed; used "
                             f"{index_to_letter(b)}-{index_to_letter(a)}.")
                a, b = b, a
            for i in range(a, b + 1):
                add(i)
        else:
            add(letter_to_index(token))
    if duplicates:
        notes.append(f"Listed more than once (used once): {', '.join(dict.fromkeys(duplicates))}.")
    if len(entered) > MAX_SELECTED:
        raise ColumnInputError(f"{len(entered)} columns selected; at most {MAX_SELECTED} can be printed.")
    return ColumnSelection(sorted(entered), notes, entered)


def _suggestions(letters: str, last_col: int, area: tuple[int, int] | None) -> list[str]:
    """Columns inside the sheet that differ by one extra typed letter (e.g. BDW -> BW, DBX -> BX);
    columns inside the print area first, at most two."""
    out = []
    for i in range(len(letters)):
        cand = letters[:i] + letters[i + 1:]
        if cand and letter_to_index(cand) <= last_col and cand not in out:
            out.append(cand)
    if area:
        out.sort(key=lambda c: not area[0] <= letter_to_index(c) <= area[1])
    return out[:2]


def check_against_sheet(selection: ColumnSelection, last_used_col: int | None,
                        print_area_cols: tuple[int, int] | None) -> tuple[list[str], list[str]]:
    """(errors, outside_print_area) for a selection on a real worksheet.

    errors: columns to the right of the sheet's used range — they cannot contain data, so they are
    almost certainly typing mistakes (with a suggestion). outside_print_area: letters of columns that
    exist but lie outside the existing print area."""
    errors, outside = [], []
    if last_used_col:
        beyond = [index_to_letter(i) for i in selection.entered or selection.indexes if i > last_used_col]
        for col in beyond:
            hint = _suggestions(col, last_used_col, print_area_cols)
            errors.append(f"Column {col} is outside this worksheet's used range (A–{index_to_letter(last_used_col)}), "
                          "so it has no data." + (f" Did you mean {' or '.join(hint)}?" if hint else ""))
    if print_area_cols:
        lo, hi = print_area_cols
        outside = [index_to_letter(i) for i in selection.indexes if not lo <= i <= hi
                   and not (last_used_col and i > last_used_col)]
    return errors, outside


def format_columns(indexes: list[int]) -> str:
    """[4, 5, 10, 75, 76, 77, 78] -> 'D, E, J, BW–BZ'."""
    if not indexes:
        return ""
    idx = sorted(set(indexes))
    parts, start, prev = [], idx[0], idx[0]
    for i in idx[1:] + [None]:
        if i is not None and i == prev + 1:
            prev = i
            continue
        if prev - start >= 2:
            parts.append(f"{index_to_letter(start)}–{index_to_letter(prev)}")
        else:
            parts.extend(index_to_letter(k) for k in range(start, prev + 1))
        if i is not None:
            start = prev = i
    return ", ".join(parts)


def parse_area(area: str) -> tuple[int, int, int, int]:
    """'$D$3:$BZ$1690' (optionally with a sheet prefix) -> (first_col, first_row, last_col, last_row)."""
    area = area.split("!")[-1].replace("$", "").strip()
    area = area.split(",")[0]  # multi-area print areas: use the first area
    m = re.fullmatch(r"([A-Za-z]{1,3})(\d+):([A-Za-z]{1,3})(\d+)", area)
    if not m:
        raise ColumnInputError(f"Unsupported range “{area}”.")
    c1, r1, c2, r2 = letter_to_index(m[1]), int(m[2]), letter_to_index(m[3]), int(m[4])
    return min(c1, c2), min(r1, r2), max(c1, c2), max(r1, r2)


def area_address(c1: int, r1: int, c2: int, r2: int) -> str:
    return f"${index_to_letter(c1)}${r1}:${index_to_letter(c2)}${r2}"

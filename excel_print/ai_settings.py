"""Optional AI help: turn written printing instructions into Excel Print Optimizer settings.

Uses the same PydanticAI + gpt-6-luna via Portkey setup as the PDF agent (agent.py). Privacy:
only the instruction text and structural metadata (print area address, column letters, row counts,
hidden column letters) are sent — never cell values, labels, comments or the workbook itself.
The answer is validated in Python; the user reviews it in the form before anything is printed.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent, capture_run_messages
from pydantic_ai.usage import RunUsage, UsageLimits

from .columns import ColumnInputError, parse_columns

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "excel_layout_prompt.md"
LIMITS = UsageLimits(request_limit=2, total_tokens_limit=8_000)
MAX_INSTRUCTION_CHARS = 1_000


class ExcelPrintRequest(BaseModel):
    columns: str | None = Field(None, description="Columns to print, e.g. 'D, E, J, BW-BZ'.")
    filter_columns: str | None = Field(None, description="Columns that decide row relevance, e.g. 'BX, BY'.")
    zero_is_empty: bool | None = None
    keep_rows_with_other_values: bool | None = None
    mode: Literal["readability", "pages"] | None = None
    min_font_pt: float | None = Field(None, ge=4, le=20)
    max_pages: int | None = Field(None, ge=1, le=50)
    paper: Literal["A3", "A4"] | None = None
    orientation: Literal["landscape", "portrait", "auto"] | None = None
    assumptions: list[str] = Field(default_factory=list)
    unclear: list[str] = Field(default_factory=list)


def structural_metadata(info: dict[str, Any]) -> str:
    """Only non-sensitive structure: no cell values, no labels."""
    allowed = ("print_area", "columns_in_print_area", "hidden_columns", "rows_in_print_area", "sheet_count")
    return "\n".join(f"- {k}: {info[k]}" for k in allowed if k in info and info[k] not in (None, ""))


def interpret_instructions(text: str, info: dict[str, Any], model=None) -> tuple[ExcelPrintRequest | None, dict]:
    """Return (validated request or None, run record with usage). Never raises for model errors."""
    text = (text or "").strip()
    record: dict[str, Any] = {"run_id": uuid.uuid4().hex[:12], "error": None}
    if not text:
        record["error"] = "Please type your printing instructions first."
        return None, record
    if len(text) > MAX_INSTRUCTION_CHARS:
        record["error"] = f"Instructions are too long (max {MAX_INSTRUCTION_CHARS} characters)."
        return None, record

    http_log: list[dict] = []
    if model is None:
        from agent import build_model  # Portkey + gpt-6-luna, key from .env
        model = build_model(http_log)
    from agent import model_settings
    agent = Agent(model, output_type=ExcelPrintRequest, instructions=PROMPT_PATH.read_text(encoding="utf-8"),
                  retries=1, model_settings=model_settings(True), name="printproof-excel-settings")
    usage = RunUsage()
    started = time.perf_counter()
    prompt = ("Workbook structure (no contents):\n" + structural_metadata(info) +
              "\n\nUser's printing instructions:\n<instructions>\n" + text + "\n</instructions>")
    request = None
    try:
        with capture_run_messages():
            result = agent.run_sync(prompt, usage=usage, usage_limits=LIMITS)
        request = _validate(result.output)
    except Exception as exc:  # API errors, limits, invalid output
        record["error"] = f"The AI could not interpret the instructions: {type(exc).__name__}: {exc}"
    record.update({
        "seconds": round(time.perf_counter() - started, 2),
        "usage": {"requests": usage.requests, "input_tokens": usage.input_tokens,
                  "output_tokens": usage.output_tokens, "total_tokens": usage.total_tokens},
        "portkey_cache": [h.get("portkey_cache_status") for h in http_log if h.get("http_status") == 200],
        "metadata_sent": structural_metadata(info),
    })
    _audit(text, record, request)
    return request, record


def _validate(req: ExcelPrintRequest) -> ExcelPrintRequest:
    """Drop column lists that are not valid Excel letters; keep the problem visible."""
    for field in ("columns", "filter_columns"):
        value = getattr(req, field)
        if value:
            try:
                parse_columns(value)
            except ColumnInputError as exc:
                req.unclear.append(f"Ignored {field.replace('_', ' ')} “{value}”: {exc}")
                setattr(req, field, None)
    if req.columns and req.filter_columns:
        sel = set(parse_columns(req.columns).indexes)
        if not set(parse_columns(req.filter_columns).indexes) <= sel:
            req.assumptions.append("Some filter columns are not printed; they are still used to decide which rows to keep.")
    return req


def _audit(text: str, record: dict, request: ExcelPrintRequest | None) -> None:
    try:
        from agent import MODEL_NAME, append_audit_events
        append_audit_events([{
            "event": "excel_ai_settings", "run_id": record["run_id"], "model": MODEL_NAME,
            "instructions": text, "metadata_sent": record.get("metadata_sent"),
            "usage": record.get("usage"), "portkey_cache": record.get("portkey_cache"),
            "seconds": record.get("seconds"), "error": record.get("error"),
            "result": request.model_dump() if request else None,
        }])
    except Exception:
        pass  # logging must never break the app

"""PrintProof AI agent (Step 2), built with PydanticAI.

- Model: gpt-6-luna through Portkey, key from PORTKEY_API_KEY in .env (project folder or one above).
- Input: the user's requirements in plain English. The PDF stays in Python; the agent only sees
  measurements returned by the tools in tools.py, which call our Step 1 checker.
- Output: a structured PrintProofReport (models.py). An output validator rejects any report whose
  findings don't match the real tool results, so the AI cannot invent or change a status.
- Limits: few model requests, tool calls and tokens per run, to protect Portkey credits.
- Audit: every run appends API calls, tool calls and real token usage to output/audit_trail.json.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")  # hide PydanticAI's console banner

import httpx2
from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic_ai import Agent, ModelRetry, RunContext, UsageLimitExceeded, capture_run_messages
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import RunUsage, UsageLimits

import tools
from models import AgentDeps, PrintProofReport
from pdf_checker import FAIL, NEEDS_REVIEW, PASS, PDFCheckError, open_pdf

PROJECT_DIR = Path(__file__).resolve().parent
PROMPT_PATH = PROJECT_DIR / "prompts" / "prompt.md"
AUDIT_PATH = PROJECT_DIR / "output" / "audit_trail.json"

PORTKEY_BASE_URL = "https://api.portkey.ai/v1"
MODEL_NAME = "gpt-6-luna"  # required model for the final project

# ---- Limits for one AI analysis (protect Portkey credits) ----
USAGE_LIMITS = UsageLimits(
    request_limit=6,  # model calls per analysis
    tool_calls_limit=8,  # tool calls per analysis (4 checks + overview + retries)
    total_tokens_limit=30_000,  # input + output tokens per analysis
)
MAX_OUTPUT_TOKENS = 1_500  # per model response
AGENT_RETRIES = 2  # retries after a bad tool argument or a report that doesn't match the tools
MAX_REQUIREMENTS_CHARS = 1_000  # longest requirements text we accept
API_TIMEOUT_SECONDS = 60

logger = logging.getLogger("printproof.agent")


# ---------------------------------------------------------------------------
# Environment and model
# ---------------------------------------------------------------------------

def load_project_env() -> list[Path]:
    """Load .env from this project folder first, then from one folder above.

    Values already loaded are not overwritten, so the project's own .env wins.
    Returns the .env files that were found (never their contents).
    """
    found = []
    for folder in (PROJECT_DIR, PROJECT_DIR.parent):
        env_file = folder / ".env"
        if env_file.is_file():
            load_dotenv(env_file, override=False)
            found.append(env_file)
    return found


def model_settings(reasoning_off: bool = True) -> OpenAIChatModelSettings:
    # Same issue as HW5: Portkey/Azure refuse function tools on gpt-6-luna chat completions when
    # reasoning is on, so reasoning is turned off. (Re-checked in Step 2; see README.)
    if reasoning_off:
        return OpenAIChatModelSettings(max_tokens=MAX_OUTPUT_TOKENS, openai_reasoning_effort="none")
    return OpenAIChatModelSettings(max_tokens=MAX_OUTPUT_TOKENS)


def build_model(http_log: list[dict[str, Any]] | None = None) -> Model:
    """gpt-6-luna through Portkey. The key comes from the environment, never from code.

    If http_log is given, every HTTP response from Portkey adds its status code, Portkey cache
    status (HIT = answer reused from Portkey's cache) and trace id to the list.
    """
    load_project_env()
    api_key = os.getenv("PORTKEY_API_KEY")
    if not api_key:
        raise RuntimeError("PORTKEY_API_KEY is missing. Add it to .env in this folder or the folder above.")

    async def log_response(response: httpx2.Response) -> None:
        if http_log is not None:
            http_log.append({
                "http_status": response.status_code,
                "portkey_cache_status": response.headers.get("x-portkey-cache-status"),
                "portkey_trace_id": response.headers.get("x-portkey-trace-id"),
            })

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=PORTKEY_BASE_URL,
        default_headers={"x-portkey-api-key": api_key},
        timeout=API_TIMEOUT_SECONDS,
        max_retries=1,
        http_client=httpx2.AsyncClient(timeout=API_TIMEOUT_SECONDS, event_hooks={"response": [log_response]}),
    )
    return OpenAIChatModel(MODEL_NAME, provider=OpenAIProvider(openai_client=client))


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

def compute_overall(statuses: list[str], anything_unclear: bool) -> str:
    """The same rule the prompt gives the AI, computed in Python."""
    if FAIL in statuses:
        return FAIL
    if NEEDS_REVIEW in statuses or anything_unclear or not statuses:
        return NEEDS_REVIEW
    return PASS


def report_mismatches(report: PrintProofReport, deps: AgentDeps) -> list[str]:
    """Differences between the AI's report and the real tool results (empty = consistent)."""
    problems = []
    checks = {r.tool_name: r for r in deps.checks_run()}
    reported = [f.tool_name for f in report.findings]

    for name in checks:
        if name not in reported:
            problems.append(f"Missing a finding for {name}, which was called.")
    for name in set(reported):
        if reported.count(name) > 1:
            problems.append(f"{name} is reported more than once.")
    for finding in report.findings:
        record = checks.get(finding.tool_name)
        if record is None:
            problems.append(f"{finding.tool_name} is reported but was never called successfully.")
        elif finding.status != record.output["status"]:
            problems.append(f"{finding.tool_name} status must be '{record.output['status']}', "
                            f"not '{finding.status}'.")

    unclear = bool(report.clarifications_needed) or any(not r.checkable for r in report.understood_requirements)
    expected = compute_overall([r.output["status"] for r in checks.values()], unclear)
    if report.overall_status != expected:
        problems.append(f"overall_status must be '{expected}', not '{report.overall_status}'.")
    return problems


def build_agent(model: Model | None = None, reasoning_off: bool = True,
                http_log: list[dict[str, Any]] | None = None) -> Agent[AgentDeps, PrintProofReport]:
    agent = Agent(
        model if model is not None else build_model(http_log),
        output_type=PrintProofReport,
        instructions=PROMPT_PATH.read_text(encoding="utf-8"),
        deps_type=AgentDeps,
        retries=AGENT_RETRIES,
        model_settings=model_settings(reasoning_off),
        name="printproof",
    )

    def call(fn, ctx: RunContext[AgentDeps], *args):
        try:
            return fn(ctx.deps, *args)
        except tools.ToolInputError as exc:
            raise ModelRetry(str(exc)) from exc

    @agent.tool
    def get_document_overview(ctx: RunContext[AgentDeps]) -> dict[str, Any]:
        """Page count, page sizes and which pages look scanned or blank. Contains no document text."""
        return call(tools.get_document_overview, ctx)

    @agent.tool
    def check_page_limit(ctx: RunContext[AgentDeps], max_pages: int) -> dict[str, Any]:
        """Check that the PDF has at most `max_pages` pages."""
        return call(tools.check_page_limit, ctx, max_pages)

    @agent.tool
    def check_paper_size(ctx: RunContext[AgentDeps], paper_size: Literal["US Letter", "A4"]) -> dict[str, Any]:
        """Check that every page is the given paper size (US Letter or A4)."""
        return call(tools.check_paper_size, ctx, paper_size)

    @agent.tool
    def check_min_font_size(ctx: RunContext[AgentDeps], min_font_size_pt: float) -> dict[str, Any]:
        """Check that no visible text is smaller than `min_font_size_pt` points."""
        return call(tools.check_min_font_size, ctx, min_font_size_pt)

    @agent.tool
    def check_min_margins(ctx: RunContext[AgentDeps], min_margin: float,
                          unit: Literal["in", "mm", "cm"] = "in") -> dict[str, Any]:
        """Check that all content is at least `min_margin` (in the given unit) from every page edge."""
        return call(tools.check_min_margins, ctx, min_margin, unit)

    @agent.output_validator
    def must_match_tools(ctx: RunContext[AgentDeps], report: PrintProofReport) -> PrintProofReport:
        problems = report_mismatches(report, ctx.deps)
        if problems:
            raise ModelRetry("Your report does not match the tool results: " + " ".join(problems))
        return report

    return agent


# ---------------------------------------------------------------------------
# Audit trail (append-only JSON array)
# ---------------------------------------------------------------------------

_audit_lock = threading.Lock()
_KEYLIKE = re.compile(r"\b(sk|pk)-[A-Za-z0-9_-]{12,}\b")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _mask(value: Any) -> Any:
    """Mask anything that looks like an API key, so secrets never reach the log."""
    if isinstance(value, str):
        key = os.getenv("PORTKEY_API_KEY")
        if key and key in value:
            value = value.replace(key, "[key removed]")
        return _KEYLIKE.sub("[key removed]", value)
    if isinstance(value, dict):
        return {k: _mask(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask(v) for v in value]
    return value


def append_audit_events(events: list[dict[str, Any]], path: Path = AUDIT_PATH) -> None:
    """Add events to the JSON array without rewriting earlier records.

    Only the final "]" is replaced. If the file is not a JSON array we can extend safely,
    nothing is written, so old records are never lost.
    """
    if not events:
        return
    stamp = _now()
    body = ",\n".join(json.dumps(_mask({"time": stamp, **e}), ensure_ascii=False, default=str) for e in events)
    with _audit_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.stat().st_size == 0:
            path.write_text("[\n" + body + "\n]\n", encoding="utf-8")
            return
        with open(path, "r+b") as f:
            f.seek(0, 2)
            pos = f.tell()
            ch = b""
            while pos > 0:  # walk back past whitespace to the closing "]"
                pos -= 1
                f.seek(pos)
                ch = f.read(1)
                if not ch.isspace():
                    break
            if ch != b"]":
                logger.error("Audit file %s does not end with ']'; events not written", path)
                return
            f.seek(0)
            empty = f.read(pos).strip() == b"["
            f.seek(pos)
            f.write((("\n" if empty else ",\n") + body + "\n]\n").encode("utf-8"))


def read_audit_events(path: Path = AUDIT_PATH) -> list[dict[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Running one analysis
# ---------------------------------------------------------------------------

@dataclass
class AIRunOutcome:
    run_id: str
    report: PrintProofReport | None
    deps: AgentDeps
    usage: dict[str, int]
    api_calls: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    mismatches: list[str] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def verified_overall(self) -> str:
        """Overall status computed in Python from the real tool results."""
        unclear = bool(self.report and (self.report.clarifications_needed or
                                        any(not r.checkable for r in self.report.understood_requirements)))
        return compute_overall([r.output["status"] for r in self.deps.checks_run()], unclear)


def _usage_dict(usage: RunUsage, api_calls: list[dict[str, Any]]) -> dict[str, int]:
    cached = sum(c["input_tokens"] + c["output_tokens"] for c in api_calls if c.get("portkey_cache_status") == "HIT")
    return {
        "requests": usage.requests,
        "tool_calls": usage.tool_calls,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
        # Tokens reported by responses that Portkey served from its cache (no new model work).
        "tokens_from_portkey_cache": cached,
        "new_model_tokens": usage.total_tokens - cached,
    }


def _api_calls(messages, http_log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One entry per model response: real usage reported by the API, Portkey cache status and the
    tools it asked for. Rejected HTTP calls (no model response) are listed with their status code."""
    ok_http = [h for h in http_log if h["http_status"] == 200]
    calls = []
    responses = [m for m in messages if isinstance(m, ModelResponse)]
    for i, msg in enumerate(responses):
        http = ok_http[i] if i < len(ok_http) else {}
        calls.append({
            "model": msg.model_name,
            "provider_response_id": msg.provider_response_id,
            "portkey_cache_status": http.get("portkey_cache_status"),
            "portkey_trace_id": http.get("portkey_trace_id"),
            "finish_reason": msg.finish_reason,
            "input_tokens": msg.usage.input_tokens,
            "output_tokens": msg.usage.output_tokens,
            "tools_requested": [p.tool_name for p in msg.parts if isinstance(p, ToolCallPart)],
        })
    for h in http_log:
        if h["http_status"] != 200:
            calls.append({"model": MODEL_NAME, "rejected": True, **h,
                          "input_tokens": 0, "output_tokens": 0, "tools_requested": []})
    return calls


def run_ai_check(pdf_bytes: bytes, file_name: str, requirements_text: str,
                 model: Model | None = None, reasoning_off: bool = True,
                 audit_path: Path = AUDIT_PATH) -> AIRunOutcome:
    """Run the agent on one PDF and plain-English requirements. Always writes an audit record."""
    text = (requirements_text or "").strip()
    if not text:
        raise ValueError("Please describe the requirements first.")
    if len(text) > MAX_REQUIREMENTS_CHARS:
        raise ValueError(f"Requirements are too long (max {MAX_REQUIREMENTS_CHARS} characters).")
    with open_pdf(pdf_bytes) as doc:  # fail early on a bad PDF, before spending tokens
        page_count = doc.page_count

    deps = AgentDeps(pdf_bytes=pdf_bytes, file_name=file_name, audit_run_id=uuid.uuid4().hex[:12])
    usage = RunUsage()
    outcome = AIRunOutcome(run_id=deps.audit_run_id, report=None, deps=deps, usage={})
    started = time.perf_counter()
    messages = []
    http_log: list[dict[str, Any]] = []
    try:
        agent = build_agent(model, reasoning_off=reasoning_off, http_log=http_log)
        # capture_run_messages keeps the API responses even if the run fails part-way.
        with capture_run_messages() as messages:
            result = agent.run_sync(
                f"User's requirements for the file '{file_name}':\n<requirements>\n{text}\n</requirements>",
                deps=deps, usage=usage, usage_limits=USAGE_LIMITS,
            )
        outcome.report = result.output
        outcome.mismatches = report_mismatches(result.output, deps)
    except UsageLimitExceeded as exc:
        outcome.error = f"Stopped by the safety limit: {exc}"
    except (PDFCheckError, RuntimeError, ValueError) as exc:
        outcome.error = str(exc)
    except Exception as exc:  # API/network errors: report them instead of crashing the app
        if "output retries" in str(exc):
            outcome.error = ("The AI's report did not match the measured results, even after retries, so it "
                             "was rejected. The measured results below come directly from the PDF checker.")
        elif "content_filter" in str(exc):
            outcome.error = ("Blocked by the Azure OpenAI safety filter (the text looked like an attempt to "
                             "override the agent's instructions). Nothing was checked; please rephrase "
                             "your requirements.")
        else:
            outcome.error = f"{type(exc).__name__}: {exc}"
    outcome.seconds = round(time.perf_counter() - started, 2)
    outcome.api_calls = _api_calls(messages, http_log)
    outcome.usage = _usage_dict(usage, outcome.api_calls)

    model_name = getattr(model, "model_name", None) if model is not None else MODEL_NAME
    events: list[dict[str, Any]] = [{
        "event": "ai_run_start",
        "run_id": deps.audit_run_id,
        "model": model_name,
        "reasoning_effort": "none" if reasoning_off else "default",
        "file_name": file_name,
        "file_sha256": deps.file_sha256,
        "page_count": page_count,
        "requirements_text": text,
        "limits": {"request_limit": USAGE_LIMITS.request_limit,
                   "tool_calls_limit": USAGE_LIMITS.tool_calls_limit,
                   "total_tokens_limit": USAGE_LIMITS.total_tokens_limit,
                   "max_output_tokens": MAX_OUTPUT_TOKENS},
    }]
    for i, call in enumerate(outcome.api_calls, 1):
        events.append({"event": "api_call", "run_id": deps.audit_run_id, "call_number": i, **call})
    for record in deps.tool_records:
        events.append({"event": "tool_call", "run_id": deps.audit_run_id, "tool": record.tool_name,
                       "arguments": record.arguments, "result": record.output})
    events.append({
        "event": "ai_run_end",
        "run_id": deps.audit_run_id,
        "ok": outcome.error is None,
        "error": outcome.error,
        "seconds": outcome.seconds,
        "usage": outcome.usage,
        "ai_overall_status": outcome.report.overall_status if outcome.report else None,
        "python_overall_status": outcome.verified_overall if outcome.report else None,
        "report_matches_tools": outcome.report is not None and not outcome.mismatches,
        "understood_requirements": [r.model_dump() for r in outcome.report.understood_requirements]
        if outcome.report else [],
        "clarifications_needed": outcome.report.clarifications_needed if outcome.report else [],
    })
    append_audit_events(events, audit_path)
    return outcome

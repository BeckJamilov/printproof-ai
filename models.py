"""Data types for the PrintProof AI agent (Step 2).

- AgentDeps:   what the agent's tools can use during one run (the PDF stays here, in Python).
- ToolRecord:  one tool call and the real result our Python checker returned.
- PrintProofReport: the structured output the AI must return.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

from pdf_checker import CheckResult

Status = Literal["Pass", "Fail", "Needs Review"]
RequirementKind = Literal["max_pages", "paper_size", "min_font_size", "min_margins", "other"]


# ---------------------------------------------------------------------------
# Run state (never sent to the model as a whole)
# ---------------------------------------------------------------------------

@dataclass
class ToolRecord:
    """One tool call made by the agent, with the Python result it received."""

    tool_name: str
    arguments: dict[str, Any]
    output: dict[str, Any]  # exactly what was returned to the model
    check_result: CheckResult | None = None  # full result (with highlights) for the app


@dataclass
class AgentDeps:
    """Dependencies for one agent run. The PDF bytes never leave Python."""

    pdf_bytes: bytes
    file_name: str
    tool_records: list[ToolRecord] = field(default_factory=list)
    audit_run_id: str = ""

    @property
    def file_sha256(self) -> str:
        return hashlib.sha256(self.pdf_bytes).hexdigest()

    def latest_check(self, tool_name: str) -> ToolRecord | None:
        """Most recent successful check from a tool (the one the report must match)."""
        for record in reversed(self.tool_records):
            if record.tool_name == tool_name and record.check_result is not None:
                return record
        return None

    def checks_run(self) -> list[ToolRecord]:
        """Latest result for every check tool that ran, in first-call order."""
        seen: dict[str, ToolRecord] = {}
        for record in self.tool_records:
            if record.check_result is not None:
                seen[record.tool_name] = record
        return list(seen.values())


# ---------------------------------------------------------------------------
# Structured output from the AI
# ---------------------------------------------------------------------------

class UnderstoodRequirement(BaseModel):
    """One requirement the AI found in the user's plain-English text."""

    kind: RequirementKind = Field(
        description="Which supported check this maps to, or 'other' if no tool can check it."
    )
    user_wording: str = Field(description="The user's own words for this requirement, quoted briefly.")
    interpreted_as: str = Field(
        description="How it was understood, with the exact value and unit, e.g. 'At most 5 pages' or "
                    "'Margins of at least 25 mm on every side'."
    )
    checkable: bool = Field(description="True only if one of the check tools can measure it.")
    note: str | None = Field(
        default=None,
        description="Why it is unclear or cannot be checked, or what assumption was made. Null if none.",
    )


class Finding(BaseModel):
    """The AI's explanation of one tool result. Status must match the tool output exactly."""

    tool_name: Literal["check_page_limit", "check_paper_size", "check_min_font_size", "check_min_margins"]
    status: Status = Field(description="Copied exactly from the tool output.")
    explanation: str = Field(
        description="One or two plain-English sentences using only the measurements and page numbers "
                    "from the tool output."
    )


class PrintProofReport(BaseModel):
    """Final structured answer from the PrintProof agent."""

    understood_requirements: list[UnderstoodRequirement] = Field(
        description="Every requirement found in the user's text, including ones that cannot be checked."
    )
    clarifications_needed: list[str] = Field(
        default_factory=list,
        description="Requirements that were unclear, ambiguous or unsupported, and what the user should "
                    "clarify or check by hand. Empty if everything was clear.",
    )
    findings: list[Finding] = Field(
        description="One finding per check tool that was called, based only on its output."
    )
    overall_status: Status = Field(
        description="Fail if any finding failed; otherwise Needs Review if any finding needs review or "
                    "anything was unclear/unchecked; otherwise Pass."
    )
    summary: str = Field(description="Two or three sentences for a manager, using only tool results.")

"""Typed contracts at agent and model boundaries.

* ``AgentResult`` - what every agent node returns to the orchestrator: an
  explicit outcome plus a state patch. Agents never write fields they do
  not own (see docs/STATE_CONTRACT.md).
* The ``*Extraction`` / ``IntakeInterpretation`` / ``ScopeScreen`` /
  ``AuditCritique`` / ``LineExplanations`` / ``CoverNote`` models are the
  structured outputs requested from the model. Model output is validated
  against them before anything reaches state.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class Outcome(str, Enum):
    SUCCESS = "success"
    NEED_INPUT = "need_more_input"
    REVISION = "revision_request"
    ESCALATION = "escalation"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Intake
# ---------------------------------------------------------------------------

IntakeIntent = Literal[
    "answer",            # answers the current question
    "correction",        # changes an earlier answer
    "go_back",           # asks to go back / redo the previous question
    "repeat",            # asks to repeat or explain the question
    "clarify",           # asks what a word or the question means
    "unsure",            # does not know the answer
    "help",              # wants a human
    "advice",            # asks for tax advice / planning / optimisation
    "off_topic",         # wanders
]

OutOfScopeCategory = Literal[
    "itemized_deductions", "self_employment", "rental_income", "capital_gains", "digital_assets",
    "foreign_income", "amended_or_prior_year", "state_return", "other",
]


class Correction(BaseModel):
    question_id: str = Field(description="id of the earlier question being corrected")
    new_answer: str = Field(description="the new answer in the taxpayer's words")


class IntakeSignals(BaseModel):
    advice_request: bool = Field(description="asks what they should do to pay less, plan, optimise, or whether something is deductible")
    third_party_without_authority: bool = Field(description="someone other than the taxpayer is answering and no authority (e.g. power of attorney) is stated")
    exploitation_concern: bool = Field(description="pressure, coercion, or refund routed to someone else's or an unknown account")
    spouse_died_2025: bool = Field(description="mentions their spouse died during 2025")
    out_of_scope: list[OutOfScopeCategory] = Field(description="out-of-scope situations the taxpayer clearly says apply to them (not ones they deny)")
    evidence: str = Field(description="short quote from the message supporting any signal, else empty")


class IntakeInterpretation(BaseModel):
    intent: IntakeIntent
    answer: Optional[str] = Field(description="normalised answer to the current question if intent is answer, else null")
    corrections: list[Correction] = Field(description="earlier answers the taxpayer changed")
    signals: IntakeSignals
    reply: str = Field(description="at most two short plain-language sentences; no numbers, no tax advice")


# ---------------------------------------------------------------------------
# Document extraction (values are transcribed text, never interpreted)
# ---------------------------------------------------------------------------


class ExtractedField(BaseModel):
    box: str = Field(description="box label as printed, e.g. '1' or '2a'")
    text: Optional[str] = Field(description="amount or value exactly as printed, null if blank")
    readable: bool = Field(description="false if the box exists but cannot be read clearly")


class DocumentExtraction(BaseModel):
    form_type_seen: Literal["W-2", "1099-INT", "1099-DIV", "1099-R", "SSA-1099", "other", "unreadable"]
    tax_year: Optional[str] = Field(description="tax/calendar year printed on the form")
    recipient_name: Optional[str]
    recipient_ssn: Optional[str] = Field(description="recipient/employee SSN or TIN as printed (may be masked)")
    payer_name: Optional[str] = Field(description="employer or payer name")
    fields: list[ExtractedField] = Field(description="every box on the form that has a printed value")
    checkboxes: list[str] = Field(description="labels of checked boxes, e.g. 'IRA/SEP/SIMPLE', 'Taxable amount not determined', 'Retirement plan'")
    distribution_code: Optional[str] = Field(description="1099-R box 7 code(s) as printed, else null")
    notes: str = Field(description="anything unusual (handwriting, corrections, 'CORRECTED' box), else empty")


# ---------------------------------------------------------------------------
# Rules, audit, assembly
# ---------------------------------------------------------------------------


class ScopeFinding(BaseModel):
    category: OutOfScopeCategory
    evidence: str


class ScopeScreen(BaseModel):
    findings: list[ScopeFinding] = Field(description="out-of-scope situations evidenced in the material; empty if none")


class AuditFinding(BaseModel):
    line: str
    concern: str
    severity: Literal["advisory", "recheck_source"]
    doc_id: Optional[str] = None
    box: Optional[str] = None


class AuditCritique(BaseModel):
    findings: list[AuditFinding]
    summary: str


class LineExplanation(BaseModel):
    line: str
    text: str


class LineExplanations(BaseModel):
    explanations: list[LineExplanation]


class CoverNote(BaseModel):
    note: str = Field(description="short note for the Kushim reviewer; may only repeat numbers given in the input")


# ---------------------------------------------------------------------------
# agent result envelope
# ---------------------------------------------------------------------------


class AgentResult(BaseModel):
    agent: str
    outcome: Outcome
    summary: str
    patch: dict = Field(default_factory=dict)
    escalation: Optional[dict] = None
    revision_targets: list[str] = Field(default_factory=list)

    def to_update(self, now: str) -> dict:
        """Convert to a LangGraph state update with a trace entry."""
        update = dict(self.patch)
        update.setdefault("trace", [])
        update["trace"] = list(update["trace"]) + [{
            "at": now, "agent": self.agent, "outcome": self.outcome.value, "summary": self.summary,
        }]
        if self.escalation is not None:
            update["escalation"] = self.escalation
        return update

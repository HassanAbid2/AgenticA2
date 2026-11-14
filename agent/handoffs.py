"""Structured hand-offs between agents (C3). Anything a later step decides on is one of these
Pydantic objects, never free text."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RiskFlag = Literal["scam", "unpaid_work", "off_platform_contact", "off_platform_payment", "personal_info_request",
                   "overpayment_scheme", "prompt_injection", "low_budget", "unverified_payment", "new_client",
                   "poor_client_history", "duplicate"]


class JobSpec(BaseModel):
    job_id: str
    title: str
    category: str = ""
    deliverables: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    nice_to_have: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list, description="Atomic requirements, one capability each")
    budget_type: Literal["fixed", "hourly"] = "fixed"
    budget_min: float | None = None
    budget_max: float | None = None
    timeline_days: int | None = None
    hours_per_week: int | None = None
    screening_questions: list[str] = Field(default_factory=list)
    hidden_needs: list[str] = Field(default_factory=list, description="Needs implied but not stated")
    client_industry: str | None = None
    source: Literal["llm", "rules"] = "rules"


class RiskReport(BaseModel):
    score: float = Field(ge=0, le=1, description="0 safe .. 1 certainly a scam")
    client_quality: float = Field(0.5, ge=0, le=1)
    flags: list[RiskFlag] = Field(default_factory=list)
    injection_detected: bool = False
    injected_spans: list[str] = Field(default_factory=list)
    explanation: str = ""


class RequirementEvidence(BaseModel):
    requirement: str
    evidence_ids: list[str] = Field(default_factory=list)
    titles: list[str] = Field(default_factory=list)
    best_score: float = 0.0
    strength: Literal["strong", "partial", "none"] = "none"


class FitReport(BaseModel):
    score: float = Field(ge=0, le=1)
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    matrix: list[RequirementEvidence] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    insufficient_evidence: bool = False


class BidDecision(BaseModel):
    action: Literal["bid", "watch", "skip"]
    reasons: list[str] = Field(default_factory=list)
    confidence: float = Field(0.5, ge=0, le=1)
    auto: bool = False


class PriceQuote(BaseModel):
    amount: float = Field(gt=0)
    unit: Literal["fixed", "hourly"]
    band_low: float
    band_high: float
    connects_cost: int = 0
    connects_worth_it: bool = True
    expected_reply_rate: float = 0.0
    floor_applied: bool = False
    rationale: list[str] = Field(default_factory=list)


class ClaimCheck(BaseModel):
    claim: str
    label: Literal["supported", "partly_supported", "unsupported"]
    score: float = 0.0
    evidence_ids: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class ProposalDraft(BaseModel):
    job_id: str
    cover_letter: str = Field(description="Cover letter with [n] citations pointing at numbered evidence")
    screening_answers: list[str] = Field(default_factory=list)
    evidence: list[dict] = Field(default_factory=list)
    claims: list[ClaimCheck] = Field(default_factory=list)
    removed_claims: list[str] = Field(default_factory=list)
    unsupported_rate_before: float = 0.0
    unsupported_rate_after: float = 0.0
    revision: int = 0
    strategy: str = "evidence_first"
    status: str = "pending_review"


class WriterOutput(BaseModel):
    """What the Writer LLM returns (the graph adds evidence and verification)."""

    cover_letter: str
    screening_answers: list[str] = Field(default_factory=list)


class Critique(BaseModel):
    approve: bool
    score: float = Field(5, ge=0, le=10)
    issues: list[str] = Field(default_factory=list)
    instructions: str = ""
    grounded: bool = True
    personalised: bool = True
    length_ok: bool = True


class Violation(BaseModel):
    rule_id: str
    message: str
    action: Literal["redact", "rewrite", "block", "append"]
    excerpt: str = ""


class ComplianceVerdict(BaseModel):
    status: Literal["pass", "fixed", "block"]
    violations: list[Violation] = Field(default_factory=list)
    cleaned_text: str = ""
    cleaned_answers: list[str] = Field(default_factory=list)


class ApprovalDecision(BaseModel):
    action: Literal["approve", "edit", "reject"]
    edited_text: str | None = None
    edited_answers: list[str] | None = None
    bid_amount: float | None = None
    reason: str | None = None


class ClientIntent(BaseModel):
    intent: Literal["question", "negotiation", "interview_request", "scam_signal", "injection", "other"]
    confidence: float = Field(0.5, ge=0, le=1)
    explanation: str = ""
    asked_price: float | None = None


class ReplyDraft(BaseModel):
    text: str
    proposed_slots: list[dict] = Field(default_factory=list)
    counter_price: float | None = None
    flags: list[str] = Field(default_factory=list)

"""Request / response models: the typed API contract the TypeScript client is generated from."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class SignupIn(BaseModel):
    email: str = Field(pattern=EMAIL, max_length=200)
    password: str = Field(min_length=8, max_length=200)
    name: str = Field("", max_length=200)


class LoginIn(BaseModel):
    email: str = Field(pattern=EMAIL, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    persona: str | None
    onboarded: bool
    settings: dict[str, Any]


class OnboardingIn(BaseModel):
    persona: Literal["ai_ml", "fullstack", "data_analyst", "own"]
    marketplace: Literal["gigsim", "upwork"] = "gigsim"
    gigsim_token: str | None = Field(None, max_length=200)
    hourly_rate: float = Field(gt=0, le=1000)
    floor_hourly: float = Field(gt=0, le=1000)
    min_fixed: float = Field(ge=0, le=1_000_000)
    weekly_connects_budget: int = Field(ge=0, le=10_000)
    categories: list[str] = Field(default_factory=list, max_length=10)
    keywords: list[str] = Field(default_factory=list, max_length=10)
    headline: str = Field("", max_length=300)


class SettingsIn(BaseModel):
    autonomy: Literal["suggest", "auto_skip_low_fit"] | None = None
    hourly_rate: float | None = Field(None, gt=0, le=1000)
    floor_hourly: float | None = Field(None, gt=0, le=1000)
    min_fixed: float | None = Field(None, ge=0)
    weekly_connects_budget: int | None = Field(None, ge=0, le=10_000)
    headline: str | None = Field(None, max_length=300)


class SavedSearchIn(BaseModel):
    name: str = Field(max_length=200)
    query: str = Field("", max_length=300)
    skills: list[str] = Field(default_factory=list, max_length=10)
    category: str = Field("", max_length=100)
    min_budget: float = Field(0, ge=0)
    interval_minutes: int = Field(180, ge=15, le=10_080)
    enabled: bool = True


class SavedSearchOut(SavedSearchIn):
    id: int
    last_run_at: datetime | None


class JobRow(BaseModel):
    job_id: str
    title: str
    category: str
    status: str
    decision: str | None
    fit_score: float | None
    risk_score: float | None
    risk_flags: list[str]
    price: float | None
    price_unit: str | None
    connects_cost: int | None
    budget: dict[str, Any]
    posted_at: str
    duplicate_of: str | None
    reason: str | None
    pipeline: str | None


class JobList(BaseModel):
    jobs: list[JobRow]
    counts: dict[str, int]


class JobDetail(BaseModel):
    job: dict[str, Any]
    row: JobRow
    analysis: dict[str, Any]
    approval_id: int | None
    run_id: int | None
    runs: list[dict[str, Any]]


class AnalyseIn(BaseModel):
    force_bid: bool = False


class Queued(BaseModel):
    queued: bool
    detail: str = ""


class ApprovalOut(BaseModel):
    id: int
    thread_id: str
    graph: str
    kind: str
    status: str
    payload: dict[str, Any]
    created_at: datetime
    reason: str | None = None


class DecisionIn(BaseModel):
    action: Literal["approve", "edit", "reject"]
    edited_text: str | None = Field(None, max_length=6000)
    reason: str | None = Field(None, max_length=1000)
    bid_amount: float | None = Field(None, gt=0)


class RegenerateIn(BaseModel):
    paragraph_index: int = Field(ge=0, le=20)
    text: str = Field(max_length=6000, description="current full text")
    instruction: str = Field("", max_length=500)


class RegenerateOut(BaseModel):
    text: str
    paragraph: str
    claims: list[dict[str, Any]]
    violations: list[dict[str, Any]]


class ProposalCard(BaseModel):
    id: int
    job_id: str
    title: str
    status: str
    bid_amount: float | None
    bid_unit: str = "fixed"
    connects_spent: int
    category: str
    strategy: str
    updated_at: datetime
    approval_id: int | None = None


class Pipeline(BaseModel):
    columns: dict[str, list[ProposalCard]]


class ThreadOut(BaseModel):
    id: int
    marketplace_thread_id: str
    job_id: str
    title: str
    status: str
    intent: str | None
    messages: list[dict[str, Any]]
    approval: ApprovalOut | None


class RunOut(BaseModel):
    id: int
    thread_id: str
    graph: str
    job_id: str | None
    status: str
    trace_id: str
    trace_url: str | None
    tokens: int
    cost_usd: float
    latency_s: float
    steps: int
    per_node: dict[str, Any]
    error: str | None
    started_at: datetime
    ended_at: datetime | None


class RunEventOut(BaseModel):
    id: int
    node: str
    kind: str
    payload: dict[str, Any]
    ts: datetime


class RunDetail(BaseModel):
    run: RunOut
    events: list[RunEventOut]
    audit: list[dict[str, Any]]


class Analytics(BaseModel):
    by_category: list[dict[str, Any]]
    funnel: dict[str, int]
    connects: dict[str, Any]
    cost_latency: dict[str, Any]
    rejection_reasons: list[dict[str, Any]]
    budgets: dict[str, Any]


class MemoryItem(BaseModel):
    namespace: str
    key: str
    value: dict[str, Any]


class MemoryOut(BaseModel):
    style: list[MemoryItem]
    outcome: list[MemoryItem]
    edits_logged: int


class EvidenceOut(BaseModel):
    evidence_id: str
    type: str
    title: str
    project: str | None
    date: str | None
    owner: str
    excluded: bool


class AccountOut(BaseModel):
    provider: str
    connected: bool
    meta: dict[str, Any]


class HealthOut(BaseModel):
    api: str
    marketplace_ok: bool
    mode: str
    detail: str
    model_profile: str
    llm: bool

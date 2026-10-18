"""Pydantic models for Letter Decoder API contract.

These models are the single source of truth. JSON Schema and OpenAPI are
generated from them and committed to the contract directory.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ANSWER_SCHEMA_VERSION = "0.1.0"


class FactKind(str, Enum):
    DATE = "date"
    AMOUNT = "amount"
    REFERENCE = "reference"
    SENDER = "sender"
    OTHER = "other"


class VerificationStatus(str, Enum):
    """Evidence status of a fact against the source document."""

    SUPPORTED = "SUPPORTED"
    UNCERTAIN = "UNCERTAIN"
    NOT_FOUND = "NOT_FOUND"


class SeverityLevel(str, Enum):
    ROUTINE = "routine"
    ACT_SOON = "act_soon"
    SEE_PROFESSIONAL = "see_professional"
    UNKNOWN = "unknown"


class DeadlineKind(str, Enum):
    RESPONSE = "response"
    PAYMENT = "payment"
    APPEAL = "appeal"
    OTHER = "other"
    UNKNOWN = "unknown"


class AnswerStatus(str, Enum):
    QUEUED = "queued"
    READING = "reading"
    READY = "ready"
    ERROR = "error"


class Tone(str, Enum):
    NEUTRAL = "neutral"
    POLITE = "polite"
    FIRM = "firm"


class BoundingBox(BaseModel):
    """Normalized bounding box (0-1)."""

    model_config = ConfigDict(extra="forbid")
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    width: float = Field(ge=0.0, le=1.0)
    height: float = Field(ge=0.0, le=1.0)


class SourceSpan(BaseModel):
    """Source location in the original document."""

    model_config = ConfigDict(extra="forbid")
    page: int = Field(ge=1)
    text: str
    bbox: BoundingBox | None = None


class Fact(BaseModel):
    """A deterministic fact extracted from the letter."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    kind: FactKind
    label: str
    raw_value: str
    normalized_value: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    verified: bool = False
    source: SourceSpan
    verification: VerificationStatus = VerificationStatus.UNCERTAIN
    role: str | None = None

    @model_validator(mode="after")
    def _sync_verification(self) -> Fact:
        if "verification" not in self.model_fields_set:
            self.verification = (
                VerificationStatus.SUPPORTED
                if self.verified
                else VerificationStatus.UNCERTAIN
            )
        self.verified = self.verification == VerificationStatus.SUPPORTED
        return self


class SourceInfo(BaseModel):
    """Identity of the source document an answer was computed from."""

    model_config = ConfigDict(extra="forbid")
    filename: str | None = None
    sha256: str | None = None
    bytes: int | None = None
    chars: int | None = None
    preview: str | None = None
    method: str | None = None


class TrustAssessment(BaseModel):
    """Whether it is safe to act on the letter's demands as written."""

    model_config = ConfigDict(extra="forbid")
    sender_claimed: str | None = None
    sender_verified: bool = False
    payment_instructions_present: bool | None = None
    verify_before_payment: bool = False
    scam_pressure: bool = False
    reasons: list[str] = Field(default_factory=list)


class Classification(BaseModel):
    """Letter classification result."""

    model_config = ConfigDict(extra="forbid")
    notice_type_id: str
    country: str
    language: str
    sender: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    top_candidates: list[dict[str, Any]] = Field(default_factory=list)


class Deadline(BaseModel):
    """Deadline information."""

    model_config = ConfigDict(extra="forbid")
    fact_id: str | None = None
    kind: DeadlineKind = DeadlineKind.UNKNOWN
    iso_date: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)


class Severity(BaseModel):
    """Severity assessment."""

    model_config = ConfigDict(extra="forbid")
    level: SeverityLevel = SeverityLevel.UNKNOWN
    reason: str = ""
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)


class Verdict(BaseModel):
    """One-line verdict."""

    model_config = ConfigDict(extra="forbid")
    text: str
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)


class Explanation(BaseModel):
    """Plain-language explanation."""

    model_config = ConfigDict(extra="forbid")
    simple: str
    detailed: str


class Step(BaseModel):
    """Next step for the user."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    text: str
    detail: str | None = None
    fact_ids: list[str] = Field(default_factory=list)


class ChecklistItem(BaseModel):
    """Document to gather."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    text: str


class DraftReplies(BaseModel):
    """Reply drafts in different tones."""

    model_config = ConfigDict(extra="forbid")
    neutral: str
    polite: str | None = None
    firm: str | None = None


class BigPrint(BaseModel):
    """Large-print summary lines."""

    model_config = ConfigDict(extra="forbid")
    lines: list[str] = Field(default_factory=list, max_length=3)


class ClarifyingQuestion(BaseModel):
    """Single clarifying question with chip options."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    text: str
    options: list[str] = Field(min_length=2, max_length=5)


class Warning(BaseModel):
    """Warning or notice about the analysis."""

    model_config = ConfigDict(extra="forbid")
    code: str
    message: str
    bbox: BoundingBox | None = None


class Meta(BaseModel):
    """Metadata about the processing run."""

    model_config = ConfigDict(extra="forbid")
    engine_version: str
    model: str
    offline: bool = True
    timings_ms: dict[str, int] = Field(default_factory=dict)


class Answer(BaseModel):
    """Complete answer card for a processed letter."""

    model_config = ConfigDict(extra="forbid")
    schema_version: str = ANSWER_SCHEMA_VERSION
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    status: AnswerStatus = AnswerStatus.QUEUED
    facts: list[Fact] = Field(default_factory=list)
    classification: Classification | None = None
    deadline: Deadline | None = None
    severity: Severity | None = None
    verdict: Verdict | None = None
    explanation: Explanation | None = None
    steps: list[Step] = Field(default_factory=list)
    checklist: list[ChecklistItem] = Field(default_factory=list)
    draft_replies: DraftReplies | None = None
    big_print: BigPrint | None = None
    clarifying_question: ClarifyingQuestion | None = None
    warnings: list[Warning] = Field(default_factory=list)
    meta: Meta | None = None
    source: SourceInfo | None = None
    trust: TrustAssessment | None = None


class ErrorResponse(BaseModel):
    """Typed error response."""

    model_config = ConfigDict(extra="forbid")
    code: str
    message: str
    retryable: bool = False


class SSEEvent(BaseModel):
    """Server-Sent Event."""

    model_config = ConfigDict(extra="forbid")
    id: str
    event: str
    data: dict[str, Any]
    retry: int | None = None


class HealthResponse(BaseModel):
    """Health check response."""

    model_config = ConfigDict(extra="forbid")
    status: Literal["ok", "degraded", "down"]
    engine_mode: Literal["real", "mock", "unknown"]
    model_available: bool
    ollama_connected: bool
    offline: bool = True
    version: str = "0.1.0"

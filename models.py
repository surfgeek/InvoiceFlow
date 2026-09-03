"""Invoice data and timestamped processing records."""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


class InvoiceItem(BaseModel):
    """An extracted item; business validation determines acceptable quantities."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    name: str | None = None
    quantity: Decimal | None = None


class Invoice(BaseModel):
    """Extracted fields without inferred currency, rounding, or payment cutoffs."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    vendor: str | None = None
    amount: Decimal | None = None
    currency: str | None = None
    currency_qualification: Literal["explicit", "unqualified_dollar", "missing", "conflicting"] | None = None
    items: list[InvoiceItem] | None = None
    due_date: date | None = None

    @field_validator("due_date", mode="before")
    @classmethod
    def parse_calendar_date(cls, value):
        # Do not turn a timestamp into a due date by dropping its time or timezone.
        if value is None or type(value) is date:
            return value
        if isinstance(value, str):
            return date.fromisoformat(value)
        raise ValueError("Due date must be a calendar date, not a timestamp")


class ProcessingEvent(BaseModel):
    """A stage outcome recorded by the application at an explicit instant."""

    model_config = ConfigDict(extra="forbid")

    stage: Literal["ingestion", "validation", "approval", "payment"]
    status: Literal["started", "completed", "failed"]
    timestamp: AwareDatetime
    reason: str | None = None

    @field_validator("timestamp")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        return value.astimezone(timezone.utc)


class ReviewFinding(BaseModel):
    """A reviewer-reported discrepancy, with its retained resolution."""

    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1)
    extracted_value: str | None
    source_evidence: str | None
    explanation: str = Field(min_length=1)
    resolution: Literal["unresolved", "corrected", "unable_to_determine"] = "unresolved"


class ReviewAttempt(BaseModel):
    """Application-stamped review and the exact invoice it examined."""

    model_config = ConfigDict(extra="forbid")

    attempt: int
    timestamp: AwareDatetime
    invoice: Invoice
    findings: list[ReviewFinding] = Field(default_factory=list)
    outcome: Literal["passed", "issues", "failed"] = "failed"
    error: str | None = None

    @field_validator("timestamp")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        return value.astimezone(timezone.utc)


class ProcessingRecord(BaseModel):
    """System metadata kept separate from the contents of the invoice."""

    model_config = ConfigDict(extra="forbid")

    received_at: AwareDatetime
    run_id: str | None = None
    invoice_id: str | None = None
    currency_assumption: str | None = None
    events: list[ProcessingEvent] = Field(default_factory=list)
    reviews: list[ReviewAttempt] = Field(default_factory=list)

    @field_validator("received_at")
    @classmethod
    def normalize_received_at(cls, value: datetime) -> datetime:
        return value.astimezone(timezone.utc)

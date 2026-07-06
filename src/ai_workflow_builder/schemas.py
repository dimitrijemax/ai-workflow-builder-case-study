from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Channel(StrEnum):
    CHAT = "chat"
    PORTAL = "portal"
    SURVEY = "survey"
    FIELD_NOTE = "field_note"


class InsightCategory(StrEnum):
    ACCESS = "access"
    BUG = "bug"
    INTEGRATION = "integration"
    FEATURE_REQUEST = "feature_request"
    DOCUMENTATION = "documentation"
    PERFORMANCE = "performance"
    DATA_QUALITY = "data_quality"
    PROCESS_GAP = "process_gap"
    OTHER = "other"


class Sentiment(StrEnum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class OpsNote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=3)
    channel: Channel
    text: str = Field(min_length=10, max_length=2_000)
    created_at: datetime

    @field_validator("created_at", mode="before")
    @classmethod
    def parse_synthetic_day_token(cls, value: Any) -> Any:
        if isinstance(value, str) and value.startswith("day_"):
            parts = value.split("_")
            if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
                return datetime(2026, 1, int(parts[1]), int(parts[2]), tzinfo=UTC)
        return value


class OpsInsight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note_id: str
    category: InsightCategory
    sentiment: Sentiment
    summary: str = Field(min_length=10, max_length=500)
    action_items: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note_id: str
    code: str
    message: str
    severity: str = "warning"


class ReviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    insight: OpsInsight
    issues: list[ValidationIssue]
    status: str = "pending"
    reviewed_at: datetime | None = None


class BatchReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    insights: list[OpsInsight]
    issues: list[ValidationIssue]
    queued_for_review: list[ReviewItem]

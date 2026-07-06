import pytest
from pydantic import ValidationError

from ai_workflow_builder.schemas import OpsInsight, OpsNote


def test_ops_note_accepts_synthetic_day_token() -> None:
    note = OpsNote.model_validate(
        {
            "id": "N-1",
            "channel": "chat",
            "text": "A synthetic operations note with enough detail.",
            "created_at": "day_01_09",
        }
    )

    assert note.created_at.hour == 9


def test_ops_note_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        OpsNote.model_validate(
            {
                "id": "N-1",
                "channel": "chat",
                "text": "A synthetic operations note with enough detail.",
                "created_at": "day_01_09",
                "unexpected": True,
            }
        )


def test_ops_insight_rejects_invalid_confidence() -> None:
    with pytest.raises(ValidationError):
        OpsInsight.model_validate(
            {
                "note_id": "N-1",
                "category": "process_gap",
                "sentiment": "neutral",
                "summary": "A structured synthetic summary.",
                "action_items": ["Clarify the missing process step."],
                "confidence": 1.5,
            }
        )

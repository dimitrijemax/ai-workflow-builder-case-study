from ai_workflow_builder.schemas import OpsInsight, Sentiment
from ai_workflow_builder.validators import validate_insight


def test_low_confidence_is_flagged() -> None:
    insight = OpsInsight(
        note_id="N-1",
        category="other",
        sentiment="neutral",
        summary="A vague synthetic note that needs human review.",
        action_items=[],
        confidence=0.3,
    )

    issues = validate_insight(insight)

    assert [issue.code for issue in issues] == ["low_confidence"]


def test_negative_without_action_is_flagged() -> None:
    insight = OpsInsight(
        note_id="N-1",
        category="bug",
        sentiment=Sentiment.NEGATIVE,
        summary="A stakeholder is blocked by a failing workflow.",
        action_items=[],
        confidence=0.9,
    )

    issues = validate_insight(insight)

    assert "negative_without_action" in {issue.code for issue in issues}


def test_overconfident_summary_is_flagged() -> None:
    insight = OpsInsight(
        note_id="N-1",
        category="process_gap",
        sentiment="neutral",
        summary="This is guaranteed to be the exact root cause.",
        action_items=["Ask for reproduction details."],
        confidence=0.9,
    )

    issues = validate_insight(insight)

    assert "overconfident_summary" in {issue.code for issue in issues}

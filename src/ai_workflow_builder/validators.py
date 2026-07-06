from __future__ import annotations

from ai_workflow_builder.schemas import OpsInsight, Sentiment, ValidationIssue

MIN_CONFIDENCE = 0.65
OVERCONFIDENT_TERMS = ["guaranteed", "certainly", "without doubt", "always correct"]


def validate_insight(insight: OpsInsight) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    if insight.confidence < MIN_CONFIDENCE:
        issues.append(
            ValidationIssue(
                note_id=insight.note_id,
                code="low_confidence",
                message="Insight confidence is below the auto-pass threshold.",
            )
        )

    if insight.sentiment == Sentiment.NEGATIVE and not insight.action_items:
        issues.append(
            ValidationIssue(
                note_id=insight.note_id,
                code="negative_without_action",
                message="Negative stakeholder tone requires at least one action item.",
            )
        )

    lowered_summary = insight.summary.lower()
    if any(term in lowered_summary for term in OVERCONFIDENT_TERMS):
        issues.append(
            ValidationIssue(
                note_id=insight.note_id,
                code="overconfident_summary",
                message="Summary contains unsafe overconfident language.",
            )
        )

    return issues


def validate_batch(insights: list[OpsInsight]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for insight in insights:
        issues.extend(validate_insight(insight))
    return issues

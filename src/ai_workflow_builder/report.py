from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter

from ai_workflow_builder.review import load_review_queue
from ai_workflow_builder.schemas import OpsInsight

InsightAdapter = TypeAdapter(list[OpsInsight])


def load_insights(output_dir: Path) -> list[OpsInsight]:
    path = output_dir / "insights.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return InsightAdapter.validate_python(payload)


def build_markdown_report(output_dir: Path) -> str:
    insights = load_insights(output_dir)
    queue = load_review_queue(output_dir)
    queued_by_note = {item.insight.note_id: item for item in queue}

    approved_ids = {item.insight.note_id for item in queue if item.status == "approved"}
    rejected = [item for item in queue if item.status == "rejected"]
    pending = [item for item in queue if item.status == "pending"]

    reportable = [
        insight
        for insight in insights
        if insight.note_id not in queued_by_note or insight.note_id in approved_ids
    ]

    lines = [
        "# Operations Insights Report",
        "",
        "This report includes auto-passed insights and items approved by a human reviewer.",
        "",
        "## Included Insights",
        "",
    ]

    if not reportable:
        lines.append("No insights are approved for reporting yet.")
    for insight in reportable:
        lines.extend(
            [
                f"### {insight.note_id} - {insight.category.value}",
                "",
                f"- Sentiment: `{insight.sentiment.value}`",
                f"- Confidence: `{insight.confidence:.2f}`",
                f"- Summary: {insight.summary}",
                "- Action items:",
            ]
        )
        lines.extend(f"  - {item}" for item in insight.action_items)
        lines.append("")

    lines.extend(["## Pending Review", ""])
    if not pending:
        lines.append("No pending items.")
    for item in pending:
        codes = ", ".join(issue.code for issue in item.issues)
        lines.append(f"- {item.insight.note_id}: {codes}")

    lines.extend(["", "## Rejected Items", ""])
    if not rejected:
        lines.append("No rejected items.")
    for item in rejected:
        codes = ", ".join(issue.code for issue in item.issues)
        lines.append(f"- {item.insight.note_id}: {codes}")

    return "\n".join(lines) + "\n"


def write_markdown_report(output_dir: Path, report_path: Path | None = None) -> Path:
    path = report_path or output_dir / "report.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_markdown_report(output_dir), encoding="utf-8")
    return path

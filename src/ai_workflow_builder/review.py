from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import TypeAdapter

from ai_workflow_builder.schemas import OpsInsight, ReviewItem, ValidationIssue

ReviewQueueAdapter = TypeAdapter(list[ReviewItem])


def build_review_items(
    insights: list[OpsInsight],
    issues: list[ValidationIssue],
) -> list[ReviewItem]:
    issues_by_note: dict[str, list[ValidationIssue]] = {}
    for issue in issues:
        issues_by_note.setdefault(issue.note_id, []).append(issue)

    return [
        ReviewItem(insight=insight, issues=issues_by_note[insight.note_id])
        for insight in insights
        if insight.note_id in issues_by_note
    ]


def review_queue_path(output_dir: Path) -> Path:
    return output_dir / "review_queue.json"


def load_review_queue(output_dir: Path) -> list[ReviewItem]:
    path = review_queue_path(output_dir)
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return ReviewQueueAdapter.validate_python(payload)


def save_review_queue(output_dir: Path, queue: list[ReviewItem]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    # Same canonical byte contract as pipeline writers: UTF-8 without BOM, LF only, one final LF,
    # ensure_ascii=False / indent=2 / sort_keys=True. The reviewed_at value itself may vary.
    review_queue_path(output_dir).write_text(
        json.dumps(
            [item.model_dump(mode="json") for item in queue],
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def set_review_status(output_dir: Path, note_id: str, status: str) -> ReviewItem:
    if status not in {"approved", "rejected"}:
        raise ValueError("Review status must be approved or rejected.")

    queue = load_review_queue(output_dir)
    for item in queue:
        if item.insight.note_id == note_id:
            item.status = status
            item.reviewed_at = datetime.now(tz=UTC)
            save_review_queue(output_dir, queue)
            return item
    raise KeyError(f"Note is not in the review queue: {note_id}")

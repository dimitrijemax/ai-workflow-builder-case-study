from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import TypeAdapter

from ai_workflow_builder.providers import FakeLLM, LLMProvider
from ai_workflow_builder.review import build_review_items
from ai_workflow_builder.schemas import BatchReport, OpsInsight, OpsNote
from ai_workflow_builder.validators import validate_batch

OpsNotesAdapter = TypeAdapter(list[OpsNote])


def load_ops_notes(path: Path) -> list[OpsNote]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return OpsNotesAdapter.validate_python(payload)


def extract_insights(
    notes: list[OpsNote],
    provider: LLMProvider | None = None,
) -> list[OpsInsight]:
    selected_provider = provider or FakeLLM()
    return [OpsInsight.model_validate(selected_provider.extract_insight(note)) for note in notes]


def run_pipeline(input_path: Path, provider: LLMProvider | None = None) -> BatchReport:
    notes = load_ops_notes(input_path)
    insights = extract_insights(notes, provider=provider)
    issues = validate_batch(insights)
    review_items = build_review_items(insights, issues)
    return BatchReport(
        generated_at=datetime.now(tz=UTC),
        insights=insights,
        issues=issues,
        queued_for_review=review_items,
    )


def write_batch_report(batch: BatchReport, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "insights.json").write_text(
        json.dumps([item.model_dump(mode="json") for item in batch.insights], indent=2),
        encoding="utf-8",
    )
    (output_dir / "validation_issues.json").write_text(
        json.dumps([item.model_dump(mode="json") for item in batch.issues], indent=2),
        encoding="utf-8",
    )
    (output_dir / "review_queue.json").write_text(
        json.dumps([item.model_dump(mode="json") for item in batch.queued_for_review], indent=2),
        encoding="utf-8",
    )

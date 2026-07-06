from pathlib import Path

from ai_workflow_builder.pipeline import run_pipeline, write_batch_report
from ai_workflow_builder.report import build_markdown_report
from ai_workflow_builder.review import set_review_status


def test_unapproved_items_do_not_enter_report(tmp_path: Path) -> None:
    batch = run_pipeline(Path("examples/synthetic_ops_notes.json"))
    write_batch_report(batch, tmp_path)

    queued_ids = [item.insight.note_id for item in batch.queued_for_review]
    assert "N-1004" in queued_ids

    before = build_markdown_report(tmp_path)
    assert "### N-1004" not in before

    set_review_status(tmp_path, "N-1004", "approved")
    after = build_markdown_report(tmp_path)
    assert "### N-1004" in after


def test_rejected_items_are_listed_but_not_included(tmp_path: Path) -> None:
    batch = run_pipeline(Path("examples/synthetic_ops_notes.json"))
    write_batch_report(batch, tmp_path)

    set_review_status(tmp_path, "N-1008", "rejected")
    report = build_markdown_report(tmp_path)

    assert "### N-1008" not in report
    assert "- N-1008:" in report

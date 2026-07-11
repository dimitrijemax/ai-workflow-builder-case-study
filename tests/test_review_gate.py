import json
from pathlib import Path

from ai_workflow_builder.pipeline import run_pipeline, write_batch_report
from ai_workflow_builder.report import build_markdown_report
from ai_workflow_builder.review import save_review_queue, set_review_status
from ai_workflow_builder.schemas import (
    InsightCategory,
    OpsInsight,
    ReviewItem,
    Sentiment,
    ValidationIssue,
)

# Synthetic non-ASCII marker used only to exercise the review-writer encoding at the boundary.
NON_ASCII_MARKER = "café ✓ Ω"


def _assert_raw_utf8_not_escaped(path: Path, marker: str) -> None:
    raw = path.read_bytes()
    raw.decode("utf-8")  # must be valid UTF-8
    assert marker.encode("utf-8") in raw, f"{path.name} must embed raw UTF-8 bytes, not escapes"
    assert b"\\u" not in raw, f"{path.name} must not contain \\uXXXX escape sequences"


def _assert_canonical_json_bytes(path: Path) -> None:
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), f"{path.name} must have no UTF-8 BOM"
    assert b"\r" not in raw, f"{path.name} must use LF newlines only"
    assert raw.endswith(b"\n"), f"{path.name} must end with a final LF"
    assert not raw.endswith(b"\n\n"), f"{path.name} must end with exactly one final LF"
    text = raw.decode("utf-8")
    data = json.loads(text)
    expected = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    assert text == expected, f"{path.name} must use ensure_ascii=False, indent=2, sort_keys=True"


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


def test_review_queue_is_canonical_bytes_after_mutation(tmp_path: Path) -> None:
    batch = run_pipeline(Path("examples/synthetic_ops_notes.json"))
    write_batch_report(batch, tmp_path)
    queue_path = tmp_path / "review_queue.json"

    # The real reviewed_at value may vary; only the encoding/newline/serialization is claimed
    # deterministic after a human approve/reject mutation.
    set_review_status(tmp_path, "N-1004", "approved")
    _assert_canonical_json_bytes(queue_path)

    set_review_status(tmp_path, "N-1008", "rejected")
    _assert_canonical_json_bytes(queue_path)


def test_save_review_queue_embeds_raw_utf8_not_escaped(tmp_path: Path) -> None:
    insight = OpsInsight(
        note_id="N-UTF8",
        category=InsightCategory.OTHER,
        sentiment=Sentiment.NEUTRAL,
        summary=f"Synthetic non-ASCII summary {NON_ASCII_MARKER}",
        action_items=[],
        confidence=0.4,
    )
    issue = ValidationIssue(
        note_id="N-UTF8",
        code="synthetic_non_ascii",
        message=f"Synthetic non-ASCII message {NON_ASCII_MARKER}",
    )

    save_review_queue(tmp_path, [ReviewItem(insight=insight, issues=[issue])])

    _assert_raw_utf8_not_escaped(tmp_path / "review_queue.json", NON_ASCII_MARKER)

import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from ai_workflow_builder.cli import app
from ai_workflow_builder.pipeline import write_batch_report
from ai_workflow_builder.schemas import (
    BatchReport,
    InsightCategory,
    OpsInsight,
    ReviewItem,
    Sentiment,
    ValidationIssue,
)

# Synthetic non-ASCII marker (Latin-1, check mark, Greek) used only to exercise the writer
# encoding at the boundary; it never touches production fixtures or provider rules.
NON_ASCII_MARKER = "café ✓ Ω"


def _assert_raw_utf8_not_escaped(path: Path, marker: str) -> None:
    raw = path.read_bytes()
    raw.decode("utf-8")  # must be valid UTF-8
    assert marker.encode("utf-8") in raw, f"{path.name} must embed raw UTF-8 bytes, not escapes"
    assert b"\\u" not in raw, f"{path.name} must not contain \\uXXXX escape sequences"


def test_cli_analyze_writes_outputs(tmp_path: Path) -> None:
    input_path = tmp_path / "notes.json"
    input_path.write_text(
        json.dumps(
            [
                {
                    "id": "N-1",
                    "channel": "chat",
                    "text": "Rollout note with enough context for process review.",
                    "created_at": "day_01_09",
                }
            ]
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(app, ["analyze", str(input_path), "-o", str(tmp_path / "out")])

    assert result.exit_code == 0
    assert (tmp_path / "out" / "insights.json").exists()
    assert (tmp_path / "out" / "review_queue.json").exists()


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_NOTES_PATH = REPO_ROOT / "examples" / "synthetic_ops_notes.json"


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


def test_cli_analyze_outputs_are_canonical_bytes(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    result = CliRunner().invoke(app, ["analyze", str(EXAMPLE_NOTES_PATH), "-o", str(out_dir)])

    assert result.exit_code == 0, result.output
    for name in ("insights.json", "validation_issues.json", "review_queue.json"):
        _assert_canonical_json_bytes(out_dir / name)


def test_write_batch_report_embeds_raw_utf8_not_escaped(tmp_path: Path) -> None:
    insight = OpsInsight(
        note_id="N-UTF8",
        category=InsightCategory.OTHER,
        sentiment=Sentiment.NEGATIVE,
        summary=f"Synthetic non-ASCII summary {NON_ASCII_MARKER}",
        action_items=[f"Synthetic non-ASCII action {NON_ASCII_MARKER}"],
        confidence=0.5,
    )
    issue = ValidationIssue(
        note_id="N-UTF8",
        code="synthetic_non_ascii",
        message=f"Synthetic non-ASCII message {NON_ASCII_MARKER}",
    )
    batch = BatchReport(
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        insights=[insight],
        issues=[issue],
        queued_for_review=[ReviewItem(insight=insight, issues=[issue])],
    )

    write_batch_report(batch, tmp_path)

    for name in ("insights.json", "validation_issues.json", "review_queue.json"):
        _assert_raw_utf8_not_escaped(tmp_path / name, NON_ASCII_MARKER)

import json
from pathlib import Path

from typer.testing import CliRunner

from ai_workflow_builder.cli import app


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

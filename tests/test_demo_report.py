from pathlib import Path

from typer.testing import CliRunner

from ai_workflow_builder.cli import app

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "examples" / "synthetic_demo_report.md"


def _canonical(data: bytes) -> bytes:
    """Canonicalize line endings so Windows CRLF output compares equal to the LF fixture."""
    return data.replace(b"\r\n", b"\n")


def test_demo_report_matches_committed_fixture(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["demo", "-o", str(tmp_path)])

    assert result.exit_code == 0, result.output

    generated = tmp_path / "report.md"
    assert generated.exists()

    assert _canonical(generated.read_bytes()) == _canonical(FIXTURE_PATH.read_bytes())

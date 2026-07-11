from pathlib import Path

from typer.testing import CliRunner

from ai_workflow_builder.cli import app

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "examples" / "synthetic_demo_report.md"
ARTIFACTS = ("insights.json", "validation_issues.json", "review_queue.json", "report.md")


def _run_demo(output_dir: Path) -> None:
    result = CliRunner().invoke(app, ["demo", "-o", str(output_dir)])
    assert result.exit_code == 0, result.output


def test_demo_report_matches_committed_fixture_raw_bytes(tmp_path: Path) -> None:
    _run_demo(tmp_path)

    generated = tmp_path / "report.md"
    assert generated.exists()

    raw = generated.read_bytes()
    # Raw byte equality: no CRLF/LF canonicalization or text-mode normalization here.
    assert raw == FIXTURE_PATH.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "report.md must have no UTF-8 BOM"
    assert b"\r" not in raw, "report.md must use LF newlines only"
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n"), "report.md needs exactly one final LF"


def test_two_demo_runs_are_byte_identical(tmp_path: Path) -> None:
    run_a = tmp_path / "run_a"
    run_b = tmp_path / "run_b"
    _run_demo(run_a)
    _run_demo(run_b)

    for name in ARTIFACTS:
        assert (run_a / name).read_bytes() == (run_b / name).read_bytes(), (
            f"{name} must be byte-identical across isolated demo runs"
        )

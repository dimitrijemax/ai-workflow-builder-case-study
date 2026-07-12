from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

import ai_workflow_builder.evaluation as evaluation
from ai_workflow_builder.pipeline import run_pipeline, write_batch_report
from ai_workflow_builder.report import write_markdown_report
from ai_workflow_builder.review import load_review_queue, set_review_status

app = typer.Typer(help="Offline AI workflow builder case-study CLI.")
review_app = typer.Typer(help="Human review queue commands.")
app.add_typer(review_app, name="review")

EXAMPLE_NOTES_PATH = Path(__file__).resolve().parents[2] / "examples" / "synthetic_ops_notes.json"

# Errors expected from a malformed corpus, gates file, or fixture on disk; distinct from a
# genuinely unexpected software failure, which must map to exit 3, never exit 2. Mapped to a
# fixed, sanitized message per type below -- never the raw exception text, which can embed
# absolute local paths (OSError) or raw internal field values (ValidationError).
_EXPECTED_EVAL_ERRORS = (evaluation.CorpusError, ValidationError, OSError, json.JSONDecodeError)
_SANITIZED_EVAL_ERROR_MESSAGES: dict[type[Exception], str] = {
    evaluation.CorpusError: "The evaluation corpus does not match the approved, frozen fixtures.",
    ValidationError: "The evaluation corpus or gates file failed strict schema validation.",
    json.JSONDecodeError: "The evaluation gates or corpus file is not valid JSON.",
    OSError: "The evaluation corpus or gates file could not be read.",
}

# Fixed, sanitized diagnostics. None of these ever interpolate a raw exception message, a
# user-supplied value, or a local path.
_INVALID_FORMAT_MESSAGE = "Error: invalid output format; choose 'markdown' or 'json'."
_DETERMINISM_FAILURE_MESSAGE = "Error: evidence failed the determinism check."
_PRIVACY_FAILURE_MESSAGE = "Error: evidence failed the privacy check."
_INTERNAL_ERROR_MESSAGE = "Internal command error."


def _sanitized_eval_error_message(exc: Exception) -> str:
    for exc_type, message in _SANITIZED_EVAL_ERROR_MESSAGES.items():
        if isinstance(exc, exc_type):
            return message
    return "The evaluation input is invalid or unavailable."


def _write_bytes_atomically(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` atomically: a crash or interruption mid-write leaves any
    pre-existing file at ``path`` untouched, never partially overwritten."""
    directory = path.parent if str(path.parent) else Path()
    fd, tmp_name = tempfile.mkstemp(dir=str(directory), prefix=f".{path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _emit(content: str, output: Path | None) -> None:
    if output is not None:
        _write_bytes_atomically(output, content.encode("utf-8"))
    else:
        # content already ends with exactly one LF (see render_json/render_markdown);
        # nl=False avoids typer.echo appending a second trailing newline.
        typer.echo(content, nl=False)


@app.command()
def analyze(
    input_path: Annotated[Path, typer.Argument(exists=True, readable=True)],
    output_dir: Annotated[Path, typer.Option("--output-dir", "-o")] = Path("out"),
) -> None:
    """Analyze synthetic operations notes and write insights plus review queue files."""
    batch = run_pipeline(input_path)
    write_batch_report(batch, output_dir)
    typer.echo(f"Wrote {len(batch.insights)} insights to {output_dir}")
    typer.echo(f"Queued {len(batch.queued_for_review)} items for human review")


@app.command()
def report(
    output_dir: Annotated[Path, typer.Option("--output-dir", "-o")] = Path("out"),
    report_path: Annotated[Path | None, typer.Option("--report-path")] = None,
) -> None:
    """Build an operational markdown report from approved insights."""
    path = write_markdown_report(output_dir, report_path=report_path)
    typer.echo(f"Wrote report to {path}")


@app.command()
def demo(
    output_dir: Annotated[Path, typer.Option("--output-dir", "-o")] = Path("out/demo"),
) -> None:
    """Run the full offline demo on bundled synthetic operations notes."""
    if not EXAMPLE_NOTES_PATH.exists():
        raise typer.BadParameter(f"Bundled example notes not found: {EXAMPLE_NOTES_PATH}")
    batch = run_pipeline(EXAMPLE_NOTES_PATH)
    write_batch_report(batch, output_dir)
    report_path = write_markdown_report(output_dir)
    typer.echo("Offline demo complete")
    typer.echo(f"Insights: {len(batch.insights)}")
    typer.echo(f"Queued for review: {len(batch.queued_for_review)}")
    typer.echo(f"Report: {report_path}")


@review_app.command("list")
def list_review_items(
    output_dir: Annotated[Path, typer.Option("--output-dir", "-o")] = Path("out"),
) -> None:
    """List pending and completed review items."""
    queue = load_review_queue(output_dir)
    if not queue:
        typer.echo("Review queue is empty")
        return
    for item in queue:
        issue_codes = ", ".join(issue.code for issue in item.issues)
        typer.echo(f"{item.insight.note_id} [{item.status}] {issue_codes}")


@review_app.command()
def approve(
    note_id: str,
    output_dir: Annotated[Path, typer.Option("--output-dir", "-o")] = Path("out"),
) -> None:
    """Approve a queued insight for reporting."""
    item = set_review_status(output_dir, note_id, "approved")
    typer.echo(f"Approved {item.insight.note_id}")


@review_app.command()
def reject(
    note_id: str,
    output_dir: Annotated[Path, typer.Option("--output-dir", "-o")] = Path("out"),
) -> None:
    """Reject a queued insight from the reportable set."""
    item = set_review_status(output_dir, note_id, "rejected")
    typer.echo(f"Rejected {item.insight.note_id}")


@app.command(name="eval")
def eval_command(
    format: Annotated[str, typer.Option("--format")] = "markdown",
    output: Annotated[Path | None, typer.Option("--output")] = None,
    check: Annotated[bool, typer.Option("--check")] = False,
) -> None:
    """Render deterministic pipeline/rubric evaluation evidence against the approved gates.

    Exit codes: 0 completed (all requested checks passing, or ``--check`` not requested);
    1 a completed evaluation whose ``--check`` quality gates failed (including a determinism
    or privacy match detected at the evidence boundary); 2 an expected input, fixture,
    configuration, or contract failure; 3 an unexpected software failure.

    ``--check`` verifies at the evidence boundary: two independent evaluation passes are
    rendered and their exact bytes compared (never claiming determinism from matching
    intermediate Python structures alone), and the exact bytes that would be emitted are
    privacy-scanned alongside the fixtures, gates, README, and tracked source -- never a
    freshly, separately rendered copy. A failure on either check is never emitted or written.
    """
    if format not in ("markdown", "json"):
        typer.echo(_INVALID_FORMAT_MESSAGE, err=True)
        raise typer.Exit(code=2)

    if check:
        try:
            verification = evaluation.produce_verified_evidence()
        except _EXPECTED_EVAL_ERRORS as exc:
            typer.echo(f"Error: {_sanitized_eval_error_message(exc)}", err=True)
            raise typer.Exit(code=2) from None

        if not verification.determinism_ok:
            typer.echo(_DETERMINISM_FAILURE_MESSAGE, err=True)
            raise typer.Exit(code=1)
        if not verification.privacy_ok:
            typer.echo(_PRIVACY_FAILURE_MESSAGE, err=True)
            raise typer.Exit(code=1)

        content = verification.json_text if format == "json" else verification.markdown
        _emit(content, output)

        if not verification.output.all_gates_passed:
            raise typer.Exit(code=1)
        return

    try:
        result = evaluation.evaluate()
    except _EXPECTED_EVAL_ERRORS as exc:
        typer.echo(f"Error: {_sanitized_eval_error_message(exc)}", err=True)
        raise typer.Exit(code=2) from None

    if format == "json":
        content = evaluation.render_json(result)
    else:
        content = evaluation.render_markdown(result)
    _emit(content, output)


def main() -> None:
    """Console-script entry point. Maps command completion/exceptions to exit codes 0/1/2/3.

    ``typer.Exit`` raised anywhere inside a command is converted by Click's non-standalone
    handling into a *returned* exit code, not a raised exception -- so a deliberate exit 1
    (quality-gate failure) or exit 2 (input/contract failure) surfaces through the ``else``
    branch below. Only a genuinely unexpected exception reaches ``except Exception``, and is
    mapped to exit 3 -- it can never be misreported as exit 1. The fixed diagnostic below is
    printed so exit 3 is never silent, and never includes the exception type, message, or a
    traceback, any of which could embed raw values or local paths.

    Also forces UTF-8/LF stdout and stderr: the platform default stream encoding (e.g. a
    non-UTF-8 Windows console codepage) can otherwise silently drop non-ASCII evidence
    characters and translate LF to CRLF at the real OS pipe/console boundary.
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", newline="\n")
    try:
        code = app(standalone_mode=False)
    except Exception:
        typer.echo(_INTERNAL_ERROR_MESSAGE, err=True)
        raise SystemExit(3) from None
    else:
        raise SystemExit(code if isinstance(code, int) else 0)

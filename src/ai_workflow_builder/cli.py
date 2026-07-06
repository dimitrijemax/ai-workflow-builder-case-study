from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ai_workflow_builder.pipeline import run_pipeline, write_batch_report
from ai_workflow_builder.report import write_markdown_report
from ai_workflow_builder.review import load_review_queue, set_review_status

app = typer.Typer(help="Offline AI workflow builder case-study CLI.")
review_app = typer.Typer(help="Human review queue commands.")
app.add_typer(review_app, name="review")

EXAMPLE_NOTES_PATH = Path(__file__).resolve().parents[2] / "examples" / "synthetic_ops_notes.json"


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

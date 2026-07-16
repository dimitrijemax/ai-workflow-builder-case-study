from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path

EXPLORER_DIR = Path(__file__).resolve().parent
REPO_ROOT = EXPLORER_DIR.parents[1]
if str(EXPLORER_DIR) not in sys.path:
    sys.path.insert(0, str(EXPLORER_DIR))

from model import (  # noqa: E402
    BuildTrace,
    EvaluationSuite,
    EvidencePointer,
    ExplorerModel,
    HistoricalIssue,
    HistoricalPullRequest,
    RunSummary,
    RunTrace,
    TraceEdge,
    TraceNode,
)
from render import render_html  # noqa: E402

from ai_workflow_builder.evaluation import evaluate, scan_privacy_violations  # noqa: E402
from ai_workflow_builder.pipeline import load_ops_notes, run_pipeline  # noqa: E402
from ai_workflow_builder.schemas import BatchReport, OpsNote  # noqa: E402

DEFAULT_NOTE_ID = "N-1004"
DEFAULT_OUTPUT_PATH = EXPLORER_DIR / "index.html"
ADAPTER_SOURCE_PATHS = (
    "examples/synthetic_ops_notes.json",
    "docs/AGENT_PILOT.md",
    "docs/workflow-explorer/data/build_trace.json",
    "evals/pipeline_cases.json",
    "evals/rubric_cases.json",
    "evals/gates.json",
    "docs/workflow-explorer/template.html",
)

_STATE_FLOW_PATTERN = re.compile(
    r"^## State Flow\s+```text\s+(?P<flow>.*?)\s+```",
    flags=re.MULTILINE | re.DOTALL,
)


def _pointer(label: str, path: str) -> EvidencePointer:
    return EvidencePointer(label=label, path=path, href=f"../../{path}")


def _trace_nodes(
    note: OpsNote,
    category: str,
    sentiment: str,
    confidence: float,
    issue_codes: tuple[str, ...],
) -> tuple[TraceNode, ...]:
    requires_review = bool(issue_codes)
    validator_status = "needs_review" if requires_review else "passed"
    gate_status = "needs_review" if requires_review else "passed"
    outcome_status = "pending" if requires_review else "passed"
    validator_detail = (
        f"Validation emitted: {', '.join(issue_codes)}."
        if issue_codes
        else "Validation emitted no issues."
    )
    gate_detail = (
        "The insight waits for a human approval or rejection."
        if requires_review
        else "No review item was created; the insight may enter the report."
    )
    outcome_detail = (
        "Pending items remain outside Included Insights."
        if requires_review
        else "The auto-passed insight is eligible for Included Insights."
    )
    return (
        TraceNode(
            node_id="input",
            label="Synthetic note",
            kind="input",
            status="passed",
            detail=f"{note.id} loaded from the committed {note.channel.value} fixture.",
            evidence=(_pointer("Canonical synthetic input", "examples/synthetic_ops_notes.json"),),
        ),
        TraceNode(
            node_id="provider",
            label="Deterministic provider",
            kind="transform",
            status="passed",
            detail=(
                f"Produced {category}, {sentiment}, confidence {confidence:.2f} "
                "without a model call."
            ),
            evidence=(_pointer("Rule-based extraction", "src/ai_workflow_builder/providers.py"),),
        ),
        TraceNode(
            node_id="contract",
            label="OpsInsight contract",
            kind="contract",
            status="passed",
            detail="The provider payload passed the strict Pydantic OpsInsight contract.",
            evidence=(
                _pointer("Pydantic schemas", "src/ai_workflow_builder/schemas.py"),
                _pointer("Pipeline validation boundary", "src/ai_workflow_builder/pipeline.py"),
            ),
        ),
        TraceNode(
            node_id="validator",
            label="Rubric checks",
            kind="check",
            status=validator_status,
            detail=validator_detail,
            evidence=(_pointer("Validator rules", "src/ai_workflow_builder/validators.py"),),
        ),
        TraceNode(
            node_id="review_gate",
            label="Human-review gate",
            kind="gate",
            status=gate_status,
            detail=gate_detail,
            evidence=(_pointer("Review queue construction", "src/ai_workflow_builder/review.py"),),
        ),
        TraceNode(
            node_id="outcome",
            label="Report outcome",
            kind="output",
            status=outcome_status,
            detail=outcome_detail,
            evidence=(
                _pointer("Report inclusion semantics", "src/ai_workflow_builder/report.py"),
                _pointer("Committed reference report", "examples/synthetic_demo_report.md"),
            ),
        ),
    )


def _trace_edges(requires_review: bool) -> tuple[TraceEdge, ...]:
    routing_kind = "review" if requires_review else "normal"
    routing_label = "issues require human review" if requires_review else "no issues"
    return (
        TraceEdge("input", "provider", "normal", "load note"),
        TraceEdge("provider", "contract", "normal", "validate payload shape"),
        TraceEdge("contract", "validator", "normal", "run rubric checks"),
        TraceEdge("validator", "review_gate", routing_kind, routing_label),
        TraceEdge("review_gate", "outcome", routing_kind, "enforce report boundary"),
    )


def build_run_traces(
    notes: list[OpsNote],
    batch: BatchReport,
) -> tuple[tuple[RunTrace, ...], RunSummary]:
    notes_by_id = {note.id: note for note in notes}
    insights_by_id = {insight.note_id: insight for insight in batch.insights}
    if set(notes_by_id) != set(insights_by_id):
        raise ValueError("Pipeline note IDs and insight IDs must match exactly.")

    issues_by_note = {
        item.insight.note_id: tuple(sorted(issue.code for issue in item.issues))
        for item in batch.queued_for_review
    }
    traces: list[RunTrace] = []
    for note_id in sorted(notes_by_id):
        note = notes_by_id[note_id]
        insight = insights_by_id[note_id]
        issue_codes = issues_by_note.get(note_id, ())
        requires_review = bool(issue_codes)
        traces.append(
            RunTrace(
                note_id=note_id,
                channel=note.channel.value,
                category=insight.category.value,
                sentiment=insight.sentiment.value,
                confidence=insight.confidence,
                requires_review=requires_review,
                status="needs_review" if requires_review else "passed",
                stop_reason=", ".join(issue_codes)
                if issue_codes
                else "None; validation produced no issues.",
                next_gate=(
                    "Human approval or rejection"
                    if requires_review
                    else "Automatic report inclusion"
                ),
                outcome="Pending human review" if requires_review else "Included insight",
                nodes=_trace_nodes(
                    note,
                    insight.category.value,
                    insight.sentiment.value,
                    insight.confidence,
                    issue_codes,
                ),
                edges=_trace_edges(requires_review),
            )
        )

    pending_review = sum(trace.requires_review for trace in traces)
    summary = RunSummary(
        total=len(traces),
        auto_passed=len(traces) - pending_review,
        pending_review=pending_review,
    )
    return tuple(traces), summary


def extract_state_flow(document: str) -> tuple[str, ...]:
    match = _STATE_FLOW_PATTERN.search(document)
    if match is None:
        raise ValueError("docs/AGENT_PILOT.md is missing the fenced State Flow block.")
    flow_lines = [line.strip() for line in match.group("flow").splitlines() if line.strip()]
    steps: list[str] = []
    for index, line in enumerate(flow_lines):
        if index == 0:
            steps.append(line)
        elif line.startswith("-> "):
            steps.append(line.removeprefix("-> "))
        else:
            raise ValueError("State Flow lines after the first must start with '-> '.")
    if len(steps) < 2:
        raise ValueError("State Flow must contain at least two steps.")
    return tuple(steps)


def _load_build_trace(path: Path) -> BuildTrace:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if set(payload) != {"issue", "pull_request"}:
        raise ValueError("Historical BUILD trace must contain only issue and pull_request.")
    issue = payload["issue"]
    pull_request = payload["pull_request"]
    if set(issue) != {"number", "state", "url"}:
        raise ValueError("Historical issue evidence has an unexpected field.")
    expected_pr_fields = {"number", "state", "url", "head_sha", "merge_sha"}
    if set(pull_request) != expected_pr_fields:
        raise ValueError("Historical pull-request evidence has an unexpected field.")
    if issue["state"] != "closed" or pull_request["state"] != "merged":
        raise ValueError("Historical BUILD evidence must contain terminal states.")
    return BuildTrace(
        issue=HistoricalIssue(**issue),
        pull_request=HistoricalPullRequest(**pull_request),
    )


def _evaluation_suites(repo_root: Path) -> tuple[EvaluationSuite, ...]:
    output = evaluate(
        repo_root / "evals" / "pipeline_cases.json",
        repo_root / "evals" / "rubric_cases.json",
        repo_root / "evals" / "gates.json",
    )
    return (
        EvaluationSuite(
            suite_id="A",
            label="Pipeline conformance",
            correct=output.pipeline.case_count - output.pipeline.failure_count,
            total=output.pipeline.case_count,
            evidence_path="evals/pipeline_cases.json",
            statement=(
                "Provider, contract, routing, and validator behavior are checked against authored "
                "synthetic expectations."
            ),
        ),
        EvaluationSuite(
            suite_id="B",
            label="Validator-rubric behavior",
            correct=output.rubric.case_count - output.rubric.failure_count,
            total=output.rubric.case_count,
            evidence_path="evals/rubric_cases.json",
            statement=(
                "Validator issue sets are checked independently from provider behavior on a "
                "separate authored synthetic rubric."
            ),
        ),
    )


def build_model(repo_root: Path = REPO_ROOT) -> ExplorerModel:
    notes_path = repo_root / "examples" / "synthetic_ops_notes.json"
    notes = load_ops_notes(notes_path)
    batch = run_pipeline(notes_path)
    run_traces, run_summary = build_run_traces(notes, batch)
    if DEFAULT_NOTE_ID not in {trace.note_id for trace in run_traces}:
        raise ValueError("The required default note is missing from the canonical input.")

    pilot_path = repo_root / "docs" / "AGENT_PILOT.md"
    build_steps = extract_state_flow(pilot_path.read_text(encoding="utf-8"))
    build_trace = _load_build_trace(
        repo_root / "docs" / "workflow-explorer" / "data" / "build_trace.json"
    )
    return ExplorerModel(
        default_note_id=DEFAULT_NOTE_ID,
        run_summary=run_summary,
        run_traces=run_traces,
        build_source="docs/AGENT_PILOT.md",
        build_steps=build_steps,
        build_trace=build_trace,
        evaluation_suites=_evaluation_suites(repo_root),
    )


def iter_adapter_source_texts(repo_root: Path = REPO_ROOT) -> tuple[tuple[str, str], ...]:
    sources: list[tuple[str, str]] = []
    for relative in ADAPTER_SOURCE_PATHS:
        text = (repo_root / relative).read_text(encoding="utf-8")
        if relative == "docs/AGENT_PILOT.md":
            match = _STATE_FLOW_PATTERN.search(text)
            if match is None:
                raise ValueError("docs/AGENT_PILOT.md is missing the fenced State Flow block.")
            sources.append((f"{relative}#State Flow", match.group("flow")))
        else:
            sources.append((relative, text))
    return tuple(sources)


def _assert_public_texts_safe(source_texts: Iterable[tuple[str, str]], rendered: str) -> None:
    for _label, text in source_texts:
        if scan_privacy_violations(text):
            raise ValueError("Workflow Explorer privacy scan failed for a consumed source.")
    if scan_privacy_violations(rendered):
        raise ValueError("Workflow Explorer privacy scan failed for generated HTML.")


def assert_public_safe(source_paths: Iterable[Path], rendered: str) -> None:
    ordered_paths = sorted((Path(path) for path in source_paths), key=lambda path: path.as_posix())
    source_texts = tuple(
        (path.as_posix(), path.read_text(encoding="utf-8")) for path in ordered_paths
    )
    _assert_public_texts_safe(source_texts, rendered)


def build_html(repo_root: Path = REPO_ROOT) -> str:
    template_path = repo_root / "docs" / "workflow-explorer" / "template.html"
    template = template_path.read_text(encoding="utf-8")
    rendered = render_html(build_model(repo_root), template)
    _assert_public_texts_safe(iter_adapter_source_texts(repo_root), rendered)
    return rendered


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the deterministic offline Workflow Explorer."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if the target file is absent or differs from a fresh deterministic build.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        rendered = build_html()
    except (OSError, ValueError, json.JSONDecodeError):
        print("Error: Workflow Explorer build contract failed.", file=sys.stderr)
        return 2

    expected = rendered.encode("utf-8")
    if args.check:
        if not args.output.is_file() or args.output.read_bytes() != expected:
            print("Error: Workflow Explorer artifact is stale.", file=sys.stderr)
            return 1
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

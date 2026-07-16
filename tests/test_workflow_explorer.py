from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from types import ModuleType

import pytest

from ai_workflow_builder.evaluation import (
    GENERIC_PRIVACY_PATTERNS,
    scan_privacy_violations,
)
from ai_workflow_builder.pipeline import load_ops_notes, run_pipeline
from ai_workflow_builder.schemas import BatchReport

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPLORER_DIR = REPO_ROOT / "docs" / "workflow-explorer"
BUILD_SCRIPT = EXPLORER_DIR / "build.py"
INDEX_PATH = EXPLORER_DIR / "index.html"
README_PATH = EXPLORER_DIR / "README.md"
BUILD_TRACE_PATH = EXPLORER_DIR / "data" / "build_trace.json"

EXPECTED_NODE_KINDS = ("input", "transform", "contract", "check", "gate", "output")
EXPECTED_STATUSES = (
    "pending",
    "passed",
    "needs_review",
    "approved",
    "rejected",
    "blocked_owner",
)
EXPECTED_EDGE_KINDS = ("normal", "review", "reject", "audit")
EXPECTED_ADAPTER_SOURCES = (
    "examples/synthetic_ops_notes.json",
    "docs/AGENT_PILOT.md",
    "docs/workflow-explorer/data/build_trace.json",
    "evals/pipeline_cases.json",
    "evals/rubric_cases.json",
    "evals/gates.json",
    "docs/workflow-explorer/template.html",
)
SYNTHETIC_LEASE_DATE = "2026" + "-07-10"


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def explorer_modules() -> tuple[ModuleType, ModuleType]:
    sys.path.insert(0, str(EXPLORER_DIR))
    try:
        model = _load_module("workflow_explorer_model", EXPLORER_DIR / "model.py")
        build = _load_module("workflow_explorer_build", BUILD_SCRIPT)
    finally:
        sys.path.remove(str(EXPLORER_DIR))
    return model, build


def test_visual_vocabulary_is_documented_and_machine_checked(explorer_modules) -> None:
    model_module, _ = explorer_modules
    readme = README_PATH.read_text(encoding="utf-8")

    assert model_module.NODE_KINDS == EXPECTED_NODE_KINDS
    assert model_module.STATUSES == EXPECTED_STATUSES
    assert model_module.EDGE_KINDS == EXPECTED_EDGE_KINDS
    for value in (*EXPECTED_NODE_KINDS, *EXPECTED_STATUSES, *EXPECTED_EDGE_KINDS):
        assert f"`{value}`" in readme


def test_run_model_is_derived_from_the_canonical_pipeline(explorer_modules) -> None:
    _, build = explorer_modules
    explorer = build.build_model()
    traces = {trace.note_id: trace for trace in explorer.run_traces}

    assert explorer.default_note_id == "N-1004"
    assert list(traces) == [f"N-{number}" for number in range(1001, 1011)]
    assert explorer.run_summary.total == 10
    assert explorer.run_summary.auto_passed == 8
    assert explorer.run_summary.pending_review == 2
    assert {trace.note_id for trace in explorer.run_traces if trace.requires_review} == {
        "N-1004",
        "N-1008",
    }
    assert "generated_at" not in json.dumps(asdict(explorer), sort_keys=True)


def test_run_counts_are_not_a_second_manual_status_source(explorer_modules) -> None:
    _, build = explorer_modules
    notes = load_ops_notes(REPO_ROOT / "examples" / "synthetic_ops_notes.json")
    batch = run_pipeline(REPO_ROOT / "examples" / "synthetic_ops_notes.json")
    one_note_batch = BatchReport(
        generated_at=batch.generated_at,
        insights=batch.insights[:1],
        issues=[],
        queued_for_review=[],
    )

    traces, summary = build.build_run_traces(notes[:1], one_note_batch)

    assert len(traces) == 1
    assert summary.total == 1
    assert summary.auto_passed == 1
    assert summary.pending_review == 0


def test_auto_pass_and_pending_review_paths_are_auditable(explorer_modules) -> None:
    _, build = explorer_modules
    traces = {trace.note_id: trace for trace in build.build_model().run_traces}

    auto_pass = traces["N-1001"]
    pending = traces["N-1004"]
    assert [node.kind for node in auto_pass.nodes] == list(EXPECTED_NODE_KINDS)
    assert [node.kind for node in pending.nodes] == list(EXPECTED_NODE_KINDS)
    assert auto_pass.status == "passed"
    assert auto_pass.stop_reason == "None; validation produced no issues."
    assert auto_pass.next_gate == "Automatic report inclusion"
    assert auto_pass.outcome == "Included insight"
    assert pending.status == "needs_review"
    assert pending.stop_reason == "low_confidence"
    assert pending.next_gate == "Human approval or rejection"
    assert pending.outcome == "Pending human review"
    assert any(edge.kind == "review" for edge in pending.edges)

    for trace in (auto_pass, pending):
        for node in trace.nodes:
            assert node.kind in EXPECTED_NODE_KINDS
            assert node.status in EXPECTED_STATUSES
            for pointer in node.evidence:
                assert not Path(pointer.path).is_absolute()
                assert (REPO_ROOT / pointer.path).is_file()


def test_build_view_uses_canonical_process_and_completed_snapshot(explorer_modules) -> None:
    _, build = explorer_modules
    explorer = build.build_model()

    assert explorer.build_source == "docs/AGENT_PILOT.md"
    assert explorer.build_steps == (
        "Next",
        "Ready",
        "Codex preflight",
        "Owner plan approval",
        "Builder writing",
        "Builder handoff",
        "Deterministic verification",
        "Codex review",
        "Same-builder fixes, if blocking",
        "Ready for PR",
        "Owner acceptance",
    )
    assert explorer.build_trace.issue.number == 9
    assert explorer.build_trace.issue.state == "closed"
    assert explorer.build_trace.pull_request.number == 10
    assert explorer.build_trace.pull_request.state == "merged"


def test_build_trace_is_bounded_immutable_historical_evidence() -> None:
    payload = json.loads(BUILD_TRACE_PATH.read_text(encoding="utf-8"))
    text = json.dumps(payload, sort_keys=True).lower()

    assert set(payload) == {"issue", "pull_request"}
    assert set(payload["issue"]) == {"number", "state", "url"}
    assert set(payload["pull_request"]) == {
        "number",
        "state",
        "url",
        "head_sha",
        "merge_sha",
    }
    assert payload["issue"]["number"] == 9
    assert payload["issue"]["state"] == "closed"
    assert payload["pull_request"]["number"] == 10
    assert payload["pull_request"]["state"] == "merged"
    assert len(payload["pull_request"]["head_sha"]) == 40
    assert len(payload["pull_request"]["merge_sha"]) == 40
    for forbidden in ("progress", "percentage", "writer", "checklist", "current_state"):
        assert forbidden not in text


def test_evaluation_suites_remain_separate(explorer_modules) -> None:
    _, build = explorer_modules
    suites = build.build_model().evaluation_suites

    assert [(suite.suite_id, suite.correct, suite.total) for suite in suites] == [
        ("A", 12, 12),
        ("B", 6, 6),
    ]
    assert all(suite.correct <= suite.total for suite in suites)
    assert "combined_score" not in json.dumps([asdict(suite) for suite in suites])


def test_generated_html_is_offline_static_and_accessible(explorer_modules) -> None:
    _, build = explorer_modules
    html = build.build_html()

    assert html.count('class="run-trace"') == 10
    assert '<details class="run-trace" data-note-id="N-1004" open>' in html
    assert '<option value="N-1004" selected>' in html
    assert '<select id="note-selector"' in html
    assert "<noscript>" in html
    assert 'aria-live="polite"' in html
    assert "Status meaning" in html
    assert "@media (max-width: 736px)" in html
    assert "@media (max-width: 320px)" in html
    assert "<script src=" not in html
    assert '<link rel="stylesheet"' not in html
    assert "fetch(" not in html
    assert "XMLHttpRequest" not in html
    assert "WebSocket" not in html
    assert "Suite A — Pipeline conformance" in html
    assert "Suite B — Validator-rubric behavior" in html
    assert "12 of 12" in html
    assert "6 of 6" in html
    assert "No combined cross-suite score" in html
    assert 'href="../../evals/pipeline_cases.json">Evidence: evals/pipeline_cases.json</a>' in html
    assert 'href="../../evals/rubric_cases.json">Evidence: evals/rubric_cases.json</a>' in html
    assert '<span class="status-badge status-needs_review">status: needs_review</span>' in html
    assert ".status-passed .status-badge, summary .status-badge" not in (
        EXPLORER_DIR / "template.html"
    ).read_text(encoding="utf-8")


def test_two_builds_are_byte_identical_and_committed_artifact_is_fresh(
    explorer_modules,
) -> None:
    _, build = explorer_modules
    first = build.build_html().encode("utf-8")
    second = build.build_html().encode("utf-8")

    assert first == second
    assert first == INDEX_PATH.read_bytes()
    assert not first.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in first
    assert first.endswith(b"\n") and not first.endswith(b"\n\n")


def test_build_cli_output_and_stale_check(tmp_path: Path) -> None:
    output = tmp_path / "explorer.html"
    build_result = subprocess.run(
        [sys.executable, str(BUILD_SCRIPT), "--output", str(output)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert build_result.returncode == 0, build_result.stderr
    original = output.read_bytes()

    check_result = subprocess.run(
        [sys.executable, str(BUILD_SCRIPT), "--output", str(output), "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert check_result.returncode == 0, check_result.stderr

    output.write_bytes(original + b"stale")
    stale = subprocess.run(
        [sys.executable, str(BUILD_SCRIPT), "--output", str(output), "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert stale.returncode == 1
    assert output.read_bytes() == original + b"stale"


def test_every_adapter_source_and_generated_artifact_is_privacy_scanned(
    explorer_modules,
) -> None:
    _, build = explorer_modules
    assert build.ADAPTER_SOURCE_PATHS == EXPECTED_ADAPTER_SOURCES

    consumed_sources = build.iter_adapter_source_texts()
    assert len(consumed_sources) == len(EXPECTED_ADAPTER_SOURCES)
    for _label, text in consumed_sources:
        assert scan_privacy_violations(text) == 0
        assert all(pattern.search(text) is None for pattern in GENERIC_PRIVACY_PATTERNS.values())

    pilot_text = (REPO_ROOT / "docs" / "AGENT_PILOT.md").read_text(encoding="utf-8")
    pilot_matches = [
        match.group(0)
        for pattern in GENERIC_PRIVACY_PATTERNS.values()
        for match in pattern.finditer(pilot_text)
    ]
    assert pilot_matches == [SYNTHETIC_LEASE_DATE, SYNTHETIC_LEASE_DATE]

    generated = build.build_html()
    assert scan_privacy_violations(generated) == 0
    assert all(pattern.search(generated) is None for pattern in GENERIC_PRIVACY_PATTERNS.values())


def test_explorer_privacy_poison_blocks_generation(explorer_modules, tmp_path: Path) -> None:
    _, build = explorer_modules
    poison = "workflow-explorer-poison" + chr(64) + "example.invalid"
    poisoned_source = tmp_path / "poisoned.txt"
    poisoned_source.write_text(f"synthetic poison marker: {poison}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="privacy scan failed"):
        build.assert_public_safe((poisoned_source,), "<html></html>\n")


def test_gitignore_reincludes_only_the_required_build_trace() -> None:
    lines = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    data_index = lines.index("data/")

    assert lines[data_index + 1 : data_index + 3] == [
        "!docs/workflow-explorer/data/",
        "!docs/workflow-explorer/data/build_trace.json",
    ]
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "docs/workflow-explorer/data/build_trace.json"],
        cwd=REPO_ROOT,
    )
    assert ignored.returncode == 1

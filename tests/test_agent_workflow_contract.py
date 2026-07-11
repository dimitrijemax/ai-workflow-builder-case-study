from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_repo_file(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_coding_task_form_keeps_required_contract_fields() -> None:
    issue_form = read_repo_file(".github/ISSUE_TEMPLATE/coding-task.yml")

    required_labels = [
        "Task state",
        "Risk lane",
        "Analyst",
        "Builder",
        "Verifier",
        "Reviewer",
        "Outcome",
        "Acceptance criteria",
        "Allowed scope",
        "Non-goals and forbidden changes",
        "Verification plan",
        "Timebox",
        "Dependencies or blockers",
        "Workflow progress",
        "Public-safety confirmation",
    ]

    for label in required_labels:
        assert f"label: {label}" in issue_form

    assert "Claude Code" in issue_form
    assert "Codex (read-only)" in issue_form
    assert "- GitHub Actions only" not in issue_form
    assert "The observable result is ..." in issue_form
    assert "No secret enters the repository, CI, issue, or any agent context." in issue_form
    assert "uv run --locked pytest" in issue_form
    assert "uv run --locked ruff" in issue_form
    assert "blank_issues_enabled: false" in read_repo_file(".github/ISSUE_TEMPLATE/config.yml")


def test_pr_template_keeps_handoff_and_review_gates() -> None:
    template = read_repo_file(".github/pull_request_template.md")

    required_text = [
        "Closes #",
        "- Analyst: Codex",
        "- Builder: Claude Code",
        "- Reviewer: Codex",
        "## Builder handoff",
        "Handoff commit: `<40-character HEAD SHA>`",
        "Reviewed commit: `<40-character HEAD SHA>`",
        "Targeted tests passed",
        "Codex read-only review completed after builder handoff",
        "Staged scope matches the linked issue",
    ]

    for text in required_text:
        assert text in template


def test_task_state_workflow_mirrors_labels_and_rejects_a_second_ready_task() -> None:
    workflow = read_repo_file(".github/workflows/task-state.yml")

    required_text = [
        '"pilot:ready"',
        '"pilot:next"',
        '"pilot:conflict"',
        '"risk:l3"',
        '"builder:claude"',
        "Only one task may be Ready",
        "Junie as builder only for an L1 task",
        "queue: max",
        "issues.get",
        "safetyRequirements",
        "contractErrors",
    ]

    for text in required_text:
        assert text in workflow


def test_pr_contract_reads_the_linked_issue_and_enforces_ready_gates() -> None:
    workflow = read_repo_file(".github/workflows/pr-contract.yml")

    required_text = [
        "issues: read",
        'field(taskBody, "Task state")',
        'taskLabels.includes("pilot:ready")',
        'field(taskBody, "Public-safety confirmation")',
        'field(taskBody, "Workflow progress")',
        "PR builder matches linked issue",
        "Full lint and test suite passed locally",
        "linked issue is the only open pilot:ready task",
        "handoff commit matches current PR head",
        "reviewed commit matches current PR head",
        "non-empty handoff changed files",
        "linked issue has a substantive acceptance criterion",
        "Bootstrap exception: agent-pilot-v1",
        "allowedBootstrapFiles",
        "pr.head.repo.full_name",
        "file.previous_filename",
        "actions/github-script@v9",
    ]

    for text in required_text:
        assert text in workflow


def test_ci_passes_the_automatic_token_to_gitleaks() -> None:
    workflow = read_repo_file(".github/workflows/ci.yml")

    assert "gitleaks/gitleaks-action@v2" in workflow
    assert "GITHUB_" + "TOKEN" in workflow
    assert "secrets.GITHUB_" + "TOKEN" in workflow


def test_agent_rules_enforce_one_builder_and_explicit_git_boundary() -> None:
    rules = read_repo_file("AGENTS.md")
    normalized_rules = " ".join(rules.split())

    assert "one builder" in rules
    assert "If there is no accepted issue contract, stay read-only." in rules
    assert "without a separate explicit owner command" in normalized_rules
    assert "active -> handoff-ready -> released" in rules
    assert "locked dependency commands" in rules

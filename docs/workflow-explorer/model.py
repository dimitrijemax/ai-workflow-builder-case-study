from __future__ import annotations

from dataclasses import dataclass

NODE_KINDS = ("input", "transform", "contract", "check", "gate", "output")
STATUSES = (
    "pending",
    "passed",
    "needs_review",
    "approved",
    "rejected",
    "blocked_owner",
)
EDGE_KINDS = ("normal", "review", "reject", "audit")


@dataclass(frozen=True, slots=True)
class EvidencePointer:
    label: str
    path: str
    href: str

    def __post_init__(self) -> None:
        if not self.path or self.path.startswith(("/", "\\")) or ":" in self.path:
            raise ValueError("Evidence paths must be non-empty and repository-relative.")


@dataclass(frozen=True, slots=True)
class TraceNode:
    node_id: str
    label: str
    kind: str
    status: str
    detail: str
    evidence: tuple[EvidencePointer, ...]

    def __post_init__(self) -> None:
        if self.kind not in NODE_KINDS:
            raise ValueError(f"Unsupported node kind: {self.kind}")
        if self.status not in STATUSES:
            raise ValueError(f"Unsupported node status: {self.status}")


@dataclass(frozen=True, slots=True)
class TraceEdge:
    source: str
    target: str
    kind: str
    label: str

    def __post_init__(self) -> None:
        if self.kind not in EDGE_KINDS:
            raise ValueError(f"Unsupported edge kind: {self.kind}")


@dataclass(frozen=True, slots=True)
class RunTrace:
    note_id: str
    channel: str
    category: str
    sentiment: str
    confidence: float
    requires_review: bool
    status: str
    stop_reason: str
    next_gate: str
    outcome: str
    nodes: tuple[TraceNode, ...]
    edges: tuple[TraceEdge, ...]

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"Unsupported trace status: {self.status}")


@dataclass(frozen=True, slots=True)
class RunSummary:
    total: int
    auto_passed: int
    pending_review: int

    def __post_init__(self) -> None:
        if self.auto_passed + self.pending_review != self.total:
            raise ValueError("RUN summary counts must partition the total.")


@dataclass(frozen=True, slots=True)
class HistoricalIssue:
    number: int
    state: str
    url: str


@dataclass(frozen=True, slots=True)
class HistoricalPullRequest:
    number: int
    state: str
    url: str
    head_sha: str
    merge_sha: str

    def __post_init__(self) -> None:
        if len(self.head_sha) != 40 or len(self.merge_sha) != 40:
            raise ValueError("Historical evidence SHAs must be full 40-character values.")


@dataclass(frozen=True, slots=True)
class BuildTrace:
    issue: HistoricalIssue
    pull_request: HistoricalPullRequest


@dataclass(frozen=True, slots=True)
class EvaluationSuite:
    suite_id: str
    label: str
    correct: int
    total: int
    evidence_path: str
    statement: str

    def __post_init__(self) -> None:
        if self.suite_id not in {"A", "B"}:
            raise ValueError("Evaluation suite ID must be A or B.")
        if not 0 <= self.correct <= self.total:
            raise ValueError("Evaluation counts must satisfy 0 <= correct <= total.")


@dataclass(frozen=True, slots=True)
class ExplorerModel:
    default_note_id: str
    run_summary: RunSummary
    run_traces: tuple[RunTrace, ...]
    build_source: str
    build_steps: tuple[str, ...]
    build_trace: BuildTrace
    evaluation_suites: tuple[EvaluationSuite, ...]

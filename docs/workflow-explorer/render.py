from __future__ import annotations

from html import escape

from model import ExplorerModel, RunTrace, TraceEdge, TraceNode


def _render_options(model: ExplorerModel) -> str:
    lines: list[str] = []
    for trace in model.run_traces:
        selected = " selected" if trace.note_id == model.default_note_id else ""
        lines.append(
            f'<option value="{escape(trace.note_id)}"{selected}>'
            f"{escape(trace.note_id)} — {escape(trace.category)}</option>"
        )
    return "\n".join(lines)


def _render_evidence(node: TraceNode) -> str:
    lines = ['<ul class="evidence-list" aria-label="Evidence pointers">']
    for pointer in node.evidence:
        lines.append(
            "<li>"
            f'<a href="{escape(pointer.href)}"><code>{escape(pointer.path)}</code></a>'
            f"<span>{escape(pointer.label)}</span>"
            "</li>"
        )
    lines.append("</ul>")
    return "\n".join(lines)


def _render_node(node: TraceNode) -> str:
    return "\n".join(
        [
            (
                f'<article class="trace-node kind-{escape(node.kind)} '
                f'status-{escape(node.status)}" data-kind="{escape(node.kind)}" '
                f'data-status="{escape(node.status)}">'
            ),
            '<div class="node-heading">',
            f'<span class="node-shape" aria-hidden="true">{escape(node.kind[:1].upper())}</span>',
            "<div>",
            f'<p class="eyebrow">{escape(node.kind)}</p>',
            f"<h4>{escape(node.label)}</h4>",
            "</div>",
            f'<span class="status-badge">status: {escape(node.status)}</span>',
            "</div>",
            f"<p>{escape(node.detail)}</p>",
            _render_evidence(node),
            "</article>",
        ]
    )


def _render_edge(edge: TraceEdge) -> str:
    return (
        f'<li class="trace-edge edge-{escape(edge.kind)}">'
        f"<code>{escape(edge.source)}</code> "
        '<span aria-hidden="true">→</span> '
        f"<code>{escape(edge.target)}</code>"
        f'<span class="edge-label">edge: {escape(edge.kind)} · {escape(edge.label)}</span>'
        "</li>"
    )


def _render_trace(trace: RunTrace, default_note_id: str) -> str:
    open_attribute = " open" if trace.note_id == default_note_id else ""
    nodes = "\n".join(_render_node(node) for node in trace.nodes)
    edges = "\n".join(_render_edge(edge) for edge in trace.edges)
    review_label = "Human review required" if trace.requires_review else "Auto-pass route"
    return "\n".join(
        [
            (f'<details class="run-trace" data-note-id="{escape(trace.note_id)}"{open_attribute}>'),
            "<summary>",
            "<span>",
            f"<strong>{escape(trace.note_id)}</strong> · {escape(trace.category)}",
            f"<small>{escape(trace.channel)} · confidence {trace.confidence:.2f}</small>",
            "</span>",
            (
                f'<span class="status-badge status-{escape(trace.status)}">'
                f"status: {escape(trace.status)}</span>"
            ),
            "</summary>",
            '<div class="trace-facts">',
            f"<p><strong>Route</strong><span>{escape(review_label)}</span></p>",
            f"<p><strong>Stop reason</strong><span>{escape(trace.stop_reason)}</span></p>",
            f"<p><strong>Next gate</strong><span>{escape(trace.next_gate)}</span></p>",
            f"<p><strong>Outcome</strong><span>{escape(trace.outcome)}</span></p>",
            "</div>",
            '<div class="trace-grid" aria-label="Auditable workflow nodes">',
            nodes,
            "</div>",
            '<ol class="edge-list" aria-label="Workflow edges">',
            edges,
            "</ol>",
            "</details>",
        ]
    )


def _render_run_traces(model: ExplorerModel) -> str:
    return "\n".join(_render_trace(trace, model.default_note_id) for trace in model.run_traces)


def _render_build_steps(model: ExplorerModel) -> str:
    return "\n".join(
        f'<li><span class="step-index">{index:02d}</span><span>{escape(step)}</span></li>'
        for index, step in enumerate(model.build_steps, start=1)
    )


def _render_build_trace(model: ExplorerModel) -> str:
    issue = model.build_trace.issue
    pull_request = model.build_trace.pull_request
    return "\n".join(
        [
            '<article class="history-card">',
            '<p class="eyebrow">Immutable completed trace</p>',
            "<h3>Issue #9 → PR #10</h3>",
            '<div class="history-grid">',
            "<div>",
            "<span>Issue</span>",
            f'<a href="{escape(issue.url)}">#{issue.number}</a>',
            f"<strong>terminal state: {escape(issue.state)}</strong>",
            "</div>",
            "<div>",
            "<span>Pull request</span>",
            f'<a href="{escape(pull_request.url)}">#{pull_request.number}</a>',
            f"<strong>terminal state: {escape(pull_request.state)}</strong>",
            "</div>",
            "</div>",
            '<dl class="sha-list">',
            "<div><dt>Accepted head SHA</dt>"
            f"<dd><code>{escape(pull_request.head_sha)}</code></dd></div>",
            f"<div><dt>Merge SHA</dt><dd><code>{escape(pull_request.merge_sha)}</code></dd></div>",
            "</dl>",
            (
                "<p>This snapshot records completed public evidence only. "
                "It is not a live tracker.</p>"
            ),
            "</article>",
        ]
    )


def _render_evaluation_suites(model: ExplorerModel) -> str:
    lines: list[str] = []
    for suite in model.evaluation_suites:
        lines.extend(
            [
                f'<article class="suite-card suite-{escape(suite.suite_id.lower())}">',
                f'<p class="eyebrow">Suite {escape(suite.suite_id)}</p>',
                f"<h3>Suite {escape(suite.suite_id)} — {escape(suite.label)}</h3>",
                (
                    f'<p class="suite-count"><strong>{suite.correct} of {suite.total}</strong> '
                    "authored synthetic cases without observed mismatches</p>"
                ),
                f"<p>{escape(suite.statement)}</p>",
                (
                    f'<a class="text-link" href="../../{escape(suite.evidence_path)}">'
                    f"Evidence: {escape(suite.evidence_path)}</a>"
                ),
                "</article>",
            ]
        )
    return "\n".join(lines)


def render_html(model: ExplorerModel, template: str) -> str:
    replacements = {
        "{{DEFAULT_NOTE_ID}}": escape(model.default_note_id),
        "{{RUN_TOTAL}}": str(model.run_summary.total),
        "{{RUN_AUTO_PASSED}}": str(model.run_summary.auto_passed),
        "{{RUN_PENDING_REVIEW}}": str(model.run_summary.pending_review),
        "{{RUN_OPTIONS}}": _render_options(model),
        "{{RUN_TRACES}}": _render_run_traces(model),
        "{{BUILD_SOURCE}}": escape(model.build_source),
        "{{BUILD_STEPS}}": _render_build_steps(model),
        "{{BUILD_TRACE}}": _render_build_trace(model),
        "{{EVALUATION_SUITES}}": _render_evaluation_suites(model),
    }
    rendered = template
    for token in sorted(replacements):
        rendered = rendered.replace(token, replacements[token])
    if "{{" in rendered or "}}" in rendered:
        raise ValueError("Template contains an unresolved placeholder.")
    return rendered.rstrip("\r\n") + "\n"

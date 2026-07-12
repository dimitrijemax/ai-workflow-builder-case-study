"""Tests for the ``awb eval`` CLI: its Markdown/JSON/output-file/``--check`` forms and the
``0/1/2/3`` exit-code contract, now implemented and owner-approved. Former strict-xfail RED-
boundary markers were removed once each test genuinely passed against the real CLI.

The only approved ``awb eval`` CLI surface is ``awb eval``, ``awb eval --format markdown|json``,
``awb eval --output PATH``, and ``awb eval --check``. No ``--pipeline``, ``--gates``, or other
threshold/path override flag exists or is exercised here. Gate-failure (code 1) and unexpected-
exception (code 3) are exercised by patching the in-process evaluation seam inside an isolated
child Python process that calls ``ai_workflow_builder.cli.main`` — never a CLI override flag.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ai_workflow_builder.cli import app
from ai_workflow_builder.evaluation import (
    CANONICAL_ISSUE_CODES,
    CORPUS_VERSION,
    PROVIDER_ID,
    SCHEMA_VERSION,
)

runner = CliRunner()

EVALS_DIR = Path(__file__).resolve().parents[1] / "evals"
POISON = "scanner-poison" + chr(64) + "example.invalid"


def _write_poisoned_gates(tmp_path: Path) -> Path:
    """A gates.json identical to the approved one except for one poisoned rationale string --
    isolates the privacy check as the only failure trigger (hashes/denominators untouched)."""
    payload = json.loads((EVALS_DIR / "gates.json").read_text(encoding="utf-8"))
    payload["pipeline"]["schema_valid"]["rationale"] += f" {POISON}"
    poisoned = tmp_path / "gates.json"
    poisoned.write_text(json.dumps(payload), encoding="utf-8")
    return poisoned


def _write_poisoned_readme(tmp_path: Path) -> Path:
    text = (EVALS_DIR / "README.md").read_text(encoding="utf-8") + f"\n{POISON}\n"
    poisoned = tmp_path / "README.md"
    poisoned.write_text(text, encoding="utf-8")
    return poisoned


def _inject_override_produce_verified_evidence_lines(**overrides: Path) -> list[str]:
    kwargs = ", ".join(f"{name}={str(path)!r}" for name, path in overrides.items())
    return [
        "_original_produce = evaluation.produce_verified_evidence",
        "def _produce_override(*_a, **_k):",
        f"    return _original_produce({kwargs})",
        "evaluation.produce_verified_evidence = _produce_override",
    ]


def _inject_poison_only_in_rendered_output_lines() -> list[str]:
    """Poisons every render call identically (so the two --check passes still byte-match, i.e.
    determinism holds), proving the privacy scan catches a pattern that exists *only* in the
    rendered candidate, never in any source fixture/gates/README file."""
    return [
        "_original_render_markdown = evaluation.render_markdown",
        f"_poison = {POISON!r}",
        "def _poisoned_render_markdown(output):",
        "    return _original_render_markdown(output) + _poison",
        "evaluation.render_markdown = _poisoned_render_markdown",
    ]


def eval_registered() -> bool:
    """True once Phase 2 registers the ``awb eval`` command."""
    return runner.invoke(app, ["eval", "--help"]).exit_code == 0


def _fake_evaluation_output_payload(all_gates_passed: bool) -> dict:
    """A minimal, JSON-serializable, schema-valid ``EvaluationOutput`` payload, for injection
    into an isolated child process (see ``_run_child`` below)."""
    metric = {
        "correct": 12,
        "total": 12,
        "errors": 0,
        "rate": "1.0000",
        "gate_passed": all_gates_passed,
    }
    rubric_metric = {**metric, "correct": 6, "total": 6}
    return {
        "schema_version": SCHEMA_VERSION,
        "corpus_version": CORPUS_VERSION,
        "provider": PROVIDER_ID,
        "pipeline": {
            "case_count": 12,
            "metrics": {
                "schema_valid": metric,
                "category_conformance": metric,
                "sentiment_conformance": {**metric, "gate_passed": None},
                "review_routing_conformance": metric,
                "issue_exact_set_conformance": metric,
                "deterministic_rerun_equal": True,
            },
            "failure_count": 0,
            "failures": [],
        },
        "rubric": {
            "case_count": 6,
            "metrics": {
                "review_routing_conformance": rubric_metric,
                "issue_exact_set_conformance": rubric_metric,
                "micro_precision": {**rubric_metric, "gate_passed": None},
                "micro_recall": {**rubric_metric, "gate_passed": None},
                "micro_f1": {**rubric_metric, "gate_passed": None},
            },
            "per_code": [
                {
                    "code": code,
                    "support": 2,
                    "true_positives": 2,
                    "false_positives": 0,
                    "false_negatives": 0,
                }
                for code in CANONICAL_ISSUE_CODES
            ],
            "failure_count": 0,
            "failures": [],
        },
        "hard_invariants": {
            "critical_overconfidence_false_negatives": 0,
            "generic_privacy_pattern_violations": 0,
            "deterministic_rerun_equal": True,
        },
        "all_gates_passed": all_gates_passed,
        "limitations": [
            "Pipeline metrics measure a deterministic rule provider against authored synthetic "
            "expectations, not a learned model or generalization.",
            "The corpus is intentionally small and public-safe; rates are accompanied by "
            "absolute counts.",
            "Overconfidence is exercised at the validator boundary because the current rule "
            "provider cannot emit that behavior.",
            "The case study does not establish production, live-user, deployment, or "
            "domain-specific quality.",
        ],
    }


def _run_child(setup_lines: list[str], argv: list[str]) -> subprocess.CompletedProcess:
    """Run the future ``ai_workflow_builder.cli.main`` wrapper in an isolated child process —
    the subprocess-equivalent of the real ``awb`` console-script boundary, but with the
    evaluation seam patched inside the child rather than through any CLI override flag.

    ``setup_lines`` are flat, column-0 top-level Python statements (no shared indentation with
    this file) inserted after the imports and before ``main()`` is invoked.
    """
    lines = [
        "import sys",
        "import ai_workflow_builder.evaluation as evaluation",
        "from ai_workflow_builder.cli import main",
        *setup_lines,
        f"sys.argv = {argv!r}",
        "main()",
    ]
    script = "\n".join(lines)
    return subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)


def _inject_completed_output_lines(all_gates_passed: bool) -> list[str]:
    payload_json = json.dumps(_fake_evaluation_output_payload(all_gates_passed))
    return [
        "import json",
        f"_payload = json.loads({payload_json!r})",
        "_output = lambda *_a, **_k: evaluation.EvaluationOutput.model_validate(_payload)",
        "evaluation.evaluate = _output",
    ]


def _inject_denominator_mismatch_lines() -> list[str]:
    message = "schema_valid: actual denominator 11 does not match the approved gate denominator 12"
    return [
        "def _boom(*_a, **_k):",
        f"    raise evaluation.CorpusError({message!r})",
        "evaluation.evaluate = _boom",
    ]


def _inject_unexpected_exception_lines() -> list[str]:
    return [
        "def _boom(*_a, **_k):",
        "    raise RuntimeError('unexpected software failure')",
        "evaluation.evaluate = _boom",
    ]


def test_eval_command_registered() -> None:
    assert eval_registered()


def test_existing_cli_commands_intact() -> None:
    assert runner.invoke(app, ["demo", "--help"]).exit_code == 0
    assert runner.invoke(app, ["analyze", "--help"]).exit_code == 0
    assert runner.invoke(app, ["report", "--help"]).exit_code == 0


def test_phase2_eval_markdown_exit_zero() -> None:
    assert eval_registered()
    result = runner.invoke(app, ["eval"])
    assert result.exit_code == 0
    assert "## Suite A" in result.output


def test_eval_stdout_has_exactly_one_trailing_newline() -> None:
    """render_markdown/render_json already end with one LF; echo must not add a second."""
    assert eval_registered()
    result = runner.invoke(app, ["eval"])
    assert result.exit_code == 0
    assert result.output.endswith("\n")
    assert not result.output.endswith("\n\n")


def test_phase2_eval_json_exit_zero() -> None:
    import json

    assert eval_registered()
    result = runner.invoke(app, ["eval", "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["schema_version"] == 1
    assert data["corpus_version"] == "v1"


def test_phase2_eval_output_file_form(tmp_path) -> None:
    assert eval_registered()
    out = tmp_path / "evidence.md"
    result = runner.invoke(app, ["eval", "--output", str(out)])
    assert result.exit_code == 0
    content = out.read_bytes()
    assert b"\r" not in content, "output must use LF line endings, not CRLF"
    assert content.decode("utf-8").startswith("#")


def test_phase2_eval_check_pass_exit_zero() -> None:
    assert eval_registered()
    assert runner.invoke(app, ["eval", "--check"]).exit_code == 0


def test_phase2_eval_invalid_format_exit_two() -> None:
    """Code 2 (contract error) is exercised through an invalid value for the existing
    ``--format`` flag, never a new CLI flag."""
    assert eval_registered()
    result = runner.invoke(app, ["eval", "--format", "not-a-real-format"])
    assert result.exit_code == 2


def _synthetic_path_or_credential_values() -> list[str]:
    # Assembled at runtime (not literal in source) so this guard file does not itself trip the
    # repo-wide generic privacy scan (tests/test_examples_are_synthetic.py).
    return [
        "../../etc/" + "shadow-equivalent",
        "C:/Users/Dmitriy/" + "secret" + "-config.json",
        "api" + "_key" + "=" + "sk-fake-synthetic-" + "0" * 10,
    ]


@pytest.mark.parametrize("synthetic_value", _synthetic_path_or_credential_values())
def test_invalid_format_never_echoes_synthetic_path_or_credential_like_value(
    synthetic_value,
) -> None:
    """A synthetic path- or credential-shaped ``--format`` value must never appear in stdout or
    stderr -- the message is a single fixed sentence, never an echo of user input."""
    result = _run_child([], ["awb", "eval", "--format", synthetic_value])
    assert result.returncode == 2
    assert synthetic_value not in result.stdout
    assert synthetic_value not in result.stderr
    assert result.stderr == "Error: invalid output format; choose 'markdown' or 'json'.\n"


def test_phase2_sentinel_preserved_on_exit_two(tmp_path) -> None:
    assert eval_registered()
    out = tmp_path / "evidence.md"
    out.write_text("SENTINEL", encoding="utf-8")
    result = runner.invoke(app, ["eval", "--format", "not-a-real-format", "--output", str(out)])
    assert result.exit_code == 2
    assert out.read_text(encoding="utf-8") == "SENTINEL"


def test_phase2_two_run_bytes_identical(tmp_path) -> None:
    assert eval_registered()
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"
    first_result = runner.invoke(app, ["eval", "--format", "json", "--output", str(first)])
    assert first_result.exit_code == 0
    second_result = runner.invoke(app, ["eval", "--format", "json", "--output", str(second)])
    assert second_result.exit_code == 0
    assert first.read_bytes() == second.read_bytes()


def test_phase2_subprocess_matrix_via_main_wrapper() -> None:
    """The required 0/1/2/3 exit-code matrix, each exercised through the future
    ``ai_workflow_builder.cli.main`` wrapper in an isolated child process (the
    subprocess-equivalent of the real ``awb`` console-script boundary) rather than only
    ``CliRunner``. Codes 1 and 3 patch the evaluation seam inside the child; no CLI override
    flag (``--pipeline``, ``--gates``, or an environment profile) is used anywhere."""
    assert eval_registered()

    normal = _run_child([], ["awb", "eval"])
    assert normal.returncode == 0

    gate_failure = _run_child(
        _inject_completed_output_lines(all_gates_passed=False), ["awb", "eval", "--check"]
    )
    assert gate_failure.returncode == 1

    invalid_format = _run_child([], ["awb", "eval", "--format", "not-a-real-format"])
    assert invalid_format.returncode == 2

    unexpected_error = _run_child(_inject_unexpected_exception_lines(), ["awb", "eval"])
    assert unexpected_error.returncode == 3


def _inject_stateful_renderer_lines() -> list[str]:
    """Makes ``render_markdown`` produce different bytes on every call after the first --
    proving ``--check``'s determinism proof compares actual rendered bytes, not merely
    intermediate Python structures (which would still match)."""
    return [
        "_render_state = {'calls': 0}",
        "_original_render_markdown = evaluation.render_markdown",
        "def _stateful_render_markdown(output):",
        "    _render_state['calls'] += 1",
        "    text = _original_render_markdown(output)",
        "    if _render_state['calls'] > 1:",
        "        text = text + 'STATEFUL-DRIFT-' + str(_render_state['calls'])",
        "    return text",
        "evaluation.render_markdown = _stateful_render_markdown",
    ]


def test_stateful_renderer_cannot_return_exit_zero_or_publish(tmp_path) -> None:
    """A renderer whose second pass produces different bytes must fail --check's determinism
    proof: never exit 0, never write or print the drifting (or any) candidate content, and
    never leave a trace of the drift in stdout/stderr."""
    out = tmp_path / "evidence.md"
    out.write_bytes(b"SENTINEL")

    result = _run_child(
        _inject_stateful_renderer_lines(), ["awb", "eval", "--check", "--output", str(out)]
    )

    assert result.returncode == 1
    assert result.returncode != 0
    assert out.read_bytes() == b"SENTINEL"
    assert "STATEFUL-DRIFT" not in result.stdout
    assert "STATEFUL-DRIFT" not in result.stderr
    assert result.stderr == "Error: evidence failed the determinism check.\n"


def test_stateful_renderer_cannot_publish_to_stdout() -> None:
    result = _run_child(_inject_stateful_renderer_lines(), ["awb", "eval", "--check"])
    assert result.returncode == 1
    assert result.stdout == ""
    assert "STATEFUL-DRIFT" not in result.stdout


_PRIVACY_FAILURE_MESSAGE = "Error: evidence failed the privacy check.\n"


def test_privacy_match_in_gates_rationale_blocks_check_stdout(tmp_path) -> None:
    poisoned_gates = _write_poisoned_gates(tmp_path)
    setup = _inject_override_produce_verified_evidence_lines(gates_path=poisoned_gates)

    result = _run_child(setup, ["awb", "eval", "--check"])

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == _PRIVACY_FAILURE_MESSAGE
    assert POISON not in result.stdout
    assert POISON not in result.stderr


def test_privacy_match_in_gates_rationale_preserves_sentinel_output_form(tmp_path) -> None:
    poisoned_gates = _write_poisoned_gates(tmp_path)
    setup = _inject_override_produce_verified_evidence_lines(gates_path=poisoned_gates)
    out = tmp_path / "evidence.md"
    out.write_bytes(b"SENTINEL")

    result = _run_child(setup, ["awb", "eval", "--check", "--output", str(out)])

    assert result.returncode == 1
    assert out.read_bytes() == b"SENTINEL"
    assert result.stderr == _PRIVACY_FAILURE_MESSAGE
    assert POISON not in result.stderr


def test_privacy_match_only_in_rendered_output_blocks_check(tmp_path) -> None:
    """A pattern introduced only by the renderer (absent from every source fixture, gates, and
    README file) must still be caught, because the scan covers the exact emitted candidate
    bytes, not only source text."""
    out = tmp_path / "evidence.md"
    out.write_bytes(b"SENTINEL")

    result = _run_child(
        _inject_poison_only_in_rendered_output_lines(),
        ["awb", "eval", "--check", "--output", str(out)],
    )

    assert result.returncode == 1
    assert out.read_bytes() == b"SENTINEL"
    assert result.stderr == _PRIVACY_FAILURE_MESSAGE
    assert POISON not in result.stderr


def test_privacy_match_in_readme_blocks_check(tmp_path) -> None:
    poisoned_readme = _write_poisoned_readme(tmp_path)
    setup = _inject_override_produce_verified_evidence_lines(readme_path=poisoned_readme)

    result = _run_child(setup, ["awb", "eval", "--check"])

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == _PRIVACY_FAILURE_MESSAGE
    assert POISON not in result.stderr


def test_phase2_sentinel_preserved_on_exit_three_via_main_wrapper(tmp_path) -> None:
    """The exit-3 sentinel-preservation proof also goes through the child-process main-wrapper
    path, proving a pre-existing output file survives byte-identical across a real unexpected
    exception caught only by ``main()``."""
    assert eval_registered()
    out = tmp_path / "evidence.md"
    out.write_bytes(b"SENTINEL")

    result = _run_child(_inject_unexpected_exception_lines(), ["awb", "eval", "--output", str(out)])

    assert result.returncode == 3
    assert out.read_bytes() == b"SENTINEL"


def test_gate_denominator_mismatch_maps_to_exit_two_and_preserves_sentinel(tmp_path) -> None:
    """A RateGate/actual-corpus denominator mismatch (e.g. an 11-case pipeline scored against
    the approved 12-case gate) is an expected corpus-configuration error: exit 2, sanitized
    message, pre-existing output preserved untouched."""
    out = tmp_path / "evidence.md"
    out.write_bytes(b"SENTINEL")

    result = _run_child(_inject_denominator_mismatch_lines(), ["awb", "eval", "--output", str(out)])

    assert result.returncode == 2
    assert out.read_bytes() == b"SENTINEL"
    assert "11" not in result.stderr
    assert "12" not in result.stderr
    assert "does not match the approved, frozen fixtures" in result.stderr


def test_exit_two_error_never_leaks_raw_exception_text_or_paths() -> None:
    """Expected-error (exit 2) messages must be a fixed, sanitized category message -- never
    the raw exception text, which can embed an absolute local path or raw internal field
    values from a malformed gates/corpus file."""
    sensitive = "C:/Users/Dmitriy/private/secret-gates.json"
    setup = [
        "def _boom(*_a, **_k):",
        f"    raise evaluation.CorpusError({('leaked hash mismatch against ' + sensitive)!r})",
        "evaluation.evaluate = _boom",
    ]
    result = _run_child(setup, ["awb", "eval"])
    assert result.returncode == 2
    assert sensitive not in result.stderr
    assert "leaked hash mismatch" not in result.stderr
    assert "does not match the approved, frozen fixtures" in result.stderr


def test_exit_three_diagnostic_is_the_exact_fixed_internal_error_message() -> None:
    """The exit-3 diagnostic is exactly ``Internal command error.`` -- never the exception
    type, never its message (which could embed sensitive detail), and never silent."""
    sensitive = "internal secret detail: /etc/shadow-equivalent"
    setup = [
        "def _boom(*_a, **_k):",
        f"    raise RuntimeError({sensitive!r})",
        "evaluation.evaluate = _boom",
    ]
    result = _run_child(setup, ["awb", "eval"])
    assert result.returncode == 3
    assert sensitive not in result.stderr
    assert "RuntimeError" not in result.stderr
    assert result.stderr == "Internal command error.\n"


def test_atomic_write_leaves_no_stray_temp_file(tmp_path) -> None:
    from ai_workflow_builder.cli import _write_bytes_atomically

    target = tmp_path / "evidence.md"
    _write_bytes_atomically(target, b"first content\n")
    assert target.read_bytes() == b"first content\n"
    assert list(tmp_path.iterdir()) == [target]

    _write_bytes_atomically(target, b"second content\n")
    assert target.read_bytes() == b"second content\n"
    assert list(tmp_path.iterdir()) == [target]


def test_atomic_write_preserves_existing_file_when_replace_fails(tmp_path, monkeypatch) -> None:
    """Failure at the ``os.replace`` step (temp file fully written, rename itself fails)."""
    from ai_workflow_builder import cli as cli_module

    target = tmp_path / "evidence.md"
    target.write_bytes(b"SENTINEL")

    def _boom_replace(*_a, **_k):
        raise OSError("simulated failure between write and rename")

    monkeypatch.setattr(cli_module.os, "replace", _boom_replace)

    with pytest.raises(OSError, match="simulated failure"):
        cli_module._write_bytes_atomically(target, b"new content")

    assert target.read_bytes() == b"SENTINEL"
    assert list(tmp_path.iterdir()) == [target], "no stray temp file after a failed write"


def test_atomic_write_preserves_existing_file_on_partial_temp_write_failure(
    tmp_path, monkeypatch
) -> None:
    """Failure *during* the write to the temp file itself, before any replace is attempted --
    distinct from (and previously untested alongside) the replace-failure case above."""
    from ai_workflow_builder import cli as cli_module

    target = tmp_path / "evidence.md"
    target.write_bytes(b"SENTINEL")

    class _BoomFile:
        def write(self, _data):
            raise OSError("simulated disk-full mid-write")

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def _boom_fdopen(fd, *_args, **_kwargs):
        os.close(fd)
        return _BoomFile()

    monkeypatch.setattr(cli_module.os, "fdopen", _boom_fdopen)

    with pytest.raises(OSError, match="simulated disk-full mid-write"):
        cli_module._write_bytes_atomically(target, b"new content")

    assert target.read_bytes() == b"SENTINEL"
    assert list(tmp_path.iterdir()) == [target], "no stray temp file after a partial-write failure"


def _inject_partial_temp_write_failure_lines() -> list[str]:
    return [
        "import os as _os_module",
        "class _BoomFile:",
        "    def write(self, _data):",
        "        raise OSError('simulated disk-full mid-write')",
        "    def __enter__(self):",
        "        return self",
        "    def __exit__(self, *_args):",
        "        return False",
        "def _boom_fdopen(fd, *a, **k):",
        "    _os_module.close(fd)",
        "    return _BoomFile()",
        "_os_module.fdopen = _boom_fdopen",
    ]


def test_atomic_write_partial_failure_via_main_wrapper_maps_to_exit_three(tmp_path) -> None:
    """The mid-write failure, exercised through the real ``main()`` wrapper end to end: exit 3,
    only the fixed internal-error diagnostic, the pre-existing sentinel byte-identical, and no
    stray temp file left behind."""
    out = tmp_path / "evidence.md"
    out.write_bytes(b"SENTINEL")

    result = _run_child(
        _inject_partial_temp_write_failure_lines(), ["awb", "eval", "--output", str(out)]
    )

    assert result.returncode == 3
    assert result.stderr == "Internal command error.\n"
    assert out.read_bytes() == b"SENTINEL"
    assert set(tmp_path.iterdir()) == {out}, "no stray temp file after a partial-write failure"

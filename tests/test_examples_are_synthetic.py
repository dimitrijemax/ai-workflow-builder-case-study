from pathlib import Path

from ai_workflow_builder.evaluation import (
    GENERIC_PRIVACY_PATTERNS,
    evaluate,
    render_json,
    render_markdown,
)

# evals/ carries the approved evaluation fixtures, gates, and README; scanned with the same
# generic patterns as source and tests so the mechanism never drifts between roots.
SCAN_ROOTS = [Path("evals"), Path("examples"), Path("src"), Path("tests")]
ROOT_TEXT_GLOBS = ["*.md"]
TEXT_SUFFIXES = {".json", ".md", ".py"}
PATTERNS = GENERIC_PRIVACY_PATTERNS


def iter_text_files() -> list[Path]:
    files: list[Path] = []
    for root in SCAN_ROOTS:
        files.extend(
            path
            for path in root.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts and path.suffix in TEXT_SUFFIXES
        )
    for pattern in ROOT_TEXT_GLOBS:
        files.extend(path for path in Path(".").glob(pattern) if path.is_file())
    return files


def test_examples_and_source_do_not_contain_obvious_private_artifacts() -> None:
    offenders: list[str] = []
    for path in iter_text_files():
        content = path.read_text(encoding="utf-8")
        for name, pattern in PATTERNS.items():
            if pattern.search(content):
                offenders.append(f"{path}:{name}")

    assert offenders == []


def test_freshly_generated_evaluation_evidence_is_synthetic() -> None:
    """Scan freshly generated (not tracked, not previously written) evaluation evidence, in
    both output forms, with the same generic patterns used for the tracked fixture/source
    roots above."""
    output = evaluate()
    generated_text = render_json(output) + render_markdown(output)

    offenders = [name for name, pattern in PATTERNS.items() if pattern.search(generated_text)]

    assert offenders == []

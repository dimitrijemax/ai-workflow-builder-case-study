import re
from pathlib import Path

SCAN_ROOTS = [Path("examples"), Path("src"), Path("tests")]
ROOT_TEXT_GLOBS = ["*.md"]
TEXT_SUFFIXES = {".json", ".md", ".py"}
PATTERNS = {
    "email": re.compile(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", re.IGNORECASE),
    "phone": re.compile(r"\+?[0-9][0-9 ()-]{8,}"),
    "credential_hint": re.compile(
        r"(api[_-]?key|secret|token)\s*[:=]",
        re.IGNORECASE,
    ),
}


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

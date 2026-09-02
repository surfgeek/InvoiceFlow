"""Read Markdown source text for model-based invoice extraction."""

from pathlib import Path

EXTENSIONS = (".md",)


def read(path: Path) -> str:
    return path.read_bytes().decode("utf-8-sig")

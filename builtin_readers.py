"""Built-in document-to-text adapters."""

from pathlib import Path
from pypdf import PdfReader


def read_text(path: Path) -> str:
    """Read UTF-8 source text, removing only an optional byte-order mark."""
    return path.read_bytes().decode("utf-8-sig")


def read_pdf(path: Path) -> str:
    """Read all PDF text pages without OCR or invoice interpretation."""
    with path.open("rb") as stream:
        reader = PdfReader(stream)
        if reader.is_encrypted:
            raise ValueError(f"Encrypted PDF is not supported: {path.name}")
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)

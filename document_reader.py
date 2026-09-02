"""Read source text without extracting or normalizing invoice fields."""

from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PyPdfError


class DocumentReadError(ValueError):
    """A document could not provide readable text for extraction."""


def read_document(path: str | Path) -> str:
    """Read UTF-8 text formats or all text pages of a PDF.

    Structured text is passed through unchanged; invoice interpretation belongs
    to the model. PDF reading does not perform OCR or recover text from images.
    """
    path = Path(path)
    extension = path.suffix.lower()
    if extension not in {".txt", ".csv", ".json", ".xml", ".pdf"}:
        raise DocumentReadError(f"Unsupported document format: {extension or '(none)'}")

    try:
        if extension == ".pdf":
            with path.open("rb") as stream:
                reader = PdfReader(stream)
                if reader.is_encrypted:
                    raise DocumentReadError(f"Encrypted PDF is not supported: {path.name}")
                text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        else:
            # utf-8-sig removes an optional byte-order mark, preserving the text.
            text = path.read_bytes().decode("utf-8-sig")
    except (OSError, UnicodeError, PyPdfError) as error:
        raise DocumentReadError(f"Could not read {path.name}: {error}") from error

    if not text.strip():
        raise DocumentReadError(f"No readable text found in {path.name}")
    return text

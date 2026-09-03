"""Command-line entry point for invoice extraction."""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from xai_sdk import Client

from document_reader import DocumentReadError, read_document
from extraction import DEFAULT_MODEL, ExtractionError, extract_invoice


def main() -> int:
    """Read a document and print extracted JSON, or report a failure to stderr."""
    parser = argparse.ArgumentParser(description="Extract invoice fields using Grok.")
    parser.add_argument("--invoice_path", required=True, type=Path)
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parent / ".env", encoding="utf-8-sig")

    api_key = os.getenv("XAI_API_KEY", "").strip()
    if not api_key:
        print("Set XAI_API_KEY in the environment or .env file.", file=sys.stderr)
        return 1

    try:
        text = read_document(args.invoice_path)
        with Client(api_key=api_key, timeout=60) as client:
            invoice = extract_invoice(text, client, os.getenv("XAI_MODEL") or DEFAULT_MODEL)
    except (DocumentReadError, ExtractionError) as error:
        print(str(error), file=sys.stderr)
        return 1

    print(invoice.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Command-line entry point for invoice extraction and validation."""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from xai_sdk import Client

from document_reader import DocumentReadError, read_document
from extraction import DEFAULT_MODEL, ExtractionError, extract_invoice
from validation import InventoryValidationError, validate_invoice


def main() -> int:
    """Print extraction and validation results, or report an operational failure."""
    parser = argparse.ArgumentParser(description="Extract and validate an invoice using Grok and SQLite.")
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
        issues = validate_invoice(invoice)
    except (DocumentReadError, ExtractionError, InventoryValidationError) as error:
        print(str(error), file=sys.stderr)
        return 1

    print(json.dumps({"invoice": invoice.model_dump(mode="json"), "validation_issues": issues}, indent=2))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())

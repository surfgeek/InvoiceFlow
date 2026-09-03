"""Command-line entry point for invoice extraction and validation."""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from xai_sdk import Client

from document_reader import DocumentReadError, read_document
from extraction import DEFAULT_MODEL, ExtractionError
from models import ProcessingEvent, ProcessingRecord
from source_review import extract_and_review
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

    record = ProcessingRecord(received_at=datetime.now(timezone.utc))
    stage = "ingestion"
    record.events.append(ProcessingEvent(stage=stage, status="started", timestamp=datetime.now(timezone.utc)))
    try:
        text = read_document(args.invoice_path)
        with Client(api_key=api_key, timeout=60) as client:
            invoice = extract_and_review(text, client, record, os.getenv("XAI_MODEL") or DEFAULT_MODEL)
        record.events.append(ProcessingEvent(stage=stage, status="completed", timestamp=datetime.now(timezone.utc)))
        stage = "validation"
        record.events.append(ProcessingEvent(stage=stage, status="started", timestamp=datetime.now(timezone.utc)))
        issues = validate_invoice(invoice)
    except (DocumentReadError, ExtractionError, InventoryValidationError) as error:
        print(str(error), file=sys.stderr)
        record.events.append(ProcessingEvent(
            stage=stage, status="failed", timestamp=datetime.now(timezone.utc), reason=str(error),
        ))
        print(json.dumps({"processing": record.model_dump(mode="json"), "error": str(error)}, indent=2))
        return 1

    record.events.append(ProcessingEvent(
        stage=stage, status="failed" if issues else "completed",
        timestamp=datetime.now(timezone.utc), reason="; ".join(issues) if issues else None,
    ))
    print(json.dumps({"invoice": invoice.model_dump(mode="json"), "validation_issues": issues,
                      "processing": record.model_dump(mode="json")}, indent=2))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())

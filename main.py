"""Command-line entry point for invoice extraction and validation."""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from xai_sdk import Client

from extraction import DEFAULT_MODEL
from models import ProcessingRecord
from workflow import build_workflow


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
    with Client(api_key=api_key, timeout=60) as client:
        graph = build_workflow(client, os.getenv("XAI_MODEL") or DEFAULT_MODEL)
        result = graph.invoke({"invoice_path": args.invoice_path, "record": record})

    output = {"processing": result["record"].model_dump(mode="json")}
    if result.get("error"):
        output["error"] = result["error"]
        print(result["error"], file=sys.stderr)
    else:
        output["invoice"] = result["invoice"].model_dump(mode="json")
        output["validation_issues"] = result["validation_issues"]
    print(json.dumps(output, indent=2))
    return 1 if result.get("error") or result.get("validation_issues") else 0



if __name__ == "__main__":
    raise SystemExit(main())

"""Command-line entry point for invoice extraction and validation."""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from langgraph.graph.state import CompiledStateGraph
from xai_sdk import Client

from extraction import DEFAULT_MODEL
from models import ProcessingRecord
from workflow import build_workflow


def process_invoice(graph: CompiledStateGraph, path: Path) -> tuple[dict, int]:
    """Run one document with fresh state and format its result for the CLI."""
    record = ProcessingRecord(received_at=datetime.now(timezone.utc))
    result = graph.invoke({"invoice_path": path, "record": record})
    output = {"processing": result["record"].model_dump(mode="json")}
    if result.get("error"):
        output["error"] = result["error"]
        print(f"{path}: {result['error']}", file=sys.stderr)
    else:
        output["invoice"] = result["invoice"].model_dump(mode="json")
        output["validation_issues"] = result["validation_issues"]
    exit_code = 1 if result.get("error") or result.get("validation_issues") else 0
    return output, exit_code


def main() -> int:
    """Print extraction and validation results, or report an operational failure."""
    parser = argparse.ArgumentParser(description="Extract and validate an invoice using Grok and SQLite.")
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--invoice_path", type=Path, help="Process one invoice file.")
    inputs.add_argument("--invoice_dir", type=Path, help="Process files directly in a folder, in filename order.")
    args = parser.parse_args()
    if args.invoice_dir is not None:
        try:
            if not args.invoice_dir.is_dir():
                raise ValueError("Invoice directory must be an existing folder.")
            paths = sorted((path for path in args.invoice_dir.iterdir() if path.is_file()),
                           key=lambda path: (path.name.casefold(), path.name))
            if not paths:
                raise ValueError("Invoice directory contains no files.")
        except (OSError, ValueError) as error:
            print(str(error), file=sys.stderr)
            return 1
    else:
        paths = [args.invoice_path]
    load_dotenv(Path(__file__).resolve().parent / ".env", encoding="utf-8-sig")

    api_key = os.getenv("XAI_API_KEY", "").strip()
    if not api_key:
        print("Set XAI_API_KEY in the environment or .env file.", file=sys.stderr)
        return 1

    with Client(api_key=api_key, timeout=60) as client:
        graph = build_workflow(client, os.getenv("XAI_MODEL") or DEFAULT_MODEL)
        if args.invoice_dir is None:
            output, exit_code = process_invoice(graph, paths[0])
        else:
            results = []
            for index, path in enumerate(paths, start=1):
                print(f"[{index}/{len(paths)}] Processing {path.name}...", file=sys.stderr, flush=True)
                item, code = process_invoice(graph, path)
                results.append({"invoice_path": str(path), "exit_code": code, **item})
                status = "Passed" if code == 0 else "Failed"
                print(f"[{index}/{len(paths)}] {status}: {path.name}", file=sys.stderr, flush=True)
            failed = sum(item["exit_code"] != 0 for item in results)
            output = {"results": results, "summary": {
                "total": len(results), "passed": len(results) - failed, "failed": failed,
            }}
            exit_code = 1 if failed else 0
    print(json.dumps(output, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

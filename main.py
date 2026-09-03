"""Command-line entry point for invoice extraction and validation."""

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import copy_context
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from uuid import uuid4

from dotenv import load_dotenv
from langgraph.graph.state import CompiledStateGraph
from xai_sdk import Client

from configuration import DEFAULT_CONFIG_PATH, load_config
from models import ProcessingRecord
from operational_logging import current_run_id, log_event, log_run
from workflow import build_workflow


def process_invoice(graph: CompiledStateGraph, path: Path) -> tuple[dict, int]:
    """Run one document with fresh state and format its result for the CLI."""
    record = ProcessingRecord(received_at=datetime.now(timezone.utc),
                              run_id=current_run_id(), invoice_id=str(uuid4()))
    log_event("invoice_started", invoice_id=record.invoice_id, file_name=path.name)
    started = monotonic()
    result = graph.invoke({"invoice_path": path, "record": record})
    output = {"processing": result["record"].model_dump(mode="json")}
    if result.get("error"):
        output["error"] = result["error"]
        print(f"{path}: {result['error']}", file=sys.stderr)
    else:
        output["invoice"] = result["invoice"].model_dump(mode="json")
        output["validation_issues"] = result["validation_issues"]
    exit_code = 1 if result.get("error") or result.get("validation_issues") else 0
    log_event("invoice_finished", invoice_id=record.invoice_id, exit_code=exit_code,
              duration_seconds=monotonic()-started,
              validation_issue_count=len(result.get("validation_issues", [])))
    return output, exit_code


def process_folder(graph: CompiledStateGraph, paths: list[Path], workers: int) -> dict:
    """Process independent invoices concurrently, retaining filename order in JSON."""
    def run(index: int, path: Path) -> dict:
        print(f"[{index}/{len(paths)}] Processing {path.name}...", file=sys.stderr, flush=True)
        started = monotonic()
        item, code = process_invoice(graph, path)
        elapsed = round(monotonic() - started, 2)
        status = "Passed" if code == 0 else "Failed"
        print(f"[{index}/{len(paths)}] {status}: {path.name} ({elapsed:.2f}s)",
              file=sys.stderr, flush=True)
        return {"invoice_path": str(path), "exit_code": code, "elapsed_seconds": elapsed, **item}

    # Each invocation owns its state; the shared graph and client contain no
    # per-invoice history. Stock validation only reads the database.
    results = {}
    with ThreadPoolExecutor(max_workers=min(workers, len(paths))) as executor:
        pending = {executor.submit(copy_context().run, run, index, path): index
                   for index, path in enumerate(paths, start=1)}
        for future in as_completed(pending):
            results[pending[future]] = future.result()
    ordered = [results[index] for index in sorted(results)]
    failed = sum(item["exit_code"] != 0 for item in ordered)
    return {"results": ordered, "summary": {
        "total": len(ordered), "passed": len(ordered) - failed, "failed": failed,
    }}


def main() -> int:
    """Print extraction and validation results, or report an operational failure."""
    parser = argparse.ArgumentParser(description="Extract and validate an invoice using Grok and SQLite.")
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--invoice_path", type=Path, help="Process one invoice file.")
    inputs.add_argument("--invoice_dir", type=Path, help="Process files directly in a folder, in filename order.")
    parser.add_argument("--workers", type=int, help="Override configured concurrent folder workers.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="TOML configuration file.")
    parser.add_argument("--log_dir", type=Path, default=Path(__file__).resolve().parent / "logs",
                        help="Directory for per-run structured operational logs.")
    args = parser.parse_args()
    if args.workers is not None and args.workers < 1:
        parser.error("--workers must be at least 1")
    try:
        settings = load_config(args.config)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    workers = args.workers if args.workers is not None else settings.batch.workers
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

    with log_run(args.log_dir) as (_, log_path):
        print(f"Operational log: {log_path}", file=sys.stderr, flush=True)
        with Client(api_key=api_key, timeout=settings.model.timeout_seconds) as client:
            graph = build_workflow(client, os.getenv("XAI_MODEL") or settings.model.name,
                                   reasoning_effort=settings.model.reasoning_effort,
                                   dollar_policy=settings.currency.unqualified_dollar)
            if args.invoice_dir is None:
                output, exit_code = process_invoice(graph, paths[0])
            else:
                output = process_folder(graph, paths, workers)
                exit_code = 1 if output["summary"]["failed"] else 0
        log_event("run_result", exit_code=exit_code, file_count=len(paths))
        print(json.dumps(output, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

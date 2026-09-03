"""Command-line entry point for invoice processing and simulated payment."""

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import copy_context
from contextlib import nullcontext
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
from offline import OfflineClient
from setup_inventory import OFFLINE_DATABASE_PATH
from reporting import write_report


OUTCOME_LABELS = {
    "simulated_paid": "Simulated paid", "pending_approval": "Pending approval",
    "rejected": "Rejected", "validation_blocked": "Validation blocked",
    "processing_error": "Processing error",
    "already_paid": "Already paid", "payment_held": "Payment held for review",
}


def processing_outcome(result: dict) -> str:
    """Classify the final state without confusing business decisions with errors."""
    if result.get("error"):
        return "processing_error"
    if result.get("validation_issues"):
        return "validation_blocked"
    record = result["record"]
    if record.payment_hold:
        return "payment_held"
    if record.payment is not None and record.payment.status == "already_paid":
        return "already_paid"
    if record.approval is not None:
        if record.approval.status == "pending":
            return "pending_approval"
        if record.approval.status == "rejected":
            return "rejected"
        if record.approval.status == "approved" and record.payment is not None:
            return "simulated_paid"
    return "processing_error"


def process_invoice(graph: CompiledStateGraph, path: Path) -> tuple[dict, int]:
    """Run one document with fresh state and format its result for the CLI."""
    record = ProcessingRecord(received_at=datetime.now(timezone.utc),
                              run_id=current_run_id(), invoice_id=str(uuid4()))
    log_event("invoice_started", invoice_id=record.invoice_id, file_name=path.name)
    started = monotonic()
    result = graph.invoke({"invoice_path": path, "record": record})
    output = {"invoice_path": str(path), "processing": result["record"].model_dump(mode="json")}
    if "invoice" in result:
        output["invoice"] = result["invoice"].model_dump(mode="json")
    if "validation_issues" in result:
        output["validation_issues"] = result["validation_issues"]
    if result.get("error"):
        output["error"] = result["error"]
        print(f"{path}: {result['error']}", file=sys.stderr)
    output["outcome"] = processing_outcome(result)
    exit_code = 0 if output["outcome"] in ("simulated_paid", "already_paid") else 1
    log_event("invoice_finished", invoice_id=record.invoice_id, exit_code=exit_code,
              duration_seconds=monotonic()-started,
              validation_issue_count=len(result.get("validation_issues", [])), outcome=output["outcome"])
    return output, exit_code


def process_folder(graph: CompiledStateGraph, paths: list[Path], workers: int,
                   on_result=None, process=None) -> dict:
    """Process independent invoices concurrently, retaining filename order in JSON."""
    invoice_processor = process or (lambda path: process_invoice(graph, path))

    def run(index: int, path: Path) -> dict:
        print(f"[{index}/{len(paths)}] Processing {path.name}...", file=sys.stderr, flush=True)
        started = monotonic()
        item, code = invoice_processor(path)
        elapsed = round(monotonic() - started, 2)
        status = OUTCOME_LABELS[item["outcome"]]
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
            item = future.result()
            results[pending[future]] = item
            if on_result is not None:
                on_result(item)
    ordered = [results[index] for index in sorted(results)]
    counts = {outcome: sum(item["outcome"] == outcome for item in ordered) for outcome in OUTCOME_LABELS}
    print("Summary: " + ", ".join(f"{count} {OUTCOME_LABELS[outcome].lower()}"
                                  for outcome, count in counts.items() if count), file=sys.stderr, flush=True)
    return {"results": ordered, "summary": {"total": len(ordered), **counts}}


def main() -> int:
    """Print invoice results and approval history, or report an operational failure."""
    parser = argparse.ArgumentParser(description="Process invoices through validation, approval, and simulated payment.")
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--invoice_path", type=Path, help="Process one invoice file.")
    inputs.add_argument("--invoice_dir", type=Path, help="Process files directly in a folder, in filename order.")
    parser.add_argument("--workers", type=int, help="Override configured concurrent folder workers.")
    parser.add_argument("--offline", action="store_true", help="Replay bundled model fixtures locally; no API key or network calls.")
    parser.add_argument("--report", type=Path, help="Create a new standalone HTML results report.")
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
    if args.report is not None:
        if (args.report.suffix.lower() != ".html" or args.report.exists() or not args.report.parent.is_dir()
                or (args.invoice_dir is not None and args.report.resolve().parent == args.invoice_dir.resolve())):
            print("Choose a new .html report filename in an existing directory outside the input folder.", file=sys.stderr)
            return 1
    api_key = ""
    if not args.offline:
        load_dotenv(Path(__file__).resolve().parent / ".env", encoding="utf-8-sig")
        api_key = os.getenv("XAI_API_KEY", "").strip()
        if not api_key:
            print("Set XAI_API_KEY for live mode, or use --offline with bundled demo invoices.", file=sys.stderr)
            return 1

    with log_run(args.log_dir) as (_, log_path):
        print(f"Operational log: {log_path}", file=sys.stderr, flush=True)
        mode = "offline" if args.offline else "live"
        print("Mode: offline simulation (fixture responses; no LLM calls)." if args.offline else
              "Mode: live Grok (paid API calls).", file=sys.stderr, flush=True)
        log_event("execution_mode", mode=mode)
        context = nullcontext(OfflineClient()) if args.offline else Client(api_key=api_key, timeout=settings.model.timeout_seconds)
        with context as client:
            graph = build_workflow(client, "offline-simulation" if args.offline else os.getenv("XAI_MODEL") or settings.model.name,
                                   reasoning_effort=settings.model.reasoning_effort,
                                   dollar_policy=settings.currency.unqualified_dollar,
                                   approval_settings=settings.approval,
                                   inventory_aliases=settings.inventory.aliases,
                                   **({"database_path": OFFLINE_DATABASE_PATH} if args.offline else {}))
            if args.invoice_dir is None:
                output, exit_code = process_invoice(graph, paths[0])
            else:
                output = process_folder(graph, paths, workers)
                exit_code = 0 if (output["summary"]["simulated_paid"] + output["summary"]["already_paid"]) == len(paths) else 1
        if args.report is not None:
            try:
                write_report(output, args.report)
                print(f"Report: {args.report.resolve()}", file=sys.stderr)
            except OSError as error:
                print(f"Could not write report: {error}. JSON results follow on stdout.", file=sys.stderr)
                log_event("report_failed", error_type=type(error).__name__)
                exit_code = 1
        log_event("run_result", exit_code=exit_code, file_count=len(paths))
        print(json.dumps(output, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

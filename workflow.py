"""LangGraph routing for document ingestion, source review, and validation."""

import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from xai_sdk import Client

from document_reader import DocumentReadError, read_document
from configuration import DollarPolicy
from currency_policy import apply_currency_policy
from extraction import DEFAULT_MODEL, ExtractionError, extract_invoice
from models import Invoice, ProcessingEvent, ProcessingRecord, ReviewAttempt, ReviewFinding
from operational_logging import log_event, logging_context
from setup_inventory import DATABASE_PATH
from source_review import review_invoice
from validation import InventoryValidationError, validate_invoice


class WorkflowState(TypedDict, total=False):
    """Per-invoice state; nodes add fields as processing progresses."""

    invoice_path: Path
    record: ProcessingRecord
    text: str
    invoice: Invoice
    correction_feedback: str
    validation_issues: list[str]
    error: str


def add_event(record: ProcessingRecord, stage: Literal["ingestion", "validation"],
              status: Literal["started", "completed", "failed"], reason: str | None = None) -> None:
    """Timestamp an outcome in the current node's copy of the processing record."""
    record.events.append(ProcessingEvent(
        stage=stage, status=status, timestamp=datetime.now(timezone.utc), reason=reason,
    ))


def guarded(node: Callable[[WorkflowState], WorkflowState],
            stage: Literal["ingestion", "validation"]) -> Callable[[WorkflowState], WorkflowState]:
    """Preserve node history on expected failures without mutating earlier states."""
    def run(state: WorkflowState) -> WorkflowState:
        record = state["record"].model_copy(deep=True)
        with logging_context(run_id=record.run_id, invoice_id=record.invoice_id, stage=node.__name__):
            started = monotonic()
            log_event("stage_started")
            try:
                update = node({**state, "record": record})
            except (DocumentReadError, ExtractionError, InventoryValidationError) as error:
                add_event(record, stage, "failed", str(error))
                update = {"error": str(error)}
                log_event("stage_failed", error_type=type(error).__name__, duration_seconds=monotonic()-started)
            except Exception as error:
                log_event("stage_failed", error_type=type(error).__name__, duration_seconds=monotonic()-started)
                raise
            else:
                log_event("stage_completed", duration_seconds=monotonic()-started,
                          validation_issue_count=len(update.get("validation_issues", [])),
                          review_finding_count=len(record.reviews[-1].findings) if node.__name__ == "review" else None)
        return {**update, "record": record}
    return run


def build_workflow(client: Client, model: str = DEFAULT_MODEL,
                   database_path: str | Path = DATABASE_PATH, *,
                   reasoning_effort: str = "low", dollar_policy: DollarPolicy | None = None):
    """Compile a sequential graph with at most one source-correction detour."""
    def read(state: WorkflowState) -> WorkflowState:
        add_event(state["record"], "ingestion", "started")
        return {"text": read_document(state["invoice_path"])}

    def extract(state: WorkflowState) -> WorkflowState:
        return {"invoice": extract_invoice(state["text"], client, model, reasoning_effort=reasoning_effort)}

    def review(state: WorkflowState) -> WorkflowState:
        record = state["record"]
        attempt = ReviewAttempt(
            attempt=len(record.reviews) + 1, timestamp=datetime.now(timezone.utc),
            invoice=state["invoice"].model_copy(deep=True),
        )
        record.reviews.append(attempt)
        try:
            result = review_invoice(state["text"], state["invoice"], client, model, reasoning_effort)
        except ExtractionError as error:
            attempt.error = str(error)
            raise
        attempt.findings = [ReviewFinding(
            field=finding.field, extracted_value=finding.extracted_value,
            source_evidence=finding.source_evidence, explanation=finding.explanation,
            resolution="unable_to_determine" if finding.unable_to_determine else "unresolved",
        ) for finding in result.findings]
        attempt.outcome = "issues" if attempt.findings else "passed"
        if not attempt.findings:
            if attempt.attempt == 2:
                for finding in record.reviews[0].findings:
                    finding.resolution = "corrected"
            add_event(record, "ingestion", "completed")
            return {}
        if attempt.attempt >= 2:
            raise ExtractionError("Source discrepancies remain after one correction attempt.")
        return {"correction_feedback": json.dumps({
            "previous_invoice": state["invoice"].model_dump(mode="json"),
            "findings": result.model_dump(mode="json")["findings"],
        })}

    def correct(state: WorkflowState) -> WorkflowState:
        return {"invoice": extract_invoice(
            state["text"], client, model, correction_feedback=state["correction_feedback"],
            reasoning_effort=reasoning_effort,
        )}

    def validate(state: WorkflowState) -> WorkflowState:
        add_event(state["record"], "validation", "started")
        invoice, assumption = apply_currency_policy(state["invoice"], dollar_policy or DollarPolicy())
        state["record"].currency_assumption = assumption
        if assumption:
            log_event("currency_assumed", currency=invoice.currency, policy="unqualified_dollar")
        issues = validate_invoice(invoice, database_path)
        add_event(state["record"], "validation", "failed" if issues else "completed",
                  "; ".join(issues) if issues else None)
        return {"invoice": invoice, "validation_issues": issues}

    def after_review(state: WorkflowState) -> str:
        if state.get("error"):
            return END
        return "validate" if state["record"].reviews[-1].outcome == "passed" else "correct"

    builder = StateGraph(WorkflowState)
    for name, node in (("read", read), ("extract", extract), ("review", review), ("correct", correct)):
        builder.add_node(name, guarded(node, "ingestion"))
    builder.add_node("validate", guarded(validate, "validation"))
    builder.add_edge(START, "read")
    for source, destination in (("read", "extract"), ("extract", "review"), ("correct", "review")):
        builder.add_conditional_edges(
            source, lambda state: "stop" if state.get("error") else "continue",
            {"stop": END, "continue": destination},
        )
    builder.add_conditional_edges("review", after_review, ["validate", "correct", END])
    builder.add_edge("validate", END)
    return builder.compile()

"""Structured operational events without invoice contents or credentials."""

import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from uuid import uuid4

from grpc import RpcError


_context = ContextVar("invoiceflow_log_context", default={})
_logger = logging.getLogger("invoiceflow.operations")
_logger.setLevel(logging.INFO)
_logger.propagate = False
_logger.addHandler(logging.NullHandler())


def log_event(event: str, **fields) -> None:
    """Write only explicitly selected metadata, never arbitrary objects or errors."""
    payload = {"timestamp": datetime.now(timezone.utc).isoformat(),
               **_context.get(), "event": event, **fields}
    _logger.info(json.dumps(payload))


def current_run_id() -> str | None:
    """Return the active CLI run identifier, if logging was configured."""
    return _context.get().get("run_id")


@contextmanager
def logging_context(**fields):
    """Scope identifiers to this execution context, including concurrent invoices."""
    token = _context.set({**_context.get(), **fields})
    try:
        yield
    finally:
        _context.reset(token)


@contextmanager
def log_run(directory: Path):
    """Create a separate UTF-8 JSON-lines log for this run and close it on exit."""
    run_id = str(uuid4())
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{run_id}.log"
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(handler)
    started = monotonic()
    try:
        with logging_context(run_id=run_id):
            log_event("run_started")
            try:
                yield run_id, path
            except BaseException as error:
                log_event("run_failed", error_type=type(error).__name__, duration_seconds=monotonic()-started)
                raise
            else:
                log_event("run_finished", duration_seconds=monotonic()-started)
    finally:
        _logger.removeHandler(handler)
        handler.close()


def sample_logged(chat, model: str, reasoning_effort: str = "low"):
    """Measure a logical SDK call; transport retries are internal to the SDK."""
    call_id = str(uuid4())
    started = monotonic()
    fields = {"call_id": call_id, "model": model, "reasoning_effort": reasoning_effort}
    prefix = "simulation_call" if getattr(chat, "is_offline", False) is True else "model_call"
    log_event(f"{prefix}_started", **fields)
    try:
        response = chat.sample()
    except Exception as error:
        code = error.code().name if isinstance(error, RpcError) and callable(getattr(error, "code", None)) else None
        log_event(f"{prefix}_failed", **fields, duration_seconds=monotonic()-started,
                  error_type=type(error).__name__, api_status=code)
        raise
    usage = getattr(response, "usage", None)
    tokens = {name: value if isinstance(value, int) else None for name in (
        "prompt_tokens", "completion_tokens", "reasoning_tokens",
    ) for value in [getattr(usage, name, None)]}
    if prefix == "simulation_call":
        tokens = {}  # Fixture replay has no token usage or billing.
    log_event(f"{prefix}_completed", **fields, duration_seconds=monotonic()-started,
              finish_reason=response.finish_reason, **tokens)
    return response

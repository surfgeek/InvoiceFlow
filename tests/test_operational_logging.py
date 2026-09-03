"""Verify log contents, failure handling, and concurrent invoice correlation."""

import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from grpc import RpcError, StatusCode

from main import process_folder
from operational_logging import log_event, log_run, logging_context, sample_logged
from source_review import SourceReview
from workflow import build_workflow


class OperationalLoggingTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)

    def read_events(self, path):
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def test_events_are_flushed_json_with_utc_and_context(self):
        with log_run(self.directory) as (run_id, path):
            with logging_context(invoice_id="invoice-1", stage="extract"):
                log_event("stage_started")
            events = self.read_events(path)  # Read before the handler closes.
            self.assertEqual(events[-1]["invoice_id"], "invoice-1")
            self.assertEqual(events[-1]["stage"], "extract")
            self.assertEqual(events[-1]["run_id"], run_id)
            self.assertEqual(datetime.fromisoformat(events[-1]["timestamp"]).utcoffset().total_seconds(), 0)
        self.assertEqual(self.read_events(path)[-1]["event"], "run_finished")

    def test_model_usage_and_latency_are_recorded_without_content(self):
        response = SimpleNamespace(content="private invoice content", finish_reason="REASON_STOP",
                                   usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20, reasoning_tokens=5))
        chat = Mock()
        chat.sample.return_value = response
        with log_run(self.directory) as (_, path):
            self.assertIs(sample_logged(chat, "grok-4.6"), response)
        event = next(event for event in self.read_events(path) if event["event"] == "model_call_completed")
        self.assertEqual(event["prompt_tokens"], 100)
        self.assertEqual(event["completion_tokens"], 20)
        self.assertEqual(event["reasoning_tokens"], 5)
        self.assertEqual(event["reasoning_effort"], "low")
        self.assertGreaterEqual(event["duration_seconds"], 0)
        self.assertNotIn("private invoice content", path.read_text())

    def test_api_failure_logs_status_without_raw_exception(self):
        class ProviderError(RpcError):
            def code(self):
                return StatusCode.RESOURCE_EXHAUSTED

        chat = Mock()
        chat.sample.side_effect = ProviderError("secret-key private payload")
        with log_run(self.directory) as (_, path):
            with self.assertRaises(ProviderError):
                sample_logged(chat, "grok-4.6")
        event = next(event for event in self.read_events(path) if event["event"] == "model_call_failed")
        self.assertEqual(event["api_status"], "RESOURCE_EXHAUSTED")
        self.assertNotIn("secret-key", path.read_text())
        self.assertNotIn("private payload", path.read_text())

    def test_run_failure_closes_log_and_next_run_has_no_duplicate_events(self):
        with self.assertRaises(RuntimeError):
            with log_run(self.directory) as (_, first):
                raise RuntimeError("private error text")
        with log_run(self.directory) as (_, second):
            log_event("second_run")
        self.assertEqual(self.read_events(first)[-1]["event"], "run_failed")
        self.assertNotIn("private error text", first.read_text())
        self.assertEqual(len(self.read_events(second)), 3)
        self.assertNotIn("second_run", first.read_text())

    def test_batch_log_ids_match_results_and_do_not_mix_invoice_histories(self):
        client = Mock()

        def create(**request):
            content = '{"findings":[]}' if request["response_format"] is SourceReview else '{"vendor":"private vendor"}'
            chat = Mock()
            chat.sample.return_value = SimpleNamespace(content=content, finish_reason="REASON_STOP")
            return chat

        client.chat.create.side_effect = create
        graph = build_workflow(client)
        with log_run(self.directory) as (run_id, path), contextlib.redirect_stderr(io.StringIO()), patch(
            "workflow.read_document", return_value="private source document"
        ), patch("workflow.validate_invoice", return_value=[]):
            results = process_folder(graph, [Path("a.txt"), Path("b.txt")], workers=2)
        events = self.read_events(path)
        ids = [item["processing"]["invoice_id"] for item in results["results"]]
        self.assertEqual(len(set(ids)), 2)
        for invoice_id in ids:
            calls = [event for event in events if event.get("invoice_id") == invoice_id
                     and event["event"] == "model_call_completed"]
            self.assertEqual([event["stage"] for event in calls], ["extract", "review"])
            self.assertTrue(all(event["run_id"] == run_id for event in calls))
        self.assertNotIn("private vendor", path.read_text())
        self.assertNotIn("private source document", path.read_text())

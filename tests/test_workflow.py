"""Test graph routes and retained review history using simulated model responses."""

import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from types import SimpleNamespace
from threading import Barrier
from unittest.mock import Mock, patch

from grpc import RpcError

from document_reader import DocumentReadError
from extraction import ExtractionError
from models import Invoice, ProcessingRecord
from source_review import SourceReview
from validation import InventoryValidationError
from workflow import build_workflow


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.sample = self.client.chat.create.return_value.sample
        self.record = ProcessingRecord(received_at=datetime.now(timezone.utc))
        self.original = {"items": [{"name": "WidgetA", "quantity": "10"}]}
        self.corrected = {"items": [{"name": "WidgetA", "quantity": "20"}]}
        self.finding = {"field": "items[0].quantity", "extracted_value": "10",
                        "source_evidence": "WidgetA qty: 20",
                        "explanation": "The quantity should be 20.", "unable_to_determine": False}
        self.issues = {"findings": [self.finding]}
        self.clean = {"findings": []}

    def responses(self, *values):
        self.sample.side_effect = [
            value if isinstance(value, Exception) else SimpleNamespace(
                content=json.dumps(value), finish_reason="REASON_STOP"
            ) for value in values
        ]

    def run_review(self):
        graph = build_workflow(self.client)
        result = {"invoice_path": "example.txt", "record": self.record}
        self.route = []
        with patch("workflow.read_document", return_value="WidgetA qty: 20"), patch(
            "workflow.validate_invoice", return_value=[]
        ) as validator:
            for update in graph.stream(result, stream_mode="updates"):
                self.route.extend(update)
                for values in update.values():
                    result.update(values)
            self.validation_calls = validator.call_count
        self.record = result["record"]
        if result.get("error"):
            raise ExtractionError(result["error"])
        return result["invoice"]

    def test_clean_review_uses_two_calls(self):
        self.responses(self.corrected, self.clean)
        self.run_review()
        self.assertEqual(self.sample.call_count, 2)
        self.assertEqual(self.route, ["read", "extract", "review", "validate"])
        self.assertEqual(self.record.reviews[0].outcome, "passed")
        self.assertEqual(self.record.reviews[0].timestamp.utcoffset().total_seconds(), 0)
        self.assertTrue(all(call.kwargs["reasoning_effort"] == "low"
                            for call in self.client.chat.create.call_args_list))

    def test_correction_preserves_original_findings_and_snapshots(self):
        self.responses(self.original, self.issues, self.corrected, self.clean)
        invoice = self.run_review()
        self.assertEqual(invoice.items[0].quantity, 20)
        first, second = self.record.reviews
        self.assertEqual(first.invoice.items[0].quantity, 10)
        self.assertEqual(second.invoice.items[0].quantity, 20)
        self.assertEqual(first.findings[0].resolution, "corrected")
        self.assertEqual(first.findings[0].source_evidence, "WidgetA qty: 20")
        self.assertEqual(first.findings[0].extracted_value, "10")
        self.assertEqual([first.attempt, second.attempt], [1, 2])
        correction_messages = self.client.chat.create.call_args_list[2].kwargs["messages"]
        self.assertIn("items[0].quantity", str(correction_messages))
        self.assertEqual(self.sample.call_count, 4)
        self.assertEqual(self.route[:5], ["read", "extract", "review", "correct", "review"])

    def test_unresolved_discrepancies_stop_after_four_calls(self):
        self.responses(self.original, self.issues, self.original, self.issues)
        with self.assertRaisesRegex(ExtractionError, "remain"):
            self.run_review()
        self.assertEqual(self.sample.call_count, 4)
        self.assertEqual(self.route[:5], ["read", "extract", "review", "correct", "review"])
        self.assertEqual(len(self.record.reviews), 2)
        self.assertEqual(self.validation_calls, 0)
        self.assertEqual(len(self.route), 5)
        self.assertTrue(all(review.findings[0].resolution == "unresolved"
                            for review in self.record.reviews))

    def test_correction_failure_does_not_erase_first_review(self):
        self.responses(self.original, self.issues, RpcError("failed"))
        with self.assertRaises(ExtractionError):
            self.run_review()
        self.assertEqual(self.record.reviews[0].findings[0].resolution, "unresolved")
        self.assertEqual(self.route, ["read", "extract", "review", "correct"])
        self.assertEqual(self.validation_calls, 0)

    def test_second_review_failure_retains_both_snapshots(self):
        self.responses(self.original, self.issues, self.corrected, RpcError("failed"))
        with self.assertRaises(ExtractionError):
            self.run_review()
        self.assertEqual(self.record.reviews[1].outcome, "failed")
        self.assertIsNotNone(self.record.reviews[1].error)
        self.assertEqual(self.record.reviews[0].findings[0].resolution, "unresolved")

    def test_unknown_source_is_retained(self):
        self.finding["unable_to_determine"] = True
        self.finding["source_evidence"] = None
        self.responses(self.original, self.issues, self.original, self.issues)
        with self.assertRaises(ExtractionError):
            self.run_review()
        self.assertEqual(self.record.reviews[0].findings[0].resolution, "unable_to_determine")

    def test_missing_findings_is_not_a_clean_review(self):
        self.responses(self.original, {})
        with self.assertRaises(ExtractionError):
            self.run_review()
        self.assertEqual(self.record.reviews[0].outcome, "failed")

    def test_incomplete_review_is_rejected(self):
        self.responses(self.original, self.clean)
        responses = list(self.sample.side_effect)
        responses[1].finish_reason = "REASON_MAX_LEN"
        self.sample.side_effect = responses
        with self.assertRaises(ExtractionError):
            self.run_review()
        self.assertEqual(self.record.reviews[0].outcome, "failed")

    def test_read_failure_stops_before_extraction(self):
        graph = build_workflow(self.client)
        with patch("workflow.read_document", side_effect=DocumentReadError("Unreadable document")):
            updates = list(graph.stream({"invoice_path": "bad.txt", "record": self.record},
                                        stream_mode="updates"))
        self.assertEqual([next(iter(update)) for update in updates], ["read"])
        result = updates[0]["read"]
        self.assertEqual(result["error"], "Unreadable document")
        self.assertEqual(result["record"].events[-1].status, "failed")
        self.client.chat.create.assert_not_called()

    def test_extraction_failure_stops_before_review(self):
        self.responses(RpcError("failed"))
        with self.assertRaises(ExtractionError):
            self.run_review()
        self.assertEqual(self.route, ["read", "extract"])
        self.assertEqual(self.record.reviews, [])
        self.assertEqual(self.validation_calls, 0)

    def test_inventory_failure_preserves_successful_review(self):
        self.responses(self.corrected, self.clean)
        graph = build_workflow(self.client)
        with patch("workflow.read_document", return_value="WidgetA qty: 20"), patch(
            "workflow.validate_invoice", side_effect=InventoryValidationError("Database unavailable")
        ):
            result = graph.invoke({"invoice_path": "invoice.txt", "record": self.record})
        self.assertEqual(result["record"].reviews[0].outcome, "passed")
        self.assertEqual(result["record"].events[-1].stage, "validation")
        self.assertEqual(result["record"].events[-1].status, "failed")
        self.assertEqual(result["error"], "Database unavailable")

    def test_graph_reuse_does_not_share_history_or_mutate_input(self):
        self.responses(self.corrected, self.clean, self.original, self.clean)
        graph = build_workflow(self.client)
        initial = {"invoice_path": "invoice.txt", "record": self.record}
        with patch("workflow.read_document", return_value="source"), patch(
            "workflow.validate_invoice", return_value=[]
        ):
            first = graph.invoke(initial)
            second = graph.invoke(initial)
        self.assertEqual(len(first["record"].reviews), 1)
        self.assertEqual(len(second["record"].reviews), 1)
        self.assertEqual(first["record"].reviews[0].invoice.items[0].quantity, 20)
        self.assertEqual(second["record"].reviews[0].invoice.items[0].quantity, 10)
        self.assertEqual(self.record.reviews, [])
        self.assertEqual(self.record.events, [])

    def test_concurrent_graph_runs_keep_invoice_state_separate(self):
        barrier = Barrier(2, timeout=5)
        graph = build_workflow(self.client)

        def extract(text, client, model):
            barrier.wait()
            return Invoice(vendor=text)

        with patch("workflow.read_document", side_effect=str), patch(
            "workflow.extract_invoice", side_effect=extract
        ), patch("workflow.review_invoice", return_value=SourceReview(findings=[])), patch(
            "workflow.validate_invoice", return_value=[]
        ), ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(graph.invoke, {
                "invoice_path": name, "record": ProcessingRecord(received_at=datetime.now(timezone.utc)),
            }) for name in ("first.txt", "second.txt")]
            results = [future.result() for future in futures]
        self.assertEqual([result["record"].reviews[0].invoice.vendor for result in results],
                         ["first.txt", "second.txt"])
        self.assertTrue(all(len(result["record"].reviews) == 1 for result in results))

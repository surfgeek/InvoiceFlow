"""Test review and correction history using simulated model responses."""

import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from grpc import RpcError

from extraction import ExtractionError
from models import ProcessingRecord
from source_review import extract_and_review


class SourceReviewTests(unittest.TestCase):
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
        return extract_and_review("WidgetA qty: 20", self.client, self.record)

    def test_clean_review_uses_two_calls(self):
        self.responses(self.corrected, self.clean)
        self.run_review()
        self.assertEqual(self.sample.call_count, 2)
        self.assertEqual(self.record.reviews[0].outcome, "passed")
        self.assertEqual(self.record.reviews[0].timestamp.utcoffset().total_seconds(), 0)

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

    def test_unresolved_discrepancies_stop_after_four_calls(self):
        self.responses(self.original, self.issues, self.original, self.issues)
        with self.assertRaisesRegex(ExtractionError, "remain"):
            self.run_review()
        self.assertEqual(self.sample.call_count, 4)
        self.assertEqual(len(self.record.reviews), 2)
        self.assertTrue(all(review.findings[0].resolution == "unresolved"
                            for review in self.record.reviews))

    def test_correction_failure_does_not_erase_first_review(self):
        self.responses(self.original, self.issues, RpcError("failed"))
        with self.assertRaises(ExtractionError):
            self.run_review()
        self.assertEqual(self.record.reviews[0].findings[0].resolution, "unresolved")

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

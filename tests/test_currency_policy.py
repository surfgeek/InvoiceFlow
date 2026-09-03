"""Check explicit currency, missing data, and the configured dollar fallback."""

import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from configuration import DollarPolicy
from currency_policy import apply_currency_policy
from models import Invoice, ProcessingRecord
from source_review import SourceReview
from workflow import build_workflow


class CurrencyPolicyTests(unittest.TestCase):
    def test_assume_unqualified_dollars_and_preserve_source(self):
        source = Invoice(currency_qualification="unqualified_dollar")
        result, reason = apply_currency_policy(source, DollarPolicy(action="assume", currency="USD"))
        self.assertEqual(result.currency, "USD")
        self.assertIn("configuration", reason)
        self.assertIsNone(source.currency)

    def test_reject_unqualified_dollars_even_if_fallback_currency_is_set(self):
        result, reason = apply_currency_policy(Invoice(currency_qualification="unqualified_dollar"),
                                               DollarPolicy(action="reject", currency="USD"))
        self.assertIsNone(result.currency)
        self.assertIsNone(reason)

    def test_explicit_currencies_are_preserved(self):
        for code in ("USD", "CAD", "EUR"):
            with self.subTest(code=code):
                result, reason = apply_currency_policy(Invoice(currency=code, currency_qualification="explicit"),
                                                       DollarPolicy(action="assume", currency="USD"))
                self.assertEqual(result.currency, code)
                self.assertIsNone(reason)

    def test_missing_unclassified_and_conflicting_do_not_receive_default(self):
        for qualification in (None, "missing", "conflicting"):
            with self.subTest(qualification=qualification):
                result, reason = apply_currency_policy(Invoice(currency_qualification=qualification),
                                                       DollarPolicy(action="assume", currency="USD"))
                self.assertIsNone(result.currency)
                self.assertIsNone(reason)

    def test_graph_applies_policy_after_review_and_records_assumption(self):
        source = Invoice(vendor="Widgets Inc.", amount="5000", due_date="2026-02-01",
                         currency_qualification="unqualified_dollar", items=[])
        for action, expected in (("assume", "USD"), ("reject", None)):
            with self.subTest(action=action), patch("workflow.read_document", return_value="Total $5,000"), patch(
                "workflow.extract_invoice", return_value=source
            ), patch("workflow.review_invoice", return_value=SourceReview(findings=[])) as reviewer, patch(
                "workflow.validate_invoice", return_value=[]
            ) as validator, patch("workflow.review_approval"):
                graph = build_workflow(Mock(), dollar_policy=DollarPolicy(action=action, currency="USD"))
                result = graph.invoke({"invoice_path": "invoice.txt",
                                       "record": ProcessingRecord(received_at=datetime.now(timezone.utc))})
                self.assertIsNone(reviewer.call_args.args[1].currency)
                self.assertEqual(validator.call_args.args[0].currency, expected)
                self.assertIsNone(result["record"].reviews[0].invoice.currency)
                self.assertEqual(bool(result["record"].currency_assumption), action == "assume")

"""Verify payment authorization, exact values, and failure reporting."""

import contextlib
import io
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

from main import process_invoice
from models import ApprovalRecord, Invoice
from payment import PaymentError, pay_invoice
from source_review import SourceReview
from workflow import build_workflow


class PaymentTests(unittest.TestCase):
    def setUp(self):
        self.invoice = Invoice(vendor="Example", amount="123.4567", currency="EUR",
                               due_date="2026-09-01", items=[{"name": "WidgetA", "quantity": "1"}])

    def test_receipt_preserves_amount_and_currency_without_stdout(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            receipt = pay_invoice(self.invoice, ApprovalRecord(status="approved"))
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(receipt.status, "simulated_paid")
        self.assertEqual(receipt.amount, Decimal("123.4567"))
        self.assertEqual(receipt.currency, "EUR")
        self.assertEqual(receipt.vendor, "Example")
        self.assertTrue(receipt.payment_id)
        self.assertEqual(receipt.timestamp.utcoffset().total_seconds(), 0)

    def test_missing_or_nonapproved_authorization_never_calls_mock(self):
        for approval in (None, ApprovalRecord(status="pending"), ApprovalRecord(status="rejected"),
                         ApprovalRecord(status="failed")):
            with self.subTest(approval=approval), patch("payment.mock_payment") as mock:
                with self.assertRaisesRegex(PaymentError, "final approval"):
                    pay_invoice(self.invoice, approval)
                mock.assert_not_called()

    def test_invalid_payment_details_never_call_mock(self):
        for changes in ({"amount": None}, {"amount": Decimal("0")}, {"currency": None}, {"vendor": " "}):
            with self.subTest(changes=changes), patch("payment.mock_payment") as mock:
                with self.assertRaises(PaymentError):
                    pay_invoice(self.invoice.model_copy(update=changes), ApprovalRecord(status="approved"))
                mock.assert_not_called()

    def test_graph_payment_failure_keeps_approval_and_reports_failure_without_retry(self):
        def approve(invoice, record, *args):
            record.status, record.reason = "approved", "Authorized."

        graph = build_workflow(Mock())
        with patch("workflow.read_document", return_value="invoice"), patch(
            "workflow.extract_invoice", return_value=self.invoice
        ), patch("workflow.review_invoice", return_value=SourceReview(findings=[])), patch(
            "workflow.validate_invoice", return_value=[]
        ), patch("workflow.review_approval", side_effect=approve), patch(
            "payment.mock_payment", side_effect=PaymentError("Simulated payment failed.")
        ) as payment, contextlib.redirect_stderr(io.StringIO()):
            output, code = process_invoice(graph, Path("invoice.txt"))
        self.assertEqual(code, 1)
        self.assertEqual(output["processing"]["approval"]["status"], "approved")
        self.assertIsNone(output["processing"]["payment"])
        self.assertEqual(output["error"], "Simulated payment failed.")
        self.assertEqual(output["processing"]["events"][-1]["stage"], "payment")
        self.assertEqual(output["processing"]["events"][-1]["status"], "failed")
        payment.assert_called_once_with("Example", Decimal("123.4567"), "EUR")

"""Verify payment authorization, exact values, and failure reporting."""

import contextlib
import io
import tempfile
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

from main import process_invoice
from models import ApprovalRecord, Invoice
from payment import PaymentError, PaymentHold, lookup_payment, mock_payment, pay_invoice
from source_review import SourceReview
from workflow import build_workflow
from setup_inventory import setup_inventory


class PaymentTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database = Path(directory.name) / "inventory.db"
        setup_inventory(self.database)
        self.invoice = Invoice(vendor="Example", invoice_number="INV-TEST", amount="123.4567", currency="EUR",
                               due_date="2026-09-01", items=[{"name": "WidgetA", "quantity": "1"}])

    def test_receipt_preserves_amount_and_currency_without_stdout(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            receipt = pay_invoice(self.invoice, ApprovalRecord(status="approved"), self.database)
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
                    pay_invoice(self.invoice, approval, self.database)
                mock.assert_not_called()

    def test_invalid_payment_details_never_call_mock(self):
        for changes in ({"amount": None}, {"amount": Decimal("0")}, {"currency": None}, {"vendor": " "}):
            with self.subTest(changes=changes), patch("payment.mock_payment") as mock:
                with self.assertRaises(PaymentError):
                    pay_invoice(self.invoice.model_copy(update=changes), ApprovalRecord(status="approved"), self.database)
                mock.assert_not_called()

    def test_graph_payment_failure_keeps_approval_and_reports_failure_without_retry(self):
        def approve(invoice, record, *args):
            record.status, record.reason = "approved", "Authorized."

        graph = build_workflow(Mock(), database_path=self.database)
        with patch("workflow.read_document", return_value="invoice"), patch(
            "workflow.extract_invoice", return_value=self.invoice
        ), patch("workflow.review_invoice", return_value=SourceReview(findings=[])), patch(
            "workflow.validate_invoice", return_value=[]
        ), patch("workflow.review_approval", side_effect=approve), patch(
            "payment.mock_payment", side_effect=PaymentError("Simulated payment failed.")
        ) as payment, contextlib.redirect_stderr(io.StringIO()):
            output, code = process_invoice(graph, Path("invoice.txt"))
        self.assertEqual(code, 1)
        self.assertEqual(output["outcome"], "processing_error")
        self.assertEqual(output["processing"]["approval"]["status"], "approved")
        self.assertIsNone(output["processing"]["payment"])
        self.assertEqual(output["error"], "Simulated payment failed.")
        self.assertEqual(output["processing"]["events"][-1]["stage"], "payment")
        self.assertEqual(output["processing"]["events"][-1]["status"], "failed")
        payment.assert_called_once_with("Example", Decimal("123.4567"), "EUR")

    def test_repeat_returns_original_receipt_across_connections(self):
        first = pay_invoice(self.invoice, ApprovalRecord(status="approved"), self.database)
        equivalent = self.invoice.model_copy(update={"vendor": " EXAMPLE ", "invoice_number": "inv-test",
                                                     "amount": Decimal("123.456700")})
        with patch("payment.mock_payment") as mock:
            second = pay_invoice(equivalent, ApprovalRecord(status="approved"), self.database)
            third = lookup_payment(equivalent, self.database)
        mock.assert_not_called()
        self.assertEqual(second.status, "already_paid")
        self.assertEqual((second.payment_id, second.timestamp), (first.payment_id, first.timestamp))
        self.assertEqual(third.payment_id, first.payment_id)

    def test_changed_invoice_and_missing_number_are_held(self):
        pay_invoice(self.invoice, ApprovalRecord(status="approved"), self.database)
        for changes in ({"amount": Decimal("200")}, {"revision": "R1"}, {"currency": "USD"},
                        {"invoice_number": None}, {"invoice_number": " "}, {"items": []}):
            with self.subTest(changes=changes), patch("payment.mock_payment") as mock:
                with self.assertRaises(PaymentHold):
                    pay_invoice(self.invoice.model_copy(update=changes), ApprovalRecord(status="approved"), self.database)
                mock.assert_not_called()

    def test_distinct_vendor_or_number_can_be_paid(self):
        first = pay_invoice(self.invoice, ApprovalRecord(status="approved"), self.database)
        for changes in ({"vendor": "Different Vendor"}, {"invoice_number": "INV-OTHER"}):
            receipt = pay_invoice(self.invoice.model_copy(update=changes), ApprovalRecord(status="approved"), self.database)
            self.assertEqual(receipt.status, "simulated_paid")
            self.assertNotEqual(receipt.payment_id, first.payment_id)

    def test_concurrent_copies_create_exactly_one_payment(self):
        barrier = Barrier(2, timeout=5)
        def pay():
            barrier.wait()
            return pay_invoice(self.invoice, ApprovalRecord(status="approved"), self.database)
        with patch("payment.mock_payment", wraps=mock_payment) as mock, ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(pay) for _ in range(2)]
            receipts = [future.result() for future in futures]
        mock.assert_called_once()
        self.assertEqual({receipt.status for receipt in receipts}, {"simulated_paid", "already_paid"})
        self.assertEqual(len({receipt.payment_id for receipt in receipts}), 1)

    def test_failed_payment_does_not_leave_a_paid_record(self):
        with patch("payment.mock_payment", side_effect=PaymentError("failed")), self.assertRaises(PaymentError):
            pay_invoice(self.invoice, ApprovalRecord(status="approved"), self.database)
        self.assertIsNone(lookup_payment(self.invoice, self.database))
        receipt = pay_invoice(self.invoice, ApprovalRecord(status="approved"), self.database)
        self.assertEqual(receipt.status, "simulated_paid")

    def test_missing_database_or_schema_gives_setup_instruction(self):
        missing = self.database.parent / "missing.db"
        old = self.database.parent / "old.db"
        sqlite3.connect(old).close()
        for path in (missing, old):
            with self.subTest(path=path), self.assertRaisesRegex(PaymentError, "setup_inventory.py"):
                pay_invoice(self.invoice, ApprovalRecord(status="approved"), path)
        self.assertFalse(missing.exists())

    def test_new_graph_skips_approval_for_paid_copy_and_holds_revision(self):
        first = pay_invoice(self.invoice, ApprovalRecord(status="approved"), self.database)
        for changes, outcome in (({}, "already_paid"), ({"revision": "R1"}, "payment_held"),
                                 ({"invoice_number": None}, "payment_held")):
            with self.subTest(outcome=outcome), patch("workflow.read_document", return_value="source"), patch(
                "workflow.extract_invoice", return_value=self.invoice.model_copy(update=changes)
            ), patch("workflow.review_invoice", return_value=SourceReview(findings=[])), patch(
                "workflow.review_approval"
            ) as approval, patch("payment.mock_payment") as payment:
                output, code = process_invoice(build_workflow(Mock(), database_path=self.database), Path("copy.pdf"))
            approval.assert_not_called()
            payment.assert_not_called()
            self.assertEqual(output["outcome"], outcome)
            self.assertEqual(code, 0 if outcome == "already_paid" else 1)
            if outcome == "already_paid":
                self.assertEqual(output["processing"]["payment"]["payment_id"], first.payment_id)
            else:
                self.assertIsNotNone(output["processing"]["payment_hold"])

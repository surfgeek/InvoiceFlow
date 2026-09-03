"""Check record structure without introducing invoice approval rules."""

import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from pydantic import ValidationError

from models import Invoice, InvoiceItem, ProcessingEvent, ProcessingRecord


class InvoiceTests(unittest.TestCase):
    def test_missing_fields_remain_unknown(self) -> None:
        invoice = Invoice()
        self.assertEqual(
            invoice.model_dump(),
            dict(vendor=None, invoice_number=None, revision=None, amount=None, currency=None,
                 currency_qualification=None, items=None, due_date=None),
        )

    def test_decimal_precision_survives_json_round_trip(self) -> None:
        amount = "1234567890123456789012345678.123456"
        invoice = Invoice(amount=amount)

        restored = Invoice.model_validate_json(invoice.model_dump_json())

        self.assertEqual(restored.amount, Decimal(amount))
        self.assertEqual(restored.amount.as_tuple(), Decimal(amount).as_tuple())

    def test_explicit_currency_is_preserved(self) -> None:
        for currency in ("EUR", "USD", "JPY"):
            with self.subTest(currency=currency):
                self.assertEqual(Invoice(currency=currency).currency, currency)

    def test_invalid_business_values_are_preserved_for_validation(self) -> None:
        invoice = Invoice(amount="-250.00", items=[{"name": "WidgetA", "quantity": "-5"}])
        self.assertEqual(invoice.amount, Decimal("-250.00"))
        self.assertEqual(invoice.items[0].quantity, Decimal("-5"))
        # Fractional quantities are also preserved rather than truncated to integers.
        self.assertEqual(InvoiceItem(quantity="1.5").quantity, Decimal("1.5"))

    def test_due_date_has_no_timezone(self) -> None:
        invoice = Invoice(due_date="2026-02-01")
        self.assertIs(type(invoice.due_date), date)
        self.assertEqual(invoice.due_date, date(2026, 2, 1))
        self.assertIn('"due_date":"2026-02-01"', invoice.model_dump_json())

    def test_ambiguous_dates_and_timestamps_are_not_silently_converted(self) -> None:
        for value in ("yesterday", "02/01/2026", "2026-02-01T00:00:00Z",
                      datetime(2026, 2, 1, tzinfo=timezone.utc), 1769904000):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                Invoice(due_date=value)

    def test_unparseable_and_nonfinite_numbers_are_rejected(self) -> None:
        for value in ("not a number", "NaN", "Infinity"):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    Invoice(amount=value)
                with self.assertRaises(ValidationError):
                    InvoiceItem(quantity=value)

    def test_unexpected_fields_and_wrong_item_structure_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            Invoice(vender="Widgets Inc.")
        with self.assertRaises(ValidationError):
            Invoice(items="WidgetA")
        with self.assertRaises(ValidationError):
            InvoiceItem(name="WidgetA", qty=5)


class ProcessingRecordTests(unittest.TestCase):
    def test_arrival_and_failure_preserve_instants_in_utc(self) -> None:
        record = ProcessingRecord(
            received_at="2026-09-02T17:00:00-07:00",
            events=[dict(stage="validation", status="failed",
                         timestamp="2026-09-03T02:00:02+02:00",
                         reason="Requested quantity exceeds inventory")],
        )
        self.assertEqual(record.received_at, datetime(2026, 9, 3, tzinfo=timezone.utc))
        self.assertEqual(record.events[0].timestamp,
                         datetime(2026, 9, 3, 0, 0, 2, tzinfo=timezone.utc))
        self.assertEqual(record.received_at.utcoffset(), timedelta(0))
        self.assertEqual(record.events[0].timestamp.utcoffset(), timedelta(0))
        self.assertEqual(record.events[0].reason, "Requested quantity exceeds inventory")
        self.assertIn('"timestamp":"2026-09-03T00:00:02Z"', record.model_dump_json())

    def test_naive_timestamps_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ProcessingRecord(received_at="2026-09-03T00:00:00")
        with self.assertRaises(ValidationError):
            ProcessingEvent(stage="ingestion", status="started",
                            timestamp=datetime(2026, 9, 3))

    def test_timestamps_must_be_explicit(self) -> None:
        with self.assertRaises(ValidationError):
            ProcessingRecord()
        with self.assertRaises(ValidationError):
            ProcessingEvent(stage="ingestion", status="started")

    def test_unknown_stage_or_status_is_rejected(self) -> None:
        for stage, status in (("unknown", "started"), ("validation", "unknown")):
            with self.subTest(stage=stage, status=status), self.assertRaises(ValidationError):
                ProcessingEvent(stage=stage, status=status,
                                timestamp="2026-09-03T00:00:00Z")

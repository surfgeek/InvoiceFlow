"""Verify invoice rules against isolated SQLite inventory databases."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from decimal import Decimal
from pathlib import Path

from models import Invoice, InvoiceItem
from setup_inventory import setup_inventory
from validation import InventoryValidationError, resolve_inventory_aliases, validate_invoice


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = Path(self.directory.name) / "inventory.db"
        setup_inventory(self.database)
        self.invoice = Invoice(
            vendor="Widgets Inc.", amount="5000", currency="USD",
            due_date="2026-02-01",
            items=[InvoiceItem(name="WidgetA", quantity="10")],
        )

    def check(self):
        return validate_invoice(self.invoice, self.database)

    def test_valid_invoice_does_not_change_stock(self):
        self.assertEqual(self.check(), [])
        self.assertEqual(self.check(), [])
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute(
                "SELECT stock FROM inventory WHERE item='WidgetA'"
            ).fetchone()[0], 15)

    def test_alias_quantities_combine_with_canonical_stock(self):
        self.invoice.items = [InvoiceItem(name="WidgetA", quantity="10"), InvoiceItem(name="Widget A", quantity="6")]
        matched, used = resolve_inventory_aliases(self.invoice, self.database, {"Widget A": "WidgetA"})
        self.assertEqual(validate_invoice(matched, self.database), ["Insufficient stock for WidgetA: 15 available."])
        self.assertEqual(used, {"Widget A": "WidgetA"})
        self.assertEqual(self.invoice.items[1].name, "Widget A")

    def test_alias_cannot_redirect_existing_zero_stock_item(self):
        self.invoice.items = [InvoiceItem(name="FakeItem", quantity="1")]
        matched, used = resolve_inventory_aliases(self.invoice, self.database, {"FakeItem": "WidgetA"})
        self.assertEqual(validate_invoice(matched, self.database), ["Insufficient stock for FakeItem: 0 available."])
        self.assertEqual(used, {})

    def test_missing_alias_target_is_configuration_error(self):
        self.invoice.items = [InvoiceItem(name="Widget A", quantity="1")]
        with self.assertRaisesRegex(InventoryValidationError, "alias target"):
            resolve_inventory_aliases(self.invoice, self.database, {"Widget A": "Typo"})

    def test_unconfigured_names_still_fail_exact_matching(self):
        self.invoice.items = [InvoiceItem(name="widgeta", quantity="1")]
        matched, used = resolve_inventory_aliases(self.invoice, self.database, {"Widget A": "WidgetA"})
        self.assertEqual(validate_invoice(matched, self.database), ["Unknown inventory item: widgeta."])
        self.assertEqual(used, {})

    def test_repeated_lines_exceed_stock(self):
        self.invoice.items *= 2
        self.assertEqual(self.check(), ["Insufficient stock for WidgetA: 15 available."])

    def test_exact_stock_and_fractional_quantities(self):
        self.invoice.items = [InvoiceItem(name="WidgetA", quantity="7.5")] * 2
        self.assertEqual(self.check(), [])

    def test_small_excess_is_not_rounded_away(self):
        self.invoice.items = [InvoiceItem(name="WidgetA", quantity="15"),
                              InvoiceItem(name="WidgetA", quantity="0.00000000000000000000000000001")]
        self.assertIn("Insufficient stock", self.check()[0])

    def test_unknown_item_and_zero_stock(self):
        self.invoice.items = [InvoiceItem(name="Unknown", quantity="1"),
                              InvoiceItem(name="FakeItem", quantity="1")]
        self.assertEqual(self.check(), ["Unknown inventory item: Unknown.",
                                       "Insufficient stock for FakeItem: 0 available."])

    def test_missing_fields_are_all_reported(self):
        self.invoice = Invoice()
        self.assertEqual(len(self.check()), 5)

    def test_blank_vendor_and_missing_item_fields(self):
        self.invoice.vendor = " "
        self.invoice.items = [InvoiceItem(name=" ")]
        self.assertEqual(self.check(), ["Vendor is missing.", "Item 1: name is missing.",
                                       "Item 1: quantity is missing."])

    def test_nonpositive_values_are_rejected(self):
        for value in ("0", "-1"):
            with self.subTest(value=value):
                self.invoice.amount = Decimal(value)
                self.invoice.items = [InvoiceItem(name="WidgetA", quantity=value)]
                self.assertEqual(self.check(), ["Amount must be positive.",
                                               "Item 1: quantity must be positive."])

    def test_negative_line_cannot_cancel_excess_stock(self):
        self.invoice.items = [InvoiceItem(name="WidgetA", quantity="20"),
                              InvoiceItem(name="WidgetA", quantity="-10")]
        self.assertEqual(len(self.check()), 2)

    def test_currency_issue_does_not_skip_inventory(self):
        self.invoice.currency = None
        self.invoice.items[0].quantity = Decimal("20")
        self.assertEqual(self.check(), ["Currency is unknown; payment is blocked.",
                                       "Insufficient stock for WidgetA: 15 available."])

    def test_item_names_are_matched_exactly(self):
        self.invoice.items[0].name = "widgeta"
        self.assertEqual(self.check(), ["Unknown inventory item: widgeta."])

    def test_missing_database_is_not_created(self):
        missing = Path(self.directory.name) / "missing.db"
        with self.assertRaises(InventoryValidationError):
            validate_invoice(self.invoice, missing)
        self.assertFalse(missing.exists())

    def test_database_without_inventory_table_fails(self):
        empty = Path(self.directory.name) / "empty.db"
        sqlite3.connect(empty).close()
        with self.assertRaises(InventoryValidationError):
            validate_invoice(self.invoice, empty)

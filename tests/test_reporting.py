"""Verify safe report content and prevent report output from overwriting input."""

import contextlib
import io
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import main
from models import ProcessingRecord
from reporting import render_report, write_report


class ReportingTests(unittest.TestCase):
    def test_document_html_is_escaped_and_currencies_remain_separate(self):
        record = ProcessingRecord(received_at=datetime.now(timezone.utc), mode="offline").model_dump(mode="json")
        results = [{"invoice_path": "<script>alert(1)</script>.txt", "outcome": "validation_blocked",
                    "processing": record, "invoice": {"vendor": '<img src=x onerror="alert(1)">',
                    "invoice_number": "INV-1", "amount": "123.4567", "currency": currency},
                    "validation_issues": ["Unknown item: <script>"]} for currency in ("USD", "EUR")]
        html = render_report({"results": results})
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img", html)
        self.assertIn("&lt;img", html)
        self.assertIn("123.4567 USD", html)
        self.assertIn("123.4567 EUR", html)
        self.assertIn("Offline simulation", html)

    def test_existing_report_or_input_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invoice.html"
            path.write_text("Original", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                write_report({}, path)
            with patch("sys.argv", ["main.py", "--offline", "--invoice_path", str(path), "--report", str(path)]), \
                    patch("main.OfflineClient") as client, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main.main(), 1)
            client.assert_not_called()
            self.assertEqual(path.read_text(), "Original")

"""Test the extraction CLI through real readers and a mocked API boundary."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import main
from setup_inventory import setup_inventory
from validation import validate_invoice


class MainTests(unittest.TestCase):
    def run_cli(self, path, key="test-key", content=None):
        if content is None:
            content = json.dumps({"vendor": "Widgets Inc.", "amount": "5000",
                                  "currency": "USD", "due_date": "2026-02-01",
                                  "items": [{"name": "WidgetA", "quantity": "10"}]})
        stdout, stderr = io.StringIO(), io.StringIO()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        database = Path(directory.name) / "inventory.db"
        setup_inventory(database)
        with (
            patch("sys.argv", ["main.py", "--invoice_path", str(path)]),
            patch.dict("os.environ", {"XAI_API_KEY": key}, clear=True),
            patch("main.load_dotenv"),
            patch("main.Client") as client,
            patch("main.validate_invoice", side_effect=lambda invoice: validate_invoice(invoice, database)),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            client.return_value.__enter__.return_value.chat.create.return_value.sample.return_value = (
                SimpleNamespace(content=content, finish_reason="REASON_STOP")
            )
            code = main.main()
        return code, stdout.getvalue(), stderr.getvalue(), client

    def test_document_to_json(self):
        path = Path(__file__).resolve().parents[1] / "data/invoices/invoice_1001.txt"
        code, output, error, client = self.run_cli(path)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["invoice"]["vendor"], "Widgets Inc.")
        self.assertEqual(json.loads(output)["validation_issues"], [])
        self.assertEqual(error, "")
        client.return_value.__exit__.assert_called_once()

    def test_missing_key_does_not_call_api(self):
        code, output, error, client = self.run_cli("unused.txt", key="")
        self.assertEqual(code, 1)
        self.assertEqual(output, "")
        self.assertIn("XAI_API_KEY", error)
        client.assert_not_called()

    def test_unreadable_document_does_not_call_api(self):
        code, output, error, client = self.run_cli("unsupported.extension")
        self.assertEqual(code, 1)
        self.assertEqual(output, "")
        self.assertTrue(error)
        client.assert_not_called()

    def test_bad_model_output_is_a_cli_failure(self):
        path = Path(__file__).resolve().parents[1] / "data/invoices/invoice_1001.txt"
        code, output, error, client = self.run_cli(path, content="not JSON")
        self.assertEqual(code, 1)
        self.assertEqual(output, "")
        self.assertIn("schema", error)
        client.return_value.__exit__.assert_called_once()

    def test_unknown_currency_is_reported_in_json(self):
        path = Path(__file__).resolve().parents[1] / "data/invoices/invoice_1001.txt"
        content = json.dumps({"vendor": "Widgets Inc.", "amount": "5000",
                              "due_date": "2026-02-01",
                              "items": [{"name": "WidgetA", "quantity": "10"}]})
        code, output, error, _ = self.run_cli(path, content=content)
        self.assertEqual(code, 1)
        self.assertEqual(error, "")
        self.assertEqual(json.loads(output)["validation_issues"],
                         ["Currency is unknown; payment is blocked."])

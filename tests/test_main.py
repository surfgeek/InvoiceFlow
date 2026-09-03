"""Test the extraction CLI through real readers and a mocked API boundary."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch

import main
from setup_inventory import setup_inventory
from validation import validate_invoice


class MainTests(unittest.TestCase):
    def run_cli(self, path, key="test-key", content=None, responses=None, folder=False):
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
            patch("sys.argv", ["main.py", "--invoice_dir" if folder else "--invoice_path", str(path),
                               "--workers", "1", "--log_dir", str(Path(directory.name) / "logs")]),
            patch.dict("os.environ", {"XAI_API_KEY": key}, clear=True),
            patch("main.load_dotenv"),
            patch("main.Client") as client,
            patch("workflow.validate_invoice", side_effect=lambda invoice, database_path: validate_invoice(invoice, database)) as validator,
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            client.return_value.__enter__.return_value.chat.create.return_value.sample.side_effect = [
                SimpleNamespace(content=value, finish_reason="REASON_STOP")
                for value in (responses if responses is not None else [content, '{"findings":[]}'])
            ]
            code = main.main()
            self.validation_calls = validator.call_count
        return code, stdout.getvalue(), stderr.getvalue(), client

    def make_folder(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return Path(directory.name)

    def test_document_to_json(self):
        path = Path(__file__).resolve().parents[1] / "data/invoices/invoice_1001.txt"
        code, output, error, client = self.run_cli(path)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["invoice"]["vendor"], "Widgets Inc.")
        self.assertEqual(json.loads(output)["validation_issues"], [])
        self.assertTrue(error.startswith("Operational log:"))
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
        self.assertEqual(json.loads(output)["processing"]["events"][-1]["status"], "failed")
        self.assertTrue(error)
        client.return_value.__enter__.return_value.chat.create.assert_not_called()

    def test_bad_model_output_is_a_cli_failure(self):
        path = Path(__file__).resolve().parents[1] / "data/invoices/invoice_1001.txt"
        code, output, error, client = self.run_cli(path, content="not JSON")
        self.assertEqual(code, 1)
        self.assertIn("error", json.loads(output))
        self.assertIn("schema", error)
        client.return_value.__exit__.assert_called_once()

    def test_unknown_currency_is_reported_in_json(self):
        path = Path(__file__).resolve().parents[1] / "data/invoices/invoice_1001.txt"
        content = json.dumps({"vendor": "Widgets Inc.", "amount": "5000",
                              "due_date": "2026-02-01",
                              "items": [{"name": "WidgetA", "quantity": "10"}]})
        code, output, error, _ = self.run_cli(path, content=content)
        self.assertEqual(code, 1)
        self.assertTrue(error.startswith("Operational log:"))
        self.assertEqual(json.loads(output)["validation_issues"],
                         ["Currency is unknown; payment is blocked."])

    def test_unresolved_review_retains_history_and_skips_validation(self):
        path = Path(__file__).resolve().parents[1] / "data/invoices/invoice_1001.txt"
        invoice = '{"amount":"1"}'
        review = json.dumps({"findings": [{"field": "amount", "extracted_value": "1",
            "source_evidence": "Total Amount: $5,000.00", "explanation": "Wrong total.",
            "unable_to_determine": False}]})
        code, output, _, _ = self.run_cli(path, responses=[invoice, review, invoice, review])
        result = json.loads(output)
        self.assertEqual(code, 1)
        self.assertEqual(self.validation_calls, 0)
        self.assertEqual(len(result["processing"]["reviews"]), 2)
        self.assertEqual(result["processing"]["reviews"][0]["findings"][0]["resolution"], "unresolved")
        self.assertEqual(result["processing"]["events"][-1]["status"], "failed")

    def test_corrected_invoice_is_used_for_inventory_validation(self):
        path = Path(__file__).resolve().parents[1] / "data/invoices/invoice_1001.txt"
        invoice = {"vendor": "Widgets Inc.", "amount": "5000", "currency": "USD",
                   "due_date": "2026-02-01", "items": [{"name": "WidgetA", "quantity": "1"}]}
        original = json.dumps(invoice)
        invoice["items"][0]["quantity"] = "10"
        review = json.dumps({"findings": [{"field": "items[0].quantity", "extracted_value": "1",
            "source_evidence": "WidgetA    qty: 10", "explanation": "Wrong quantity.",
            "unable_to_determine": False}]})
        code, output, _, _ = self.run_cli(path, responses=[original, review, json.dumps(invoice), '{"findings":[]}'])
        result = json.loads(output)
        self.assertEqual(code, 0)
        self.assertEqual(self.validation_calls, 1)
        self.assertEqual(result["invoice"]["items"][0]["quantity"], "10")
        self.assertEqual(result["processing"]["reviews"][0]["invoice"]["items"][0]["quantity"], "1")

    def test_folder_runs_in_order_continues_after_errors_and_skips_subfolders(self):
        folder = self.make_folder()
        (folder / "c.txt").write_text("Invoice C", encoding="utf-8")
        (folder / "a.unsupported").write_text("Unreadable format", encoding="utf-8")
        (folder / "b.txt").write_text("Invoice B", encoding="utf-8")
        (folder / "nested").mkdir()
        (folder / "nested" / "extra.txt").write_text("Nested invoice", encoding="utf-8")
        invoice = json.dumps({"vendor": "Example", "amount": "10", "currency": "EUR",
                              "due_date": "2026-02-01", "items": [{"name": "WidgetA", "quantity": "1"}]})
        code, output, error, client = self.run_cli(
            folder, folder=True, responses=["not JSON", invoice, '{"findings":[]}'],
        )
        result = json.loads(output)
        self.assertEqual(code, 1)
        self.assertEqual([Path(item["invoice_path"]).name for item in result["results"]],
                         ["a.unsupported", "b.txt", "c.txt"])
        self.assertEqual([item["exit_code"] for item in result["results"]], [1, 1, 0])
        self.assertEqual(result["summary"], {"total": 3, "passed": 1, "failed": 2})
        self.assertIn("[1/3] Processing a.unsupported...", error)
        self.assertIn("[1/3] Failed: a.unsupported", error)
        self.assertIn("[3/3] Passed: c.txt", error)
        self.assertIn("a.unsupported", error)
        self.assertIn("b.txt", error)
        self.assertEqual(self.validation_calls, 1)
        client.assert_called_once()
        client.return_value.__exit__.assert_called_once()

    def test_folder_success_keeps_each_invoice_history_separate(self):
        folder = self.make_folder()
        for name in ("a.txt", "b.txt"):
            (folder / name).write_text("invoice", encoding="utf-8")
        invoices = [json.dumps({"vendor": vendor, "amount": "10", "currency": "EUR",
                               "due_date": "2026-02-01",
                               "items": [{"name": "WidgetA", "quantity": "1"}]})
                    for vendor in ("First", "Second")]
        code, output, error, _ = self.run_cli(folder, folder=True, responses=[
            invoices[0], '{"findings":[]}', invoices[1], '{"findings":[]}',
        ])
        result = json.loads(output)
        self.assertEqual(code, 0)
        self.assertIn("[1/2] Processing a.txt...", error)
        self.assertIn("[2/2] Passed: b.txt", error)
        self.assertEqual(result["summary"], {"total": 2, "passed": 2, "failed": 0})
        self.assertEqual([item["processing"]["reviews"][0]["invoice"]["vendor"]
                          for item in result["results"]], ["First", "Second"])
        self.assertTrue(all(len(item["processing"]["reviews"]) == 1 for item in result["results"]))

    def test_empty_folder_is_reported_without_api_calls(self):
        code, output, error, client = self.run_cli(self.make_folder(), folder=True)
        self.assertEqual(code, 1)
        self.assertEqual(output, "")
        self.assertIn("no files", error)
        client.assert_not_called()

    def test_invalid_folder_is_reported_without_api_calls(self):
        folder = self.make_folder()
        file = folder / "invoice.txt"
        file.write_text("invoice", encoding="utf-8")
        for path in (folder / "missing", file):
            with self.subTest(path=path):
                code, output, error, client = self.run_cli(path, folder=True)
                self.assertEqual(code, 1)
                self.assertEqual(output, "")
                self.assertIn("existing folder", error)
                client.assert_not_called()

    def test_single_file_and_folder_options_are_mutually_exclusive(self):
        with patch("sys.argv", ["main.py", "--invoice_path", "a.txt", "--invoice_dir", "."]), \
                contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            main.main()
        self.assertEqual(raised.exception.code, 2)

    def test_folder_workers_overlap_and_keep_results_ordered(self):
        barrier = Barrier(2, timeout=5)

        def process(graph, path):
            barrier.wait()  # Both jobs must start before either can finish.
            return {"invoice": {"vendor": path.stem}}, 0

        with patch("main.process_invoice", side_effect=process), contextlib.redirect_stderr(io.StringIO()):
            result = main.process_folder(None, [Path("a.txt"), Path("b.txt")], workers=2)
        self.assertEqual([item["invoice"]["vendor"] for item in result["results"]], ["a", "b"])
        self.assertTrue(all(item["elapsed_seconds"] >= 0 for item in result["results"]))
        self.assertEqual(result["summary"]["passed"], 2)

    def test_nonpositive_workers_are_rejected(self):
        for workers in ("0", "-1"):
            with self.subTest(workers=workers), patch("sys.argv", [
                "main.py", "--invoice_dir", ".", "--workers", workers,
            ]), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                main.main()
            self.assertEqual(raised.exception.code, 2)

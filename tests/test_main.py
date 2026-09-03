"""Test the extraction CLI through real readers and a mocked API boundary."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock, patch

from approval import ApprovalCritique
from models import ApprovalDecision

import main
from setup_inventory import setup_inventory
from workflow import build_workflow
from validation import validate_invoice


class MainTests(unittest.TestCase):
    def run_cli(self, path, key="test-key", content=None, responses=None, folder=False, config_text=None):
        if content is None:
            content = json.dumps({"invoice_number": "INV-TEST", "vendor": "Widgets Inc.", "amount": "5000",
                                  "currency": "USD", "due_date": "2026-02-01",
                                  "items": [{"name": "WidgetA", "quantity": "10"}]})
        stdout, stderr = io.StringIO(), io.StringIO()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        database = Path(directory.name) / "inventory.db"
        setup_inventory(database)
        argv = ["main.py", "--invoice_dir" if folder else "--invoice_path", str(path),
                "--workers", "1", "--log_dir", str(Path(directory.name) / "logs")]
        if config_text is not None:
            config_path = Path(directory.name) / "config.toml"
            config_path.write_text(config_text, encoding="utf-8")
            argv.extend(["--config", str(config_path)])
        with (
            patch("sys.argv", argv),
            patch.dict("os.environ", {"XAI_API_KEY": key}, clear=True),
            patch("main.load_dotenv"),
            patch("main.Client") as client,
            patch("main.build_workflow", side_effect=lambda *args, **kwargs:
                  build_workflow(*args, database_path=database, **kwargs)),
            patch("workflow.validate_invoice", side_effect=lambda invoice, database_path: validate_invoice(invoice, database)) as validator,
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            source_responses = iter([
                SimpleNamespace(content=value, finish_reason="REASON_STOP")
                for value in (responses if responses is not None else [content, '{"findings":[]}'])
            ])
            def create_chat(**kwargs):
                schema = kwargs.get("response_format")
                if schema is ApprovalDecision:
                    value = SimpleNamespace(content='{"status":"approved","reason":"Within the configured limit."}',
                                            finish_reason="REASON_STOP")
                elif schema is ApprovalCritique:
                    value = SimpleNamespace(content='{"findings":[]}', finish_reason="REASON_STOP")
                else:
                    value = next(source_responses)
                return Mock(sample=Mock(return_value=value))
            client.return_value.__enter__.return_value.chat.create.side_effect = create_chat
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
        receipt = json.loads(output)["processing"]["payment"]
        self.assertEqual(receipt["status"], "simulated_paid")
        self.assertEqual(receipt["amount"], "5000")
        self.assertEqual(receipt["currency"], "USD")
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
        content = json.dumps({"invoice_number": "INV-TEST", "vendor": "Widgets Inc.", "amount": "5000",
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
        invoice = {"invoice_number": "INV-TEST", "vendor": "Widgets Inc.", "amount": "5000", "currency": "USD",
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
        invoice = json.dumps({"invoice_number": "INV-TEST", "vendor": "Example", "amount": "10", "currency": "USD",
                              "due_date": "2026-02-01", "items": [{"name": "WidgetA", "quantity": "1"}]})
        code, output, error, client = self.run_cli(
            folder, folder=True, responses=["not JSON", invoice, '{"findings":[]}'],
        )
        result = json.loads(output)
        self.assertEqual(code, 1)
        self.assertEqual([Path(item["invoice_path"]).name for item in result["results"]],
                         ["a.unsupported", "b.txt", "c.txt"])
        self.assertEqual([item["exit_code"] for item in result["results"]], [1, 1, 0])
        self.assertEqual(result["summary"], {"total": 3, "simulated_paid": 1, "processing_error": 2,
                                            "pending_approval": 0, "rejected": 0, "validation_blocked": 0, "already_paid": 0, "payment_held": 0})
        self.assertIn("[1/3] Processing a.unsupported...", error)
        self.assertIn("[1/3] Processing error: a.unsupported", error)
        self.assertIn("[3/3] Simulated paid: c.txt", error)
        self.assertIn("a.unsupported", error)
        self.assertIn("b.txt", error)
        self.assertEqual(self.validation_calls, 1)
        client.assert_called_once()
        client.return_value.__exit__.assert_called_once()

    def test_folder_success_keeps_each_invoice_history_separate(self):
        folder = self.make_folder()
        for name in ("a.txt", "b.txt"):
            (folder / name).write_text("invoice", encoding="utf-8")
        invoices = [json.dumps({"invoice_number": "INV-TEST", "vendor": vendor, "amount": "10", "currency": "USD",
                               "due_date": "2026-02-01",
                               "items": [{"name": "WidgetA", "quantity": "1"}]})
                    for vendor in ("First", "Second")]
        code, output, error, _ = self.run_cli(folder, folder=True, responses=[
            invoices[0], '{"findings":[]}', invoices[1], '{"findings":[]}',
        ])
        result = json.loads(output)
        self.assertEqual(code, 0)
        self.assertIn("[1/2] Processing a.txt...", error)
        self.assertIn("[2/2] Simulated paid: b.txt", error)
        self.assertEqual(result["summary"], {"total": 2, "simulated_paid": 2, "processing_error": 0,
                                            "pending_approval": 0, "rejected": 0, "validation_blocked": 0, "already_paid": 0, "payment_held": 0})
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
            return {"invoice": {"invoice_number": "INV-TEST", "vendor": path.stem}, "outcome": "simulated_paid"}, 0

        with patch("main.process_invoice", side_effect=process), contextlib.redirect_stderr(io.StringIO()):
            result = main.process_folder(None, [Path("a.txt"), Path("b.txt")], workers=2)
        self.assertEqual([item["invoice"]["vendor"] for item in result["results"]], ["a", "b"])
        self.assertTrue(all(item["elapsed_seconds"] >= 0 for item in result["results"]))
        self.assertEqual(result["summary"]["simulated_paid"], 2)

    def test_nonpositive_workers_are_rejected(self):
        for workers in ("0", "-1"):
            with self.subTest(workers=workers), patch("sys.argv", [
                "main.py", "--invoice_dir", ".", "--workers", workers,
            ]), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                main.main()
        self.assertEqual(raised.exception.code, 2)

    def test_folder_reports_each_business_outcome_separately(self):
        outcomes = list(main.OUTCOME_LABELS)
        responses = [({"outcome": outcome}, 0 if outcome in ("simulated_paid", "already_paid") else 1)
                     for outcome in outcomes]
        stderr = io.StringIO()
        with patch("main.process_invoice", side_effect=responses), contextlib.redirect_stderr(stderr):
            result = main.process_folder(None, [Path(f"{index}.txt") for index in range(len(outcomes))], workers=1)
        self.assertEqual(result["summary"], {"total": len(outcomes), **{outcome: 1 for outcome in outcomes}})
        self.assertEqual([item["outcome"] for item in result["results"]], outcomes)
        for label in main.OUTCOME_LABELS.values():
            self.assertIn(f"{label}:", stderr.getvalue())

    def test_configured_dollar_policy_controls_single_invoice_outcome(self):
        path = Path(__file__).resolve().parents[1] / "data/invoices/invoice_1001.txt"
        content = json.dumps({"invoice_number": "INV-TEST", "vendor": "Widgets Inc.", "amount": "5000",
                              "currency_qualification": "unqualified_dollar", "due_date": "2026-02-01",
                              "items": [{"name": "WidgetA", "quantity": "10"}]})
        for action, expected_code in (("assume", 0), ("reject", 1)):
            with self.subTest(action=action):
                code, output, _, _ = self.run_cli(path, content=content, config_text=
                    f'[currency.unqualified_dollar]\naction="{action}"\ncurrency="USD"')
                result = json.loads(output)
                self.assertEqual(code, expected_code)
                self.assertEqual(result["invoice"]["currency"], "USD" if action == "assume" else None)
                self.assertEqual(bool(result["processing"]["currency_assumption"]), action == "assume")

    def test_invalid_config_does_not_call_api(self):
        code, output, error, client = self.run_cli("invoice.txt", config_text=
            '[currency.unqualified_dollar]\naction="assume"')
        self.assertEqual(code, 1)
        self.assertEqual(output, "")
        self.assertIn("currency is required", error)
        client.assert_not_called()

    def test_model_configuration_reaches_client_and_requests(self):
        path = Path(__file__).resolve().parents[1] / "data/invoices/invoice_1001.txt"
        _, _, _, client = self.run_cli(path, config_text=
            '[model]\nname="configured-model"\nreasoning_effort="medium"\ntimeout_seconds=25')
        self.assertEqual(client.call_args.kwargs["timeout"], 25)
        calls = client.return_value.__enter__.return_value.chat.create.call_args_list
        self.assertTrue(all(call.kwargs["model"] == "configured-model" for call in calls))
        self.assertTrue(all(call.kwargs["reasoning_effort"] == "medium" for call in calls))

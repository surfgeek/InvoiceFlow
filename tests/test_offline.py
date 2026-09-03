"""Run the real offline CLI with network access and live client construction blocked."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main
from document_reader import read_document
from models import Invoice
from offline import FIXTURES_PATH, source_digest
from setup_inventory import setup_inventory


ROOT = Path(__file__).resolve().parents[1]


class OfflineTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.database = self.root / "offline.db"
        setup_inventory(self.database)

    def run_cli(self, path, *, folder=False, settings=None, report=None):
        args = ["main.py", "--offline", "--invoice_dir" if folder else "--invoice_path", str(path),
                "--log_dir", str(self.root / "logs")]
        if settings:
            config = self.root / "config.toml"
            config.write_text(settings, encoding="utf-8")
            args.extend(["--config", str(config)])
        if report is not None:
            args.extend(["--report", str(report)])
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("sys.argv", args), patch.dict("os.environ", {}, clear=True), patch(
            "main.OFFLINE_DATABASE_PATH", self.database
        ), patch("main.Client", side_effect=AssertionError("Live client constructed")), patch(
            "main.load_dotenv", side_effect=AssertionError("Offline mode read credentials")
        ), patch("socket.socket.connect", side_effect=AssertionError("Network connection attempted")), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main.main()
        return code, json.loads(stdout.getvalue()), stderr.getvalue()

    def test_offline_correction_payment_and_repeat_without_network(self):
        path = ROOT / "data/invoices/invoice_1001.txt"
        code, result, stderr = self.run_cli(path)
        self.assertEqual(code, 0)
        self.assertEqual(result["outcome"], "simulated_paid")
        self.assertEqual(result["processing"]["mode"], "offline")
        self.assertEqual(len(result["processing"]["reviews"]), 2)
        self.assertEqual(result["processing"]["reviews"][0]["findings"][0]["resolution"], "corrected")
        self.assertIn("offline simulation", stderr)
        _, repeated, _ = self.run_cli(path)
        self.assertEqual(repeated["outcome"], "already_paid")
        self.assertEqual(repeated["processing"]["payment"]["payment_id"], result["processing"]["payment"]["payment_id"])
        events = [json.loads(line) for log in (self.root / "logs").glob("*.log") for line in log.read_text().splitlines()]
        self.assertTrue(any(event["event"] == "simulation_call_completed" for event in events))
        self.assertFalse(any(event["event"].startswith("model_call") for event in events))
        self.assertFalse(any("prompt_tokens" in event for event in events))

    def test_all_bundled_formats_exercise_business_outcomes(self):
        code, result, _ = self.run_cli(ROOT / "data/invoices", folder=True)
        self.assertEqual(code, 1)
        self.assertEqual(result["summary"], {"total": 20, "simulated_paid": 5, "already_paid": 2,
            "payment_held": 1, "validation_blocked": 11, "pending_approval": 1,
            "rejected": 0, "processing_error": 0})
        self.assertTrue(all(item["processing"]["mode"] == "offline" for item in result["results"]))

    def test_aliases_preserve_source_and_appear_in_report(self):
        path = ROOT / "data/invoices/invoice_1010.txt"
        report = self.root / "result.html"
        code, result, stderr = self.run_cli(path, report=report)
        self.assertEqual(code, 0)
        self.assertEqual(result["invoice"]["items"][-1]["name"], "WidgetA (rush order)")
        self.assertEqual(result["processing"]["reviews"][0]["invoice"]["items"][-1]["name"], "WidgetA (rush order)")
        self.assertEqual(result["processing"]["inventory_aliases"], {"WidgetA (rush order)": "WidgetA"})
        html = report.read_text(encoding="utf-8")
        self.assertIn("Configured inventory matches", html)
        self.assertIn("WidgetA (rush order) → WidgetA", html)
        self.assertIn("Offline simulation", html)
        self.assertIn("Report:", stderr)

    def test_vp_tool_response_controls_all_three_outcomes(self):
        for status, outcome in (("pending", "pending_approval"), ("rejected", "rejected"), ("approved", "simulated_paid")):
            with self.subTest(status=status):
                code, result, _ = self.run_cli(ROOT / "data/offline_demo/high_value.txt", settings=
                    f'[approval.mock_vp]\nresponse="{status}"\nreason="Configured test response."')
                self.assertEqual(result["outcome"], outcome)
                self.assertEqual(code, 0 if status == "approved" else 1)
                self.assertEqual(result["processing"]["approval"]["vp_response"]["status"], status)

    def test_edited_document_cannot_reuse_fixture_by_name(self):
        path = self.root / "invoice_1001.txt"
        path.write_text(read_document(ROOT / "data/invoices/invoice_1001.txt") + "\nChanged total: 10", encoding="utf-8")
        code, result, _ = self.run_cli(path)
        self.assertEqual(code, 1)
        self.assertEqual(result["outcome"], "processing_error")
        self.assertIn("no fixture", result["error"])
        self.assertIn("without --offline", result["error"])
        self.assertIsNone(result["processing"]["payment"])

    def test_fixture_catalog_matches_checked_in_sources(self):
        catalog = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))
        for digest, fixture in catalog.items():
            Invoice.model_validate(fixture["invoice"])
            for filename in fixture["source_files"]:
                with self.subTest(filename=filename):
                    text = read_document(ROOT / filename)
                    self.assertEqual(source_digest(text), digest)
                    for finding in fixture.get("findings", []):
                        self.assertIn(finding["source_evidence"], text)

    def test_missing_offline_schema_names_the_correct_setup_command(self):
        self.database = self.root / "uninitialized" / "offline.db"
        code, result, _ = self.run_cli(ROOT / "data/invoices/invoice_1001.txt")
        self.assertEqual(code, 1)
        self.assertIn("setup_inventory.py", result["error"])

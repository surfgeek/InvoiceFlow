"""Exercise the local UI runner and its documented offline recovery."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import ui
from setup_inventory import setup_inventory


ROOT = Path(__file__).resolve().parents[1]


def run_state(run_id: str, directory: Path) -> dict:
    return {"id": run_id, "status": "starting", "directory": str(directory),
            "total": 0, "completed": 0, "results": [], "notices": [],
            "summary": None, "report_path": None, "log_path": None,
            "mode": "live", "error": None}


class UiTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.invoices = self.root / "invoices"
        self.invoices.mkdir()
        ui.RUNS.clear()

    def test_missing_key_continues_with_offline_fixture(self):
        shutil.copyfile(ROOT / "data/invoices/invoice_1001.txt", self.invoices / "invoice.txt")
        database = self.root / "offline.db"
        setup_inventory(database)
        ui.RUNS["run"] = run_state("run", self.invoices)

        with patch.object(ui, "ROOT", self.root), patch.object(
            ui, "OFFLINE_DATABASE_PATH", database
        ), patch.object(ui, "load_dotenv"), patch.dict(os.environ, {}, clear=True):
            ui.run_invoices("run", self.invoices)

        result = ui.RUNS["run"]
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["mode"], "offline")
        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["results"][0]["outcome"], "simulated_paid")
        self.assertIn("Offline mode activated", result["notices"][0])
        self.assertTrue(Path(result["report_path"]).is_file())

    def test_api_failure_retries_offline_and_continues(self):
        (self.invoices / "invoice.txt").write_text("invoice", encoding="utf-8")
        ui.RUNS["run"] = run_state("run", self.invoices)
        live_failure = ({"invoice_path": "invoice.txt", "processing": {"mode": "live"},
                         "outcome": "processing_error", "error": "Grok API request failed."}, 1)
        offline_success = ({"invoice_path": "invoice.txt", "processing": {"mode": "offline"},
                            "outcome": "simulated_paid"}, 0)
        client = Mock()
        client.__enter__ = Mock(return_value=client)
        client.__exit__ = Mock(return_value=False)

        with patch.object(ui, "ROOT", self.root), patch.object(ui, "load_dotenv"), patch.dict(
            os.environ, {"XAI_API_KEY": "test-key"}, clear=True
        ), patch.object(ui, "Client", return_value=client), patch.object(
            ui, "make_graph", side_effect=["offline", "live"]
        ), patch.object(ui, "process_invoice", side_effect=[live_failure, offline_success]) as process, patch.object(
            ui, "write_report"
        ):
            ui.run_invoices("run", self.invoices)

        result = ui.RUNS["run"]
        self.assertEqual(process.call_count, 2)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["mode"], "offline")
        self.assertEqual(result["results"][0]["outcome"], "simulated_paid")
        self.assertIn("Retried offline", result["results"][0]["recovery"])
        self.assertTrue(any("Grok API became unavailable" in notice for notice in result["notices"]))

    def test_invalid_directory_is_rejected_before_starting_thread(self):
        with self.assertRaisesRegex(ValueError, "existing invoice directory"):
            ui.start_run(str(self.root / "missing"))
        self.assertEqual(ui.RUNS, {})

    def test_live_page_uses_expandable_per_invoice_details(self):
        self.assertIn("document.createElement('details')", ui.HTML)
        self.assertIn("View errors and details", ui.HTML)
        self.assertNotIn("validation_issues||[]).join('; ')", ui.HTML)

    def test_runtime_message_reports_missing_key_before_a_run(self):
        with patch.object(ui, "load_dotenv"), patch.dict(os.environ, {}, clear=True):
            self.assertIn("No xAI API key was detected", ui.runtime_message())


if __name__ == "__main__":
    unittest.main()

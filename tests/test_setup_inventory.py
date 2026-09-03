"""Verify inventory setup against real, isolated SQLite databases."""

import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from setup_inventory import setup_inventory


class InventorySetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.database_path = self.root / "inventory.db"

    def read_inventory(self) -> dict[str, int]:
        connection = sqlite3.connect(self.database_path)
        try:
            rows = connection.execute("SELECT item, stock FROM inventory").fetchall()
            # Also catches duplicate rows rather than hiding them in a dictionary.
            self.assertEqual(len(rows), len(dict(rows)))
            return dict(rows)
        finally:
            connection.close()

    def test_creates_assessment_inventory(self) -> None:
        setup_inventory(self.database_path)

        self.assertEqual(
            self.read_inventory(),
            {"WidgetA": 15, "WidgetB": 10, "GadgetX": 5, "FakeItem": 0},
        )

    def test_rerun_leaves_inventory_unchanged(self) -> None:
        setup_inventory(self.database_path)
        original_inventory = self.read_inventory()

        setup_inventory(self.database_path)

        self.assertEqual(self.read_inventory(), original_inventory)

    def test_rerun_preserves_stock_and_restores_missing_seed(self) -> None:
        setup_inventory(self.database_path)
        connection = sqlite3.connect(self.database_path)
        try:
            with connection:
                connection.execute(
                    "UPDATE inventory SET stock = ? WHERE item = ?", (7, "WidgetA")
                )
                connection.execute("DELETE FROM inventory WHERE item = ?", ("WidgetB",))
        finally:
            connection.close()

        setup_inventory(self.database_path)

        self.assertEqual(
            self.read_inventory(),
            {"WidgetA": 7, "WidgetB": 10, "GadgetX": 5, "FakeItem": 0},
        )

    def test_invalid_database_path_reports_failure(self) -> None:
        # SQLite cannot open a directory as a database file.
        with self.assertRaises(sqlite3.OperationalError):
            setup_inventory(self.root)

    def test_upgrade_adds_ledger_and_rerun_preserves_existing_rows(self):
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.execute("CREATE TABLE inventory (item TEXT PRIMARY KEY, stock INTEGER)")
            connection.execute("INSERT INTO inventory VALUES ('WidgetA', 7)")
        setup_inventory(self.database_path)
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.execute("INSERT INTO payments VALUES ('vendor', 'invoice', 'fingerprint', 'receipt')")
        setup_inventory(self.database_path)
        with closing(sqlite3.connect(self.database_path)) as connection:
            self.assertEqual(connection.execute("SELECT * FROM payments").fetchall(),
                             [('vendor', 'invoice', 'fingerprint', 'receipt')])
            self.assertEqual(connection.execute("SELECT stock FROM inventory WHERE item='WidgetA'").fetchone(), (7,))

    def test_cli_creates_database_beside_script(self) -> None:
        # Run a copy so the command cannot touch the developer's inventory.db.
        source = Path(__file__).resolve().parents[1] / "setup_inventory.py"
        script = self.root / source.name
        shutil.copyfile(source, script)
        working_directory = self.root / "other-working-directory"
        working_directory.mkdir()

        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=working_directory,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.database_path.is_file())
        self.assertFalse((working_directory / "inventory.db").exists())
        self.assertIn(str(self.database_path), result.stdout)
        self.assertEqual(
            self.read_inventory(),
            {"WidgetA": 15, "WidgetB": 10, "GadgetX": 5, "FakeItem": 0},
        )

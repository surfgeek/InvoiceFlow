"""Install the local inventory and simulated-payment schemas."""

import argparse
import sqlite3
from pathlib import Path


DATABASE_PATH = Path(__file__).resolve().parent / "inventory.db"
OFFLINE_DATABASE_PATH = DATABASE_PATH.with_name("offline.db")


SEED_INVENTORY = [
    ("WidgetA", 15),
    ("WidgetB", 10),
    ("GadgetX", 5),
    ("FakeItem", 0),
]


def setup_inventory(database_path: str | Path = DATABASE_PATH) -> None:
    """Install missing tables and seed inventory, preserving stock and payments."""
    connection = sqlite3.connect(database_path)
    try:
        # Commit seed inserts together, or roll them back if an insert fails.
        with connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS inventory "
                "(item TEXT PRIMARY KEY, stock INTEGER)"
            )
            connection.executemany(
                "INSERT INTO inventory (item, stock) VALUES (?, ?) "
                "ON CONFLICT(item) DO NOTHING",
                SEED_INVENTORY,
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS payments ("
                "vendor_key TEXT NOT NULL, invoice_key TEXT NOT NULL, "
                "fingerprint TEXT NOT NULL, receipt_json TEXT NOT NULL, "
                "PRIMARY KEY (vendor_key, invoice_key))"
            )
    finally:
        connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Install inventory and payment tables without resetting records.")
    parser.add_argument("--offline", action="store_true", help="Only initialize offline data; by default initialize both databases.")
    args = parser.parse_args()
    for path in ([OFFLINE_DATABASE_PATH] if args.offline else [DATABASE_PATH, OFFLINE_DATABASE_PATH]):
        setup_inventory(path)
        print(f"Inventory and payment database ready: {path}")

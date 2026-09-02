"""Create the local inventory database required by the assessment."""

import sqlite3
from pathlib import Path


DATABASE_PATH = Path(__file__).resolve().parent / "inventory.db"
SEED_INVENTORY = [
    ("WidgetA", 15),
    ("WidgetB", 10),
    ("GadgetX", 5),
    ("FakeItem", 0),
]


def setup_inventory(database_path=DATABASE_PATH):
    connection = sqlite3.connect(database_path)
    try:
        # Commit both changes together, or roll back if either fails.
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
    finally:
        connection.close()


if __name__ == "__main__":
    setup_inventory()
    print(f"Inventory database ready: {DATABASE_PATH}")

"""Check extracted invoice data against explicit rules and local inventory."""

import sqlite3
from contextlib import closing
from fractions import Fraction
from pathlib import Path

from models import Invoice
from setup_inventory import DATABASE_PATH, setup_command


class InventoryValidationError(Exception):
    """Inventory could not be read, so validation could not complete."""


def resolve_inventory_aliases(invoice: Invoice, database_path: str | Path,
                              aliases: dict[str, str]) -> tuple[Invoice, dict[str, str]]:
    """Map explicitly configured names for validation; exact inventory names win."""
    matched = invoice.model_copy(deep=True)
    used = {}
    if not aliases:
        return matched, used
    try:
        with closing(sqlite3.connect(Path(database_path).resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            names = {row[0] for row in connection.execute("SELECT item FROM inventory")}
    except sqlite3.Error as error:
        raise InventoryValidationError(f"Inventory could not be read; run {setup_command(database_path)} and check the database.") from error
    for item in matched.items or []:
        if item.name not in names and item.name in aliases:
            target = aliases[item.name]
            if target not in names:
                raise InventoryValidationError(f"Configured alias target is not in inventory: {target}.")
            used[item.name] = target
            item.name = target
    return matched, used


def validate_invoice(
    invoice: Invoice, database_path: str | Path = DATABASE_PATH
) -> list[str]:
    """Return all detected issues; an empty list does not constitute approval.

    Currency uncertainty is reported alongside other issues for the eventual
    payment gate. Checks neither modify extracted fields nor reserve stock.
    """
    issues: list[str] = []
    if not invoice.vendor or not invoice.vendor.strip():
        issues.append("Vendor is missing.")
    if invoice.amount is None:
        issues.append("Amount is missing.")
    elif invoice.amount <= 0:
        issues.append("Amount must be positive.")
    if invoice.due_date is None:
        issues.append("Due date is missing or ambiguous.")
    if not invoice.currency or not invoice.currency.strip():
        issues.append("Currency is unknown; payment is blocked.")
    if not invoice.items:
        issues.append("Invoice items are missing.")

    quantities: dict[str, Fraction] = {}
    for index, item in enumerate(invoice.items or [], start=1):
        if not item.name or not item.name.strip():
            issues.append(f"Item {index}: name is missing.")
        if item.quantity is None:
            issues.append(f"Item {index}: quantity is missing.")
        elif item.quantity <= 0:
            issues.append(f"Item {index}: quantity must be positive.")
        if item.name and item.name.strip():
            quantities.setdefault(item.name, Fraction(0))
            if item.quantity is not None and item.quantity > 0:
                # Exact addition prevents Decimal context rounding when repeated
                # lines are combined. The original Decimal fields stay unchanged.
                quantities[item.name] += Fraction(item.quantity)

    try:
        uri = Path(database_path).resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            for name, quantity in quantities.items():
                row = connection.execute(
                    "SELECT stock FROM inventory WHERE item = ?", (name,)
                ).fetchone()
                if row is None:
                    issues.append(f"Unknown inventory item: {name}.")
                elif quantity > row[0]:
                    issues.append(f"Insufficient stock for {name}: {row[0]} available.")
    except sqlite3.Error as error:
        raise InventoryValidationError(
            f"Inventory could not be read; run {setup_command(database_path)} and check the database."
        ) from error

    return issues

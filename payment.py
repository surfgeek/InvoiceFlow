"""Local payment simulation with an explicit approval gate."""

from datetime import datetime, timezone
from decimal import Decimal
from contextlib import closing
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from models import ApprovalRecord, Invoice, PaymentReceipt
from setup_inventory import DATABASE_PATH


class PaymentError(Exception):
    """Payment was blocked or the simulation failed."""


class PaymentHold(Exception):
    """Identity is missing or conflicts with a previously paid invoice."""


def normalized_identity(value: str) -> str:
    """Ignore case and repeated whitespace, preserving punctuation and zeros."""
    return " ".join(value.split()).casefold()


def payment_identity(invoice: Invoice) -> tuple[str, str, str]:
    if not invoice.invoice_number or not invoice.invoice_number.strip():
        raise PaymentHold("Invoice number is missing; payment requires review.")
    if not invoice.vendor or not invoice.vendor.strip():
        raise PaymentHold("Vendor is missing; payment identity requires review.")
    # Compare reviewed business fields, not file bytes or model metadata.
    # Fractions canonicalize equivalent decimals without precision loss.
    payload = {
        "amount": str(Fraction(invoice.amount)) if invoice.amount is not None else None,
        "currency": invoice.currency,
        "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
        "revision": normalized_identity(invoice.revision) if invoice.revision else None,
        "items": sorted((item.name or "", str(Fraction(item.quantity)) if item.quantity is not None else "")
                        for item in invoice.items or []),
    }
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return normalized_identity(invoice.vendor), normalized_identity(invoice.invoice_number), fingerprint


def stored_payment(connection, identity: tuple[str, str, str]) -> PaymentReceipt | None:
    row = connection.execute("SELECT fingerprint, receipt_json FROM payments WHERE vendor_key=? AND invoice_key=?",
                             identity[:2]).fetchone()
    if row is None:
        return None
    if row[0] != identity[2]:
        raise PaymentHold("Invoice details differ from a paid invoice with the same vendor and number; review required.")
    try:
        return PaymentReceipt.model_validate_json(row[1]).model_copy(update={"status": "already_paid"})
    except ValueError as error:
        raise PaymentError("Stored payment receipt is invalid; check the payment ledger.") from error


def lookup_payment(invoice: Invoice, database_path: str | Path = DATABASE_PATH) -> PaymentReceipt | None:
    """Check for paid copies or revisions before spending calls on approval."""
    identity = payment_identity(invoice)
    try:
        with closing(sqlite3.connect(Path(database_path).resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            return stored_payment(connection, identity)
    except sqlite3.Error as error:
        raise PaymentError("Payment ledger could not be read; run setup_inventory.py and check the database.") from error


def mock_payment(vendor: str, amount: Decimal, currency: str) -> PaymentReceipt:
    """Produce a simulated receipt without banking calls or inventory changes."""
    return PaymentReceipt(payment_id=str(uuid4()), vendor=vendor, amount=amount,
                          currency=currency, timestamp=datetime.now(timezone.utc))


def pay_invoice(invoice: Invoice, approval: ApprovalRecord | None,
                database_path: str | Path = DATABASE_PATH) -> PaymentReceipt:
    """Serialize duplicate checks and local receipt creation in one transaction."""
    if approval is None or approval.status != "approved":
        raise PaymentError("Payment requires final approval.")
    if (not invoice.vendor or not invoice.vendor.strip() or invoice.amount is None
            or not invoice.amount.is_finite() or invoice.amount <= 0
            or not invoice.currency or not invoice.currency.strip()):
        raise PaymentError("Payment requires a vendor, positive amount, and currency.")
    identity = payment_identity(invoice)
    try:
        with closing(sqlite3.connect(Path(database_path).resolve().as_uri() + "?mode=rw", uri=True)) as connection:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = stored_payment(connection, identity)
                if existing is not None:
                    return existing
                receipt = mock_payment(invoice.vendor, invoice.amount, invoice.currency)
                connection.execute("INSERT INTO payments VALUES (?, ?, ?, ?)", (*identity, receipt.model_dump_json()))
                return receipt
    except sqlite3.Error as error:
        raise PaymentError("Payment ledger could not be updated; run setup_inventory.py and check the database.") from error

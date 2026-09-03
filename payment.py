"""Local payment simulation with an explicit approval gate."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from models import ApprovalRecord, Invoice, PaymentReceipt


class PaymentError(Exception):
    """Payment was blocked or the simulation failed."""


def mock_payment(vendor: str, amount: Decimal, currency: str) -> PaymentReceipt:
    """Produce a simulated receipt without banking calls or inventory changes."""
    return PaymentReceipt(payment_id=str(uuid4()), vendor=vendor, amount=amount,
                          currency=currency, timestamp=datetime.now(timezone.utc))


def pay_invoice(invoice: Invoice, approval: ApprovalRecord | None) -> PaymentReceipt:
    """Only an application's final approved result may reach the payment mock."""
    if approval is None or approval.status != "approved":
        raise PaymentError("Payment requires final approval.")
    if (not invoice.vendor or not invoice.vendor.strip() or invoice.amount is None
            or not invoice.amount.is_finite() or invoice.amount <= 0
            or not invoice.currency or not invoice.currency.strip()):
        raise PaymentError("Payment requires a vendor, positive amount, and currency.")
    return mock_payment(invoice.vendor, invoice.amount, invoice.currency)

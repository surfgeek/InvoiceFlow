"""Apply configured currency assumptions after source review."""

from configuration import DollarPolicy
from models import Invoice


def apply_currency_policy(invoice: Invoice, policy: DollarPolicy) -> tuple[Invoice, str | None]:
    """Return a copy and an audit reason; never infer from missing currency alone."""
    result = invoice.model_copy(deep=True)
    if invoice.currency_qualification in ("missing", "conflicting"):
        result.currency = None
    elif invoice.currency_qualification == "unqualified_dollar":
        result.currency = None
        if policy.action == "assume":
            result.currency = policy.currency
            return result, f"Unqualified $ treated as {policy.currency} by currency.unqualified_dollar configuration."
    return result, None

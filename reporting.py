"""Export a standalone HTML report from completed CLI results."""

from collections import Counter
from html import escape
from pathlib import Path


def text(value) -> str:
    return escape(str(value)) if value is not None else "—"


def render_report(output: dict) -> str:
    """Escape all document values; the report needs no scripts or external assets."""
    results = output.get("results", [output])
    counts = Counter(item["outcome"] for item in results)
    modes = {item["processing"]["mode"] for item in results}
    mode = "Offline simulation · scripted model responses" if modes == {"offline"} else "Live model processing"
    cards = "".join(f'<div class="stat"><strong>{count}</strong>{text(outcome.replace("_", " "))}</div>'
                    for outcome, count in counts.items())
    rows = []
    for result in results:
        invoice = result.get("invoice", {})
        record = result["processing"]
        receipt = record.get("payment")
        outcome = result["outcome"]
        reasons = ([result["error"]] if result.get("error") else result.get("validation_issues") or
                   ([record["payment_hold"]] if record.get("payment_hold") else []))
        if not reasons:
            if receipt:
                reasons = ["Original receipt reused; no new payment." if outcome == "already_paid"
                           else "Simulated payment completed."]
            else:
                reasons = [(record.get("approval") or {}).get("reason", "No completed decision.")]
        details = []
        if invoice.get("items"):
            details.append("<h4>Extracted items</h4><ul>" + "".join(
                f'<li>{text(item.get("name"))} · quantity {text(item.get("quantity"))}</li>'
                for item in invoice["items"]) + "</ul>")
        if record.get("inventory_aliases"):
            details.append("<h4>Configured inventory matches</h4><ul>" + "".join(
                f"<li>{text(source)} → {text(target)}</li>" for source, target in record["inventory_aliases"].items()) + "</ul>")
        if record.get("currency_assumption"):
            details.append(f'<p>{text(record["currency_assumption"])}</p>')
        findings = [finding for review in record.get("reviews", []) for finding in review["findings"]]
        if findings:
            details.append("<h4>Source review findings</h4><ul>" + "".join(
                f'<li>{text(finding["field"])}: {text(finding["explanation"])} '
                f'({text(finding["resolution"])})</li>' for finding in findings) + "</ul>")
        approval = record.get("approval")
        if approval:
            details.append(f'<h4>Approval</h4><p>{text(approval["status"])}: {text(approval["reason"])}</p>')
            if approval.get("vp_response"):
                details.append(f'<p>Mock VP: {text(approval["vp_response"]["status"])} — '
                               f'{text(approval["vp_response"]["reason"])}</p>')
            for attempt in approval.get("attempts", []):
                details.extend(f'<p>Critique: {text(finding)}</p>' for finding in attempt["findings"])
        if receipt:
            details.append(f'<h4>Receipt</h4><p>{text(receipt["payment_id"])}<br>{text(receipt["timestamp"])} (UTC)</p>')
        details.append("<h4>Processing history</h4><ul>" + "".join(
            f'<li>{text(event["timestamp"])} · {text(event["stage"])}: {text(event["status"])}'
            f'{": " + text(event["reason"]) if event.get("reason") else ""}</li>'
            for event in record["events"]) + "</ul>")
        details.append(f'<p class="muted">Run: {text(record.get("run_id"))}<br>Invoice record: {text(record.get("invoice_id"))}</p>')
        rows.append(f'''<tr><td><strong>{text(invoice.get("invoice_number"))}</strong>
<span class="muted">{text(Path(result.get("invoice_path", "")).name)}</span>
<span>{text(invoice.get("vendor"))}</span></td>
<td class="amount">{text(invoice.get("amount"))} {text(invoice.get("currency"))}</td>
<td><span class="badge {text(outcome)}">{text(outcome.replace("_", " "))}</span>
<ul>{"".join(f"<li>{text(reason)}</li>" for reason in reasons)}</ul>
<details><summary>View evidence and history</summary>{"".join(details)}</details></td></tr>''')
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>InvoiceFlow results</title><style>
body{{margin:0;background:#f3f6fa;color:#172538;font:16px/1.5 system-ui,sans-serif}}
main{{max-width:1150px;margin:40px auto;padding:0 24px}}h1{{font-size:32px;margin:4px 0}}
.eyebrow{{color:#285579;font-weight:700;letter-spacing:.12em;font-size:12px}}.muted{{color:#52647a;font-size:13px}}
.stats{{display:flex;flex-wrap:wrap;gap:12px;margin:24px 0}}.stat{{background:white;padding:16px 22px;border-radius:10px;min-width:110px}}
.stat strong{{display:block;font-size:28px}}.table-wrap{{overflow:auto;background:white;border-radius:12px}}
table{{width:100%;border-collapse:collapse;text-align:left}}th,td{{padding:20px;vertical-align:top;border-bottom:1px solid #dde4ec}}
th{{background:#e8eef5;font-size:13px}}td:first-child{{width:26%}}td:first-child span{{display:block;overflow-wrap:anywhere}}
.amount{{white-space:nowrap}}.badge{{display:inline-block;background:#e8eef5;padding:4px 10px;border-radius:6px;font-weight:600;font-size:13px}}
.simulated_paid,.already_paid{{background:#dcf3e7;color:#18583c}}.pending_approval,.payment_held{{background:#fff0cc;color:#725000}}
.processing_error,.rejected,.validation_blocked{{background:#fce4e4;color:#832b2b}}
ul{{padding-left:20px;margin:10px 0}}summary{{cursor:pointer;color:#285579;font-weight:600}}details{{font-size:14px;overflow-wrap:anywhere}}
h4{{margin:16px 0 4px}}p{{margin:8px 0}}@media print{{body{{background:white}}main{{margin:0}}details{{break-inside:avoid}}}}
</style></head><body><main><div class="eyebrow">ACME CORP · INVOICEFLOW</div><h1>Invoice processing results</h1>
<p>{text(mode)} · {len(results)} document(s)</p><p class="muted">All payments are simulated. No funds were transferred. Amounts retain their original currencies and precision.</p>
<section class="stats" aria-label="Outcome summary">{cards}</section><div class="table-wrap"><table>
<thead><tr><th scope="col">Invoice / source / vendor</th><th scope="col">Amount</th><th scope="col">Outcome and evidence</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></div><p class="muted">Held and pending invoices require review; this report does not authorize or resume payments.</p>
</main></body></html>'''


def write_report(output: dict, path: Path) -> None:
    """Create a new report without overwriting an existing file."""
    with path.open("x", encoding="utf-8") as report:
        report.write(render_report(output))

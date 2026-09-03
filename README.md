# InvoiceFlow

InvoiceFlow uses Grok and LangGraph to extract invoice data, review it against the
source, validate it against a local SQLite inventory, and simulate approval and payment.
It supports TXT, CSV, JSON, XML, Markdown, and text-based PDFs. No real funds are transferred.
Live mode uses Grok; offline mode replays explicit demo fixtures through the same
workflow. See the [demo walkthrough](docs/DEMO.md) for scenarios and business impact.

## How to set up

You need Python 3.12. Install dependencies before disconnecting from the internet:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
```

**Install the required database schema and seed inventory before running the app:**

```powershell
.\.venv\Scripts\python setup_inventory.py
```

For the offline demo, use this instead (or run both to use both modes):

```powershell
.\.venv\Scripts\python setup_inventory.py --offline
```

Python includes SQLite; no separate database server is needed. This command creates
`inventory.db` for live mode, or `offline.db` for offline mode, beside the script with:

- `inventory`: validation stock—WidgetA 15, WidgetB 10, GadgetX 5, FakeItem 0.
- `payments`: saved simulated receipts and invoice identities for duplicate checks.

Run the same command after upgrading an existing installation to add the payment
table. It preserves existing stock and payment records. The app requires these
tables; copying the code alone is not enough. Earlier receipts in log files are
not imported into the new ledger.

**Live mode only:** get an xAI API key with credits and create `.env` beside `main.py`:

```dotenv
XAI_API_KEY=your-api-key
```

Offline mode needs no API key, does not read `.env`, and makes no network calls.
The key and generated databases are excluded from Git. Keep each database between
runs to retain its payment history; offline receipts cannot affect live runs.

Commands below use Windows paths. On macOS/Linux, use `.venv/bin/python` instead
of `.\.venv\Scripts\python`.

## How to run from the command line

Process one invoice with live Grok:

```powershell
.\.venv\Scripts\python main.py --invoice_path=data/invoices/invoice_1001.txt
```

Process a folder and save the results:

```powershell
.\.venv\Scripts\python main.py --invoice_dir=data/invoices > batch-results.json
```

**Offline demo — no internet or API charges:**

```powershell
.\.venv\Scripts\python main.py --offline --invoice_path=data/invoices/invoice_1001.txt
.\.venv\Scripts\python main.py --offline --invoice_dir=data/invoices > offline-results.json
.\.venv\Scripts\python main.py --offline --invoice_path=data/offline_demo/high_value.txt
```

Offline mode uses scripted model responses for unchanged bundled invoices. It
exercises the real readers, graph, SQLite checks, approval tool, and payment ledger;
it does **not** perform LLM reasoning. Invoice 1001 includes a deliberate extraction
mistake that its scripted review detects and corrects. The high-value example
requests the configured mock VP response (pending by default).

Input text is checked against fixture hashes. Renamed copies work; new or edited
documents fail clearly instead of receiving canned answers. Use live mode for those.
The terminal, `processing.mode`, and simulation log events identify offline runs.

Folder runs process files concurrently, skip subfolders, and continue after
individual failures. Results remain in filename order. Keep the output file
outside the input folder.

Live processing uses paid API calls. Progress appears in the terminal; JSON results
are written when the run finishes. Results include extracted data, validation
issues, source-review history, and approval decisions in `processing.approval`.
Simulated receipts appear in `processing.payment`, with the vendor, exact amount,
currency, payment ID, and UTC timestamp. Exit code **0** means simulated payment
completed or was already recorded; **1** means failed, blocked, rejected, pending,
or held for review. Each result has an
`outcome`: `simulated_paid`, `pending_approval`, `rejected`, `validation_blocked`,
`processing_error`, `already_paid`, or `payment_held`. Folder summaries count each outcome separately.

Duplicate checks use the source-reviewed vendor and invoice number. A matching
paid invoice reuses its original receipt without another payment. Changed details
under that identity, or a missing invoice number, hold payment for review; the
reason appears in `processing.payment_hold`. There is no review inbox or automatic
revision reconciliation. If original and revised copies arrive together, the first
successful payment is recorded and a differing copy is held.

Each run also writes a structured log under `logs/` and prints its path. Logs
include stage timings, model usage, and errors, linked to results by run/invoice IDs.

Run automated tests without API calls:

```powershell
.\.venv\Scripts\python -m unittest discover -s tests -v
```

## How to configure

Edit [config.toml](config.toml). Changes apply on the next run.

```toml
[model]
name = "grok-4.6"
reasoning_effort = "low"
timeout_seconds = 60

[batch]
workers = 4

[currency.unqualified_dollar]
action = "assume"
currency = "USD"

[approval.limits]
USD = "10000"

[approval.mock_vp]
response = "pending"
reason = "Configured local mock VP response."
```

`timeout_seconds` applies per model call. `workers` controls concurrent invoices.
Keep secrets in `.env`. Invalid configuration stops processing before any API calls.

An **unqualified dollar** is `$` attached to an invoice amount with no clear
currency identifier elsewhere in the document. For example:

| Invoice text | Treatment |
| --- | --- |
| `$5,000` alone | Apply the configured dollar policy. |
| `US$5,000` or `$5,000` with `Currency: USD` | Preserve explicit USD. |
| `CAD 5,000`, `CA$5,000`, or `EUR 5,000` | Preserve the explicit currency. |
| No currency indication, or conflicting declarations | Block; do not assume a currency. |

`action = "assume"` applies the configured currency and records the assumption
in the result. To block unqualified dollars instead, set `action = "reject"`;
the `currency` setting is then ignored. An omitted dollar policy also rejects.
Explicit currencies are never converted. Grok identifies the currency notation;
Python applies the policy after source review.

Approval limits are quoted decimal amounts, separately configured per currency.
At or below the limit, a valid invoice is eligible for automatic approval after
Grok's recommendation and critique. Above it, Grok must request the separate
mock VP response: set `response` to `approved`, `rejected`, or `pending` and
provide a `reason`. This setting applies to every above-limit invoice in the run;
it simulates authorization, not a real person's decision. Python prevents Grok
from overriding it. Unresolved critiques block approval after one correction.

USD defaults to 10,000. To support another currency, add its limit under
`[approval.limits]`, for example `EUR = "8000"`. No conversion occurs; a currency
without a configured limit stays pending. Pending results do not wait or resume
automatically; update configuration and rerun to exercise a different mock response.
Already-paid copies skip approval after validation. Payment receipts persist in
SQLite; complete processing histories still appear in the CLI results and logs.

Optional command-line overrides:

```powershell
.\.venv\Scripts\python main.py --invoice_dir=data/invoices --workers=2 --config=config.toml --log_dir=logs
```

`--workers` overrides the configured worker count. If set, `XAI_MODEL` overrides
`model.name`; environment variables take precedence over `.env`.

See [reader plugins](reader_plugins/README.md) to add file formats and
[CUSTOMIZATIONS.md](CUSTOMIZATIONS.md) for project-specific behavior.

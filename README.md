# InvoiceFlow

Extract invoice data, validate inventory, obtain simulated approval, and record
simulated payments. Live mode uses Grok and LangGraph; offline mode uses scripted
model responses through the same workflow. No real funds are transferred.

Supported inputs: TXT, CSV, JSON, XML, Markdown, and text-based PDF. See the
[demo walkthrough](docs/DEMO.md) for scenarios, audit details, and limitations.

## How to set up

You need **Python 3.12** and Git. Install dependencies while connected to the internet:

```powershell
git clone https://github.com/surfgeek/InvoiceFlow.git
cd InvoiceFlow
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
```

Run all remaining commands from this repository folder. Examples use Windows paths;
on macOS/Linux, replace `.\.venv\Scripts\python` with `.venv/bin/python`.

**Create the required database before running the app:**

```powershell
.\.venv\Scripts\python setup_inventory.py --offline
```

This creates `offline.db` with inventory stock (WidgetA 15, WidgetB 10, GadgetX 5,
FakeItem 0) and a payment ledger for duplicate checks. SQLite is included with
Python; no database server is needed. Rerunning setup preserves existing records.

**For live Grok**, also run `.\.venv\Scripts\python setup_inventory.py` to create
`inventory.db`, then put an xAI API key with credits in `.env` beside `main.py`:

```dotenv
XAI_API_KEY=your-api-key
```

Offline mode needs no key or network access at runtime. Live mode uses paid API
calls. The two databases keep payment histories separate; retain them between runs.
Keys, databases, and operational logs are excluded from Git.

## How to run from the command line

**Start here: process the sample folder offline and create a readable report.**

```powershell
.\.venv\Scripts\python main.py --offline --invoice_dir=data/invoices --report=results.html > offline-results.json
```

Open `results.html` in your browser. It shows outcomes, reasons, and expandable
evidence. Progress and a summary appear in the terminal; detailed JSON is saved
when the run finishes. Each run also prints the path to its operational log.

The samples deliberately include invalid invoices, so **exit code 1 is expected**
for the full folder. Completed payments become `already_paid` on subsequent runs.
Use a new report filename when rerunning; existing reports are not overwritten.

Other examples:

```powershell
# One invoice, offline
.\.venv\Scripts\python main.py --offline --invoice_path=data/invoices/invoice_1001.txt

# Live Grok, with a report
.\.venv\Scripts\python main.py --invoice_dir=data/invoices --report=live-results.html > live-results.json

# Offline example requiring additional authorization
.\.venv\Scripts\python main.py --offline --invoice_path=data/offline_demo/high_value.txt

# Automated tests; no API calls
.\.venv\Scripts\python -m unittest discover -s tests -v
```

Offline mode recognizes unchanged bundled invoice text, including renamed copies
with supported formats. It does **not** perform LLM reasoning or parse new documents.
Invoice 1001 includes a scripted mistake and correction. Use live mode for new or
edited inputs. Results explicitly identify the mode.

Folder processing is concurrent and nonrecursive. Handled per-invoice failures
do not stop the batch. Keep JSON and HTML output outside the input folder.
Exit code 0 means every invoice was paid in simulation or already recorded;
1 indicates a blocked, pending, rejected, held, or failed result, or a report-write failure.

| If you see… | What to do |
| --- | --- |
| Missing database/schema | Run the setup command above; include `--offline` for offline mode. |
| Missing API key | Set `XAI_API_KEY` in `.env`, or use `--offline`. |
| No offline fixture | Use an unchanged bundled invoice or remove `--offline` for live extraction. |
| Report filename rejected | Choose a new `.html` filename in an existing directory outside the input folder. |
| Validation block or payment hold | Read the reason in the report. These are business outcomes, not necessarily API failures. |

## How to configure

Edit [config.toml](config.toml); changes apply on the next run. The shipped settings are:

```toml
[model]
name = "grok-4.6"
reasoning_effort = "low"
timeout_seconds = 60

[batch]
workers = 4

[inventory.aliases]
"Widget A" = "WidgetA"
"Gadget X" = "GadgetX"
"WidgetA (rush order)" = "WidgetA"

[currency.unqualified_dollar]
action = "assume"
currency = "USD"

[approval.limits]
USD = "10000"

[approval.mock_vp]
response = "pending"
reason = "Configured local mock VP response."
```

- **Model and concurrency:** timeout is per model call; workers controls concurrent
  invoices. Offline mode uses fixtures instead of the configured model.
- **Inventory aliases:** map exact source names to existing inventory items. Existing
  inventory names take precedence; matched quantities are combined. Original names
  and applied mappings remain in the audit record. Omit this section for exact matching only.
- **Currency:** an *unqualified dollar* is `$` attached to an invoice amount with no
  clear currency identifier elsewhere in the document. `assume` applies the configured
  currency; set `action = "reject"` to block instead. Missing or conflicting currencies
  never receive this fallback. Explicit USD, CAD, EUR, etc. are preserved without conversion.
- **Approval:** amounts at or below the currency's limit are eligible for automatic
  approval after review and critique. Higher amounts require the configured mock VP
  response: `approved`, `rejected`, or `pending`. Supply a reason. It applies to all
  above-limit invoices in that run and represents simulated authorization.
- **Other currencies:** add a quoted limit such as `EUR = "8000"` under
  `[approval.limits]`. Without a limit, that currency remains pending. Pending invoices
  do not resume automatically; change configuration and rerun when appropriate.

Malformed settings stop startup. Alias targets are checked against inventory during
processing. Keep secrets in `.env`.

Optional overrides:

```powershell
.\.venv\Scripts\python main.py --offline --invoice_dir=data/invoices --workers=2 --config=config.toml --log_dir=logs
```

`--workers` overrides the worker count. In live mode, `XAI_MODEL` overrides
`model.name`; environment variables take precedence over `.env`.

See [reader plugins](reader_plugins/README.md) to add formats and
[CUSTOMIZATIONS.md](CUSTOMIZATIONS.md) for deliberate project-specific policies.

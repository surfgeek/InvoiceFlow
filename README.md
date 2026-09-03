# InvoiceFlow

Extract invoice data, validate inventory, obtain simulated approval, and record
simulated payments. Live mode uses Grok and LangGraph; offline mode uses scripted
model responses through the same workflow. No real funds are transferred.

Supported inputs: TXT, CSV, JSON, XML, Markdown, and text-based PDF. See the
[demo walkthrough](docs/DEMO.md) for scenarios, audit details, and limitations.

## How to set up

You need **Python 3.12**. Git is required only if you clone the repository.

**Get the project with Git:**

```bash
git clone https://github.com/surfgeek/InvoiceFlow.git
cd InvoiceFlow
```

Alternatively, open the [InvoiceFlow repository](https://github.com/surfgeek/InvoiceFlow),
select **Code → Download ZIP**, extract the ZIP, and open a Bash terminal in the
extracted `InvoiceFlow-main` folder.

**Create the Python environment while connected to the internet:**

```bash
python -m venv .venv
source .venv/Scripts/activate
python -m pip install -r requirements.txt
```

Run all remaining commands from this repository folder with the virtual environment
active. On macOS/Linux, activate it with `source .venv/bin/activate` instead.

**Create the required database before running the app:**

```bash
python setup_inventory.py
```

This single setup command initializes inventory stock (WidgetA 15, WidgetB 10,
GadgetX 5, FakeItem 0) and payment ledgers in `inventory.db` and `offline.db`.
Both belong to the same application; separate histories keep offline demo payments
out of live runs. SQLite is included with Python. Rerunning setup preserves records.

**For normal processing with Grok**, put an xAI API key with credits in `.env` beside `main.py`:

```dotenv
XAI_API_KEY=your-api-key
```

Offline mode needs no key or network access at runtime. Live mode uses paid API
calls. The two databases keep payment histories separate; retain them between runs.
Keys, databases, and operational logs are excluded from Git.

## How to run from the command line

**Start here: process the provided invoices and create a readable report.**

```bash
python main.py --invoice_dir=data/invoices --report=results.html > results.json
```

Open `results.html` in your browser. It shows outcomes, reasons, and expandable
evidence. Progress and a summary appear in the terminal; detailed JSON is saved
when the run finishes. Each run also prints the path to its operational log.

The samples deliberately include invalid invoices, so **exit code 1 is expected**
for the full folder. Completed payments become `already_paid` on subsequent runs.
Use a new report filename when rerunning; existing reports are not overwritten.

Other examples:

```bash
# One invoice, offline
python main.py --offline --invoice_path=data/invoices/invoice_1001.txt

# Offline demo of the provided folder, with a report
python main.py --offline --invoice_dir=data/invoices --report=offline-results.html > offline-results.json

# Your own folder of supported invoices (live Grok)
python main.py --invoice_dir="C:/Invoices"

# Automated tests; no API calls
python -m unittest discover -s tests -v
```

Offline mode recognizes unchanged bundled invoice text, including renamed copies
with supported formats. It does **not** perform LLM reasoning or parse new documents.
Use live mode for new or edited inputs. Results explicitly identify the mode.

If a Grok API request fails, the affected invoice stops with an error and suggests
`--offline` for a local demo of bundled invoices. The app never switches modes
automatically. Retry live processing when API access is restored.

Folder processing is concurrent and nonrecursive. Handled per-invoice failures
do not stop the batch. Keep JSON and HTML output outside the input folder.
Exit code 0 means every invoice was paid in simulation or already recorded;
1 indicates a blocked, pending, rejected, held, or failed result, or a report-write failure.

| If you see… | What to do |
| --- | --- |
| Missing database/schema | Run `python setup_inventory.py` to initialize both databases. |
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

```bash
python main.py --offline --invoice_dir=data/invoices --workers=2 --config=config.toml --log_dir=logs
```

`--workers` overrides the worker count. In live mode, `XAI_MODEL` overrides
`model.name`; environment variables take precedence over `.env`.

See [reader plugins](reader_plugins/README.md) to add formats and
[CUSTOMIZATIONS.md](CUSTOMIZATIONS.md) for deliberate project-specific policies.

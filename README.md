# InvoiceFlow

InvoiceFlow uses Grok and LangGraph to extract invoice data, review it against the
source, and validate it against a local SQLite inventory. It supports TXT, CSV,
JSON, XML, Markdown, and text-based PDFs. Approval and payment are not yet implemented.

## How to set up

You need Python 3.12 and an xAI API key with credits. From the repository folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python setup_inventory.py
```

Create a `.env` file beside `main.py`:

```dotenv
XAI_API_KEY=your-api-key
```

The key and generated inventory database are excluded from Git. Running inventory
setup again preserves existing stock values.

Commands below use Windows paths. On macOS/Linux, use `.venv/bin/python` instead
of `.\.venv\Scripts\python`.

## How to run from the command line

Process one invoice:

```powershell
.\.venv\Scripts\python main.py --invoice_path=data/invoices/invoice_1001.txt
```

Process a folder and save the results:

```powershell
.\.venv\Scripts\python main.py --invoice_dir=data/invoices > batch-results.json
```

Folder runs process files concurrently, skip subfolders, and continue after
individual failures. Results remain in filename order. Keep the output file
outside the input folder.

Processing uses paid API calls. Progress appears in the terminal; JSON results
are written when the run finishes. Results include extracted data, validation
issues, and review history. Exit code **0** means all checks passed; **1** means
processing failed or validation blocked an invoice.

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

Optional command-line overrides:

```powershell
.\.venv\Scripts\python main.py --invoice_dir=data/invoices --workers=2 --config=config.toml --log_dir=logs
```

`--workers` overrides the configured worker count. If set, `XAI_MODEL` overrides
`model.name`; environment variables take precedence over `.env`.

See [reader plugins](reader_plugins/README.md) to add file formats and
[CUSTOMIZATIONS.md](CUSTOMIZATIONS.md) for project-specific behavior.

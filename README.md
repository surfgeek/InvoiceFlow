# InvoiceFlow

A Python prototype for Acme Corp's automated invoice processing workflow, based on the [Galatiq invoice processing assessment](https://github.com/galatiq-ai/galatiq-case-invoices).

The planned workflow covers invoice ingestion, structured data extraction, inventory validation, simulated approval, and mock payment processing.

See [CUSTOMIZATIONS.md](CUSTOMIZATIONS.md) for additions beyond the assessment,
their purpose, implementation status, and limits.

## Project status

Inventory database setup and a minimal LangGraph verification example are implemented.
Invoice and processing metadata models are defined in `models.py`.
Document text reading is implemented in `document_reader.py`.
Grok extraction is implemented in `extraction.py`, with a CLI in `main.py`.
LangGraph is the selected orchestration framework. The extraction CLI is not yet
connected to a graph. Required-field and SQLite inventory checks are implemented
in `validation.py`; approval, payment, extraction review, self-correction,
and runtime processing events are not yet implemented.

## Python environment and LangGraph example

From the repository root, create an isolated environment and install dependencies
(verified with Python 3.12):

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python graph_example.py
```

On macOS/Linux, use `.venv/bin/python` in place of `.venv\Scripts\python`.
The `.venv` directory stays local and is excluded from Git. `requirements.txt`
pins direct dependencies; their transitive dependencies are resolved by pip.
Installation requires internet; the example runs locally without an API key or model call.

Expected output:

```text
Input: {'message': 'Hello, InvoiceFlow'}
Output: {'message': 'Received: Hello, InvoiceFlow'}
```

The graph follows `START -> acknowledge -> END`. Its state is a dictionary
containing a message; the node returns an updated message. `TypedDict` describes
the dictionary shape for type checking, not runtime data validation.
This example demonstrates orchestration only, not an AI agent or invoice processing.

## Set up the inventory database

Run from the repository root using Python 3:

```sh
python setup_inventory.py
```

This uses Python's built-in `sqlite3` module; no additional packages are needed.
It creates `inventory.db` beside the script with the assessment's seed records:

| Item | Stock |
| --- | ---: |
| WidgetA | 15 |
| WidgetB | 10 |
| GadgetX | 5 |
| FakeItem | 0 |

Running the script again adds any missing seed records without duplicating rows
or overwriting existing stock values. The generated database is excluded from Git.

## Document reading

`read_document(path)` returns source text from TXT, CSV, JSON, XML, and text-based
PDF documents. The bundled Markdown plugin also supports MD. Text files use UTF-8,
with an optional byte-order mark. PDF text is
read across all pages using pypdf. The function does not extract invoice fields,
parse structured formats, or correct source values; all supported formats will
pass through Grok for invoice-field extraction and normalization.

Missing files, unsupported formats, decoding failures, corrupt or encrypted PDFs,
and documents without readable text raise `DocumentReadError`. OCR is not
implemented: text inside images is not read, including images within otherwise
readable PDFs. The three supplied PDFs contain extractable text.

The original assessment fixtures are included in `data/invoices`; see
`data/README.md` for their source revision.

## Extract an invoice with Grok

Set `XAI_API_KEY` in the environment or in a local `.env` file beside `main.py`:

```dotenv
XAI_API_KEY=your-api-key
XAI_MODEL=grok-4.6
```

The `.env` file is excluded from Git. Existing environment variables take
precedence over the file. `XAI_MODEL` is optional and defaults to `grok-4.6`.
Run:

```powershell
.venv\Scripts\python setup_inventory.py
.venv\Scripts\python main.py --invoice_path=data/invoices/invoice_1001.txt
```

This command sends the document text to the xAI API and consumes API credits.
It requires internet access and a funded API key. External inventory, approval,
and payment services are not called. The reader supplies text for every supported
format; Grok extracts and normalizes the fields using a JSON schema generated
from `Invoice`. Decimal fields are requested as strings to preserve precision.
Pydantic validates the returned structure locally, then Python checks the invoice
against the local inventory. JSON output contains `invoice` and `validation_issues`.

The command currently makes one extraction request, with a 60-second timeout
and a 2,048-token output limit. Incomplete output is rejected. Errors go to stderr
with exit code 1. Validation issues are printed in JSON and also return exit code 1;
exit code 0 means extraction and the implemented validation checks passed.
It does not mean the invoice is approved or its extraction is verified against the source.
There is no automatic correction or retry loop yet.

A live check of `invoice_1001.txt` returned Widgets Inc., amount `5000.00`,
WidgetA quantity `10`, WidgetB quantity `5`, and due date `2026-02-01`, matching
the source. Currency remained null because `$` alone is ambiguous. This is a
single integration check, not evidence of accuracy across the fixture set.
With validation enabled, this invoice reports unknown currency as a payment blocker.

## Invoice validation

The implemented rules require a nonblank vendor, positive amount, due date,
and at least one item with a nonblank name and positive quantity. Unknown currency
is reported as a payment blocker without skipping the remaining checks.
All detected issues are collected. Missing inventory or an unreadable database
is an operational error, not evidence of an invalid invoice.

Item names match SQLite records exactly. Repeated names are combined before
comparing quantities with stock; unknown items and insufficient stock are reported.
Negative lines cannot cancel positive quantities. Validation opens SQLite read-only
and does not reserve or decrement stock. Fractional positive quantities are accepted;
no whole-unit restriction, past-due rejection, or approval amount threshold is imposed.

These are prototype business rules. Source comparison, arithmetic reconciliation
of invoice totals, currency-code verification, and the approval/payment stages
are not yet implemented. A nonempty currency field alone does not verify a currency.

### Additional file formats

Readers are discovered from `reader_plugins/*.py` at startup. Add a module
exporting `EXTENSIONS` and `read(path) -> str`, install its dependencies, and restart
to enable another format without changing or rebuilding the core application.
See `reader_plugins/README.md` for the contract and bundled Markdown reader.
DOCX and PNG are extension examples, not currently bundled capabilities.

## Data records

`Invoice` contains vendor, amount, currency, items, and due date. `InvoiceItem`
contains an item name and quantity. Missing fields remain `None`; currency is not
inferred. Amounts and quantities use finite `Decimal` values without rounding or
currency conversion. Pass decimal strings or `Decimal` objects to avoid precision
loss before validation. Negative and fractional values remain available for
business validation rather than being silently corrected.

Due dates are calendar dates with no timezone. Extraction must supply an ISO date
or leave it unknown; ambiguous text and timestamps are not converted by the model.
Pydantic reports malformed field values and unexpected fields as schema errors.
Passing schema validation does not establish invoice correctness or approval.

`ProcessingRecord` stores arrival time separately from invoice data. Its
`ProcessingEvent` entries identify a stage, status, timestamp, and optional reason.
Stages are ingestion, validation, approval, and payment; statuses are started,
completed, and failed. The application must supply timezone-aware timestamps;
the models normalize them to UTC while preserving the instant. No timestamps are
generated automatically. Recording events and handling extraction errors will be
implemented with the workflow.

## Tests

Run the automated tests from the repository root:

```sh
.venv\Scripts\python -m unittest discover -s tests -v
```

The tests use Python's built-in `unittest` runner and temporary SQLite databases;
they do not modify your local `inventory.db`. They cover the required seed data,
repeat setup, preservation of changed stock, restoration of missing seed records,
and an invalid database path. A command-line test runs the script in a separate
process and verifies that it creates the database beside the script even when
launched from another working directory.

Model unit tests cover missing data, decimal precision, currency preservation,
calendar dates, malformed records, and UTC timestamp handling.
Document reader tests cover all 20 supplied files, source text preservation,
multiple PDF pages, and unreadable or unsupported inputs.
Plugin tests cover discovery, restart behavior, extension conflicts, invalid
definitions, dependency failures, reader errors, and execution in a fresh process.
Extraction tests mock the xAI boundary and cover precise decimals, missing fields,
malformed and incomplete output, and provider failures. CLI integration tests use
the real document reader and a temporary SQLite database with mocked Grok responses.
Validation tests cover required fields, repeated items, stock boundaries, exact
quantity aggregation, unknown currency, unchanged stock, and database failures.
The automated suite makes
no paid model calls and does not load a real API key.
The inventory tests are database integration tests and a setup CLI test. End-to-end invoice
processing tests will be added when that workflow is implemented.

## Change control

Develop changes on feature branches and review them through pull requests before merging into `main`.

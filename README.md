# InvoiceFlow

A Python prototype for Acme Corp's automated invoice processing workflow, based on the [Galatiq invoice processing assessment](https://github.com/galatiq-ai/galatiq-case-invoices).

The planned workflow covers invoice ingestion, structured data extraction, inventory validation, simulated approval, and mock payment processing.

See [CUSTOMIZATIONS.md](CUSTOMIZATIONS.md) for additions beyond the assessment,
their purpose, implementation status, and limits.

## Project status

Inventory database setup and a minimal LangGraph verification example are implemented.
Invoice and processing metadata models are defined in `models.py`.
Document text reading is implemented in `document_reader.py`.
LangGraph is the selected orchestration framework. Invoice processing is not yet implemented.

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
`data/README.md` for their source revision. Grok integration is not yet implemented.

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
The inventory tests are database integration tests and a setup CLI test. End-to-end invoice
processing tests will be added when that workflow is implemented.

## Change control

Develop changes on feature branches and review them through pull requests before merging into `main`.

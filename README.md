# InvoiceFlow

A Python prototype for Acme Corp's automated invoice processing workflow, based on the [Galatiq invoice processing assessment](https://github.com/galatiq-ai/galatiq-case-invoices).

The planned workflow covers invoice ingestion, structured data extraction, inventory validation, simulated approval, and mock payment processing.

## Project status

Inventory database setup and a minimal LangGraph verification example are implemented.
Invoice and processing metadata models are defined in `models.py`.
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
The inventory tests are database integration tests and a setup CLI test. End-to-end invoice
processing tests will be added when that workflow is implemented.

## Change control

Develop changes on feature branches and review them through pull requests before merging into `main`.

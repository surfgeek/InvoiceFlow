# InvoiceFlow

A Python prototype for Acme Corp's automated invoice processing workflow, built step by step for the [Galatiq technical assessment](https://github.com/galatiq-ai/galatiq-case-invoices).

The planned workflow covers invoice ingestion, structured data extraction, inventory validation, simulated approval, and mock payment processing.

## Project status

Inventory database setup and a minimal LangGraph learning example are implemented.
LangGraph is the selected orchestration framework; the invoice processing workflow
will be developed incrementally.

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
pins the direct LangGraph dependency; its transitive dependencies are resolved by pip.
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

## Change control

Discuss each change before implementation, develop it on a feature branch, and review it through a pull request before merging into `main`.

# InvoiceFlow

A Python prototype for Acme Corp's automated invoice processing workflow, built step by step for the [Galatiq technical assessment](https://github.com/galatiq-ai/galatiq-case-invoices).

The planned workflow covers invoice ingestion, structured data extraction, inventory validation, simulated approval, and mock payment processing.

## Project status

Inventory database setup is implemented. The invoice processing workflow will be developed incrementally.

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

## Tests

Run the automated tests from the repository root:

```sh
python -m unittest discover -s tests -v
```

The tests use Python's built-in `unittest` runner and temporary SQLite databases;
they do not modify your local `inventory.db`. They cover the required seed data,
repeat setup, preservation of changed stock, restoration of missing seed records,
and an invalid database path. A command-line test runs the script in a separate
process and verifies that it creates the database beside the script even when
launched from another working directory.

These are database integration tests and a setup CLI test. End-to-end invoice
processing tests will be added when that workflow is implemented.

## Change control

Discuss each change before implementation, develop it on a feature branch, and review it through a pull request before merging into `main`.

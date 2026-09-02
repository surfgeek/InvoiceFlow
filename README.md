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

## Change control

Discuss each change before implementation, develop it on a feature branch, and review it through a pull request before merging into `main`.

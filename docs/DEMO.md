# InvoiceFlow demo

InvoiceFlow turns an invoice document into an explained payment decision. Grok
extracts and reviews messy data; Python enforces stock, approval, and duplicate
payment rules. Staff can see why an invoice stopped and which evidence was corrected.

## Choose a mode

| Mode | Purpose | Dependencies at runtime |
| --- | --- | --- |
| Live (default) | Demonstrate actual Grok extraction, tool calling, and critique. | xAI API access and credits; local SQLite. |
| `--offline` | Demonstrate workflow behavior reproducibly with scripted model responses. | Installed Python dependencies and local SQLite only. |

The assessment requests Grok API integration and also locally simulated external
APIs. Live mode demonstrates the integration; offline mode provides a fully local
runtime. Approval and payment services are local mocks in both modes. Offline
results are not evidence of model quality or live performance.

## A short walkthrough

Follow [README setup](../README.md#how-to-set-up), using `setup_inventory.py --offline`
for the steps below. Run commands from the repository root. Outcomes assume a fresh
offline payment ledger; repeat runs return `already_paid` for completed payments.
Setup never resets the ledger.

1. **Correction followed by payment:**
   `python main.py --offline --invoice_path=data/invoices/invoice_1001.txt`
   The scripted extraction reports quantity 9; review finds 10 in the source.
   One correction succeeds. The result retains both snapshots and the finding.
2. **Stop an invalid order:**
   `python main.py --offline --invoice_path=data/invoices/invoice_1002.txt`
   The request for 20 GadgetX exceeds stock of 5. No approval or payment occurs.
3. **Require authorization:**
   `python main.py --offline --invoice_path=data/offline_demo/high_value.txt`
   USD 12,500 exceeds the USD 10,000 limit. The simulated model calls the VP tool;
   its default response leaves the invoice pending. Set `approval.mock_vp.response`
   to `approved` or `rejected` in configuration to exercise those outcomes. This
   response comes from configuration, not from the model's recommendation.
4. **Avoid duplicate payment:**
   Run invoice 1011's `.pdf` and then `.txt` with the same command pattern.
   The second copy returns the original receipt ID and timestamp.
5. **Hold a revision:**
   Run `invoice_1004.json`, then `invoice_1004_revised.json`.
   The original is paid; changed details under the same identity require review.

Remove `--offline` to use actual Grok on these or other supported documents.
Both modes return structured JSON on stdout and progress/log locations on stderr.
Add `--report=results.html` to open the results in any browser, including offline.
The report lists outcomes and reasons, with expandable source findings, configured
item matches, approval responses, payment receipts, and stage timestamps.
The full folder includes deliberately blocked invoices, so exit code 1 is expected.

## Reading the results

Each JSON result has an `outcome`: `simulated_paid`, `already_paid`,
`validation_blocked`, `pending_approval`, `rejected`, `payment_held`, or
`processing_error`. The HTML report explains these in plain language. Folder
summaries count each outcome separately; result order follows filenames even
though processing runs concurrently.

`processing.approval` retains recommendations, critique findings, and any mock VP
response. `processing.payment` holds the receipt, including exact amount, currency,
ID, and UTC timestamp. Source-review snapshots and findings remain under
`processing.reviews`; configured matches and currency assumptions are recorded
alongside them. Logs carry run/invoice IDs for correlation with these results.

Duplicate checks run after validation using source-reviewed vendor and invoice
number. Matching paid copies reuse their original receipt. Changed details under
the same identity, or missing invoice numbers, hold payment for review. The reason
is in `processing.payment_hold`. Changing approval configuration does not resolve
a revision conflict; there is no review inbox or automatic revision reconciliation.

Database setup is safe to rerun when upgrading: it creates missing tables and
preserves stock and payment rows. Receipts produced before the payment ledger
existed remain in their log files and are not imported automatically.

## What the implementation demonstrates

| Evaluation area | Concrete evidence |
| --- | --- |
| Functionality | All four stages are connected, with approved, rejected, pending, invalid, duplicate, and revision outcomes. |
| Code quality | Validated configuration and structured models; Decimal amounts; SQLite transactions; tests for failures and concurrent duplicates. |
| Agentic sophistication | Separate extraction, source-review, and approval calls; bounded correction and critique loops; a VP authorization tool. Live mode uses Grok; offline calls are scripted. |
| Shipping mindset | Local CLI and mock services; bounded loops and concurrency. No bank integration, approval inbox, or revision reconciliation. |
| Presentation | Reasons, source discrepancies, UTC events, and payment receipts explain each decision. Deterministic controls prevent model recommendations from bypassing authorization. |
| Above/beyond | Reader plugins, configurable currency policy, concurrent batches, and persistent duplicate protection address concrete input and operational issues. |
| UI/UX | One-file/folder commands, explicit mode labels, distinct outcome labels, actionable errors, and an optional browser-readable HTML report. No dashboard server is required. |

## Limits to explain honestly

- Inventory matching uses exact names plus explicit configured aliases, including
  `Widget A` → `WidgetA`. Other variations remain unknown; no fuzzy matching is used.
- Missing currencies remain blocked; currencies without an approval limit remain pending.
- Duplicate matching depends on extracted vendor/number and compared fields. It
  does not resolve vendor aliases or reconcile revisions. The first successful
  payment wins when differing versions arrive concurrently.
- Payment receipts persist, but full processing results are emitted at run completion.
  There is no review inbox or automatic resumption of held invoices.
- No financial savings or production reliability are claimed from a prototype run.

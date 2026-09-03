# Using InvoiceFlow

InvoiceFlow processes the supplied invoice folder and explains which documents
can proceed to simulated payment, which need attention, and why. The supplied
files intentionally include clean invoices, missing data, inventory problems,
duplicate copies, and revisions. A useful run will therefore include several
outcomes, not just successful payments.

## Start with the provided invoices

Complete the [README setup](../README.md#how-to-set-up) once. From the repository
folder, run:

```powershell
.\.venv\Scripts\python main.py --invoice_dir=data/invoices --report=results.html > results.json
```

Open `results.html` in your browser. The terminal shows progress and outcome
counts; the report gives each invoice's reason and expandable evidence. Detailed
JSON is saved when the batch finishes. Use a new report filename on subsequent runs.

By default, Grok processes the documents through its API. The app does not choose
an outcome from the filename. You can also point `--invoice_dir` at your own
folder of supported invoices, or use `--invoice_path` for a single document.
Validation still uses the configured local inventory and business rules.

## What happens and why

1. **Read and extract.** A format-specific reader obtains document text. Grok
   extracts the vendor, invoice identity, amount, currency, items, and due date.
   This lets different layouts enter a common workflow.
2. **Check the extraction.** A separate model call compares the extracted fields
   with the source. If it finds discrepancies, one correction is allowed and
   checked again. Unresolved discrepancies stop processing. The original findings
   remain visible even when corrected; model review is not a guarantee of accuracy.
3. **Validate the business data.** Python checks required values, item names, and
   quantities against SQLite inventory. Configured aliases handle known naming
   variations, and repeated quantities are combined. Currency assumptions are
   applied only where configured. Invalid data cannot proceed to payment.
4. **Check payment history.** After validation, an identical paid invoice reuses
   its receipt. Changed details under the same vendor and invoice number, or a
   missing invoice number, hold payment for review. This prevents duplicate copies
   from generating another payment while avoiding guesses about revisions.
5. **Apply approval policy.** Eligible invoices within their currency's limit can
   be approved after recommendation and critique. Above the limit, the agent must
   request a separate mock VP response. Python prevents the model from overriding
   that authorization. Missing currency limits leave approval pending.
6. **Record simulated payment.** Only final approval reaches the payment function.
   It saves a receipt with the exact amount, currency, ID, and UTC timestamp.
   A database transaction prevents concurrent copies from creating two payments.
   No bank is contacted and no real funds move.

## Understand the outcomes

| Outcome | Meaning |
| --- | --- |
| Simulated paid | All required checks and approval completed; a simulated receipt was saved. |
| Already paid | A matching payment was recorded earlier; its receipt was reused. |
| Validation blocked | Required data or inventory checks failed; the report lists the issues. |
| Pending approval | Additional authorization is pending, or the currency has no configured approval limit. |
| Rejected | The approval process returned a rejection; payment did not occur. |
| Payment held for review | Invoice identity is missing or conflicts with a paid invoice. |
| Processing error | Reading, model processing, database access, or another handled processing step failed. |

Blocked and pending outcomes are expected in the supplied sample set. Exit code 1
means at least one document did not complete payment or another run error occurred;
it does not by itself mean the app malfunctioned. Exit code 0 means every document
was paid in simulation or already recorded.

Payment history survives restarts. Repeating a run can produce `already_paid`
instead of new payments. With concurrent original/revised copies, the first
successful payment is recorded and the differing version is held. Setup preserves
history; it does not reset the demonstration.

Expand an invoice in the report to see extracted items, applied aliases, source
findings, approval reasons, receipts, and timestamps. JSON and logs provide
run/invoice IDs for tracing a result. Held invoices have no approval inbox or
automatic reconciliation; changing a VP response does not resolve a revision conflict.

## If the API is unavailable

There is one application installation. Live mode needs xAI access and credits.
If the API request fails, the affected invoice stops with an error; the app does
not silently replace live processing with simulated answers. Retry when access is
restored, or explicitly run the local demo:

```powershell
.\.venv\Scripts\python main.py --offline --invoice_dir=data/invoices --report=offline-results.html > offline-results.json
```

`--offline` replays scripted model responses for the unchanged supplied documents
through the same readers, graph, validation, approval tool, and payment code. It
includes a scripted correction so that path can be demonstrated without an API.
It is not an offline LLM and cannot interpret new or edited invoices. Mode labels
make the distinction visible in terminal output, reports, results, and logs.

Offline payment records use a separate database so demo runs do not affect the
live-mode ledger. This is data isolation, not a second installation. Business
services—VP authorization and payment—are local mocks in both modes.

## Scope and business value

The prototype reduces repetitive extraction and checking while keeping payment
controls in application code. Its report makes exceptions and their evidence
visible instead of treating every stopped invoice as a technical failure.

- **Functionality:** ingestion, validation, approval, and payment are connected.
- **Code quality:** structured data, exact decimal amounts, transactional receipts,
  bounded correction loops, operational logs, and automated failure/concurrency tests.
- **Agentic behavior:** separate model roles, source correction, approval critique,
  and a tool request for independent authorization. These are live Grok calls in
  normal mode and explicitly scripted responses offline.
- **Usability:** one-file or folder input, readable reports, distinct outcomes,
  configurable policies, and modular readers.
- **Deliberate limits:** no real banking, review inbox, fuzzy inventory matching,
  vendor-alias resolution, or revision reconciliation. Full results are emitted at
  batch completion; only payment receipts have database persistence.

These are prototype capabilities, not claims of proven financial savings or
production reliability. Configuration details are in the README; policy boundaries
are recorded in [CUSTOMIZATIONS.md](../CUSTOMIZATIONS.md).

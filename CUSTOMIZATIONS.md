# Customizations

This log records deliberate additions beyond the explicit
[assessment requirements](https://github.com/galatiq-ai/galatiq-case-invoices).
It does not replace the assessment or imply additional functionality is complete.

| Addition | Purpose | Current status and limits |
| --- | --- | --- |
| Reader plugins discovered at startup | Add file formats without modifying or rebuilding the core application. | Implemented in `document_reader.py`. Install a reader module and its dependencies, then restart. Duplicate extensions and invalid plugins stop discovery with a clear error. |
| Markdown reader | Provide an additional supported format and a concrete implementation of the plugin contract. | Implemented in `reader_plugins/markdown.py`. DOCX and PNG plugins are possible extensions, but are not implemented. |
| Configurable currency policy | Preserve explicit currencies and allow Acme to define treatment of unqualified dollars. | `config.toml` selects `assume` with USD or `reject`. Qualification comes from extraction and source review; Python applies the policy afterward and records any assumption. Missing/conflicting currencies receive no fallback. The README defines the terms and configuration examples. No conversion or currency-specific rounding is implemented. |
| UTC arrival and stage timestamps | Establish when a document entered the system and when processing started, completed, or failed. | The CLI records arrival and ingestion/validation/approval events in `ProcessingRecord`, including UTC timestamps and reasons. Payment events await that stage. Invoice due dates remain separate calendar dates. |
| Retained source-review findings | Preserve errors discovered during source review, including those later corrected. | Each review records an attempt number, UTC timestamp, invoice snapshot, findings with source excerpts and explanations, and resolution status. Findings survive correction and subsequent processing failures in stdout JSON. No automatic durable storage is implemented. |

## Scope distinctions

### Folder processing

The CLI adds `--invoice_dir` alongside the assessment's single-file option.
Files directly in the folder run with four concurrent workers by default
(configurable with `--workers`) and independent processing histories. Results
retain filename order and include elapsed time per file. Expected per-file failures do not stop the batch. Output
contains per-file results and summary counts. Recursive discovery, duplicate
invoice detection, and automatic comparison with expected answers are not implemented.

### Agreed validation policies

- Currency still unknown after the configured dollar policy blocks payment. Implemented as a validation issue; extraction
  and inventory checks still run. The payment stage itself is not yet implemented.
- Missing required fields, nonpositive amounts or quantities, unknown inventory
  items, and insufficient stock prevent progression to approval. Implemented as
  reported issues and a nonzero CLI exit status. LangGraph routes only invoices
  with no validation issues to approval.
- Repeated item lines are combined for stock comparison. Validation reads stock
  without changing it. No whole-unit quantity restriction is imposed.

### Approval policy interpretation

The assessment requires simulated rule-based approval and critique, but does not
define the authorization mechanism. InvoiceFlow permits automatic approval at
or below a per-currency limit (USD 10,000 by default). Above the limit, Grok calls
`request_vp_approval`; its arguments cannot contain an authorization or substitute
invoice fields. A local mock returns the configured response independently of Grok.
The response applies to all above-limit invoices in that run and defaults to pending.
It is not a real human approval or evidence that a VP reviewed the document.

Grok proposes a decision and a separate critique checks its reasons against the
invoice and policy. One correction is allowed; code also checks the decision
against the authorization. Unknown approval currencies stay pending. The result
retains the limit, mock response, UTC response time, recommendations, and critique
findings. Pending and rejected outcomes block progression. No approval inbox,
automatic resume, or payment is implemented. Runtime settings are in `config.toml`.

### Assessment and engineering scope

Structured operational logs are implemented as per-run local JSON-lines files.
They supplement the assessment's logging requirement with run/invoice correlation,
per-node and model-call timings, reasoning effort, available token usage, and
sanitized API failure status. Individual SDK transport retries are not observable;
automatic log retention and persistent result storage remain unimplemented.

- Grok, multi-agent orchestration, structured outputs, tool use, self-correction,
  SQLite validation, simulated approval, mock payment, and CLI results come from
  the assessment. They are not custom enhancements.
- LangGraph, Pydantic, Decimal, and pypdf are implementation choices.
- Tests, readable code, documentation, and pull-request review are engineering
  practices rather than additional product features.

Update this log when an addition is agreed, implemented, changed, or removed.
Describe implemented behavior separately from planned behavior.

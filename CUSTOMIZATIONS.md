# Customizations

This log records deliberate additions beyond the explicit
[assessment requirements](https://github.com/galatiq-ai/galatiq-case-invoices).
It does not replace the assessment or imply additional functionality is complete.

| Addition | Purpose | Current status and limits |
| --- | --- | --- |
| Reader plugins discovered at startup | Add file formats without modifying or rebuilding the core application. | Implemented in `document_reader.py`. Install a reader module and its dependencies, then restart. Duplicate extensions and invalid plugins stop discovery with a clear error. |
| Markdown reader | Provide an additional supported format and a concrete implementation of the plugin contract. | Implemented in `reader_plugins/markdown.py`. DOCX and PNG plugins are possible extensions, but are not implemented. |
| Currency preservation | Avoid assuming all amounts are USD; the supplied XML sample explicitly uses EUR, although currency is not listed among the required extraction fields. | Connected to Grok extraction: the prompt requests an explicit, unambiguous currency or null. A live check of invoice 1001 preserved its ambiguous `$` currency as unknown. No currency conversion, default currency, or currency-specific rounding is implemented. |
| UTC arrival and stage timestamps | Establish when a document entered the system and when processing started, completed, or failed. | The CLI records arrival and ingestion/validation events in `ProcessingRecord`, including UTC timestamps and failure reasons. Approval/payment events await those stages. Invoice due dates remain separate calendar dates. |
| Retained source-review findings | Preserve errors discovered during source review, including those later corrected. | Each review records an attempt number, UTC timestamp, invoice snapshot, findings with source excerpts and explanations, and resolution status. Findings survive correction and subsequent processing failures in stdout JSON. No automatic durable storage is implemented. |

## Scope distinctions

### Agreed validation policies

- Unknown currency blocks payment. Implemented as a validation issue; extraction
  and inventory checks still run. The payment stage itself is not yet implemented.
- Missing required fields, nonpositive amounts or quantities, unknown inventory
  items, and insufficient stock prevent progression to approval. Implemented as
  reported issues and a nonzero CLI exit status; graph routing is pending.
- Repeated item lines are combined for stock comparison. Validation reads stock
  without changing it. No whole-unit quantity restriction is imposed.

### Assessment and engineering scope

- Grok, multi-agent orchestration, structured outputs, tool use, self-correction,
  SQLite validation, simulated approval, mock payment, and CLI results come from
  the assessment. They are not custom enhancements.
- LangGraph, Pydantic, Decimal, and pypdf are implementation choices.
- Tests, readable code, documentation, and pull-request review are engineering
  practices rather than additional product features.

Update this log when an addition is agreed, implemented, changed, or removed.
Describe implemented behavior separately from planned behavior.

# Offline model fixtures

`responses.json` maps hashes of reader-produced text to explicit invoice fixtures.
It covers the 20 assessment files and one added high-value authorization scenario,
available in the normal batch as `data/invoices/invoice_vp_review.txt`. The fixtures
are committed data; generating or using them does not
require an API key. Changes to input text deliberately invalidate the match.

The assessment fixtures were prepared from inspected sample documents and prior
source-reviewed live outputs, with invoice identities checked against the source.
They are scripted examples, not an independent accuracy benchmark. Invoice 1001
has a deliberately incorrect initial quantity plus a scripted source finding to
exercise the real correction loop. Its corrected fixture matches the document.

`offline.py` simulates model responses only. Readers, validation, authorization
policy, tool dispatch, and transactional payments use the same code as live mode.
Offline approval recommendations and critiques follow scripted policy checks;
they do not reproduce Grok's reasoning. Unknown documents require live mode.

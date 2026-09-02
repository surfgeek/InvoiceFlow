# Document reader plugins

To add a format, place a Python module here, install its dependencies into the
application environment, and restart. No core changes or rebuild are required.
Discovery runs once when `document_reader` is imported at startup. Files beginning
with `_` are ignored.

Each plugin exports `EXTENSIONS`, a nonempty tuple/list of lowercase extensions
including the dot, and `read(path: pathlib.Path) -> str`. The included Markdown
reader demonstrates the complete contract:

```python
from pathlib import Path

EXTENSIONS = (".md",)

def read(path: Path) -> str:
    return path.read_bytes().decode("utf-8-sig")
```

Readers obtain source text only. They must not extract invoice fields, infer
currency, or repair business values; Grok performs extraction and normalization.
A DOCX reader would obtain text including tables. A PNG reader would need OCR.
DOCX and PNG readers are not bundled; declaring an extension alone does not
implement its decoding.

Duplicate extensions, invalid definitions, and import failures stop startup with
`ReaderPluginError`. Plugins cannot override built-in or other registered readers.
File-reading exceptions become `DocumentReadError`; non-string and empty results
also fail rather than continuing with unusable input.

Plugins execute Python with the application's permissions. Install trusted code
here, not invoice uploads. Dependencies are installed separately and should be
documented with each plugin.

"""Discover document reader plugins and dispatch files by extension."""

import importlib.util
import re
from collections.abc import Callable
from pathlib import Path

from builtin_readers import read_pdf, read_text


PLUGIN_DIRECTORY = Path(__file__).resolve().parent / "reader_plugins"


class DocumentReadError(ValueError):
    """A document could not provide readable text for extraction."""


class ReaderPluginError(ValueError):
    """Reader discovery failed; startup cannot use a partial configuration."""


class DocumentReader:
    """Load readers once at startup; restart to discover plugin changes.

    Plugins export EXTENSIONS (tuple/list) and read(path) -> str. They return
    source text without normalizing invoice fields and run as trusted Python code.
    """

    def __init__(self, plugin_directory: str | Path = PLUGIN_DIRECTORY) -> None:
        self._readers: dict[str, Callable[[Path], str]] = {
            extension: read_text for extension in (".txt", ".csv", ".json", ".xml")
        }
        self._readers[".pdf"] = read_pdf
        directory = Path(plugin_directory)
        if not directory.exists():
            return
        if not directory.is_dir():
            raise ReaderPluginError(f"Plugin location is not a directory: {directory}")
        for path in sorted(directory.glob("*.py")):
            if not path.name.startswith("_"):
                self._load_plugin(path)

    def _load_plugin(self, path: Path) -> None:
        try:
            spec = importlib.util.spec_from_file_location(f"invoiceflow_reader_{path.stem}", path)
            if spec is None or spec.loader is None:
                raise ValueError("Could not load Python module")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            extensions = getattr(module, "EXTENSIONS", None)
            reader = getattr(module, "read", None)
            if not isinstance(extensions, (tuple, list)) or not extensions or not callable(reader):
                raise ValueError("Plugin must export EXTENSIONS (tuple/list) and callable read(path)")
            for extension in extensions:
                if not isinstance(extension, str) or not re.fullmatch(r"\.[a-z0-9]+", extension):
                    raise ValueError(f"Extension must be lowercase with a leading dot: {extension!r}")
                if extension in self._readers:
                    raise ValueError(f"A reader is already registered for {extension}")
                self._readers[extension] = reader
        except Exception as error:
            raise ReaderPluginError(f"Could not load reader plugin {path.name}: {error}") from error

    def read(self, path: str | Path) -> str:
        """Return source text or a consistent error for unsupported/unreadable input."""
        path = Path(path)
        extension = path.suffix.lower()
        reader = self._readers.get(extension)
        if reader is None:
            raise DocumentReadError(f"Unsupported document format: {extension or '(none)'}")
        try:
            text = reader(path)
            if not isinstance(text, str):
                raise TypeError("Reader must return text as a string")
        except Exception as error:
            raise DocumentReadError(f"Could not read {path.name}: {error}") from error
        if not text.strip():
            raise DocumentReadError(f"No readable text found in {path.name}")
        return text


# Importing this module during application startup discovers installed plugins.
_default_reader = DocumentReader()


def read_document(path: str | Path) -> str:
    """Read with the readers discovered at application startup."""
    return _default_reader.read(path)

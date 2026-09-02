"""Verify reader extension without changing core application code."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from document_reader import DocumentReadError, DocumentReader, ReaderPluginError, read_document


class ReaderPluginTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.plugins = self.root / "plugins"
        self.plugins.mkdir()

    def install_plugin(self, name: str, source: str) -> None:
        (self.plugins / name).write_text(source, encoding="utf-8")

    def test_bundled_markdown_preserves_source(self) -> None:
        path = self.root / "invoice.MD"
        path.write_bytes("# Invoice\n\nQuantity: -5\nAmount: €250.123\n".encode("utf-8"))
        self.assertEqual(read_document(path), path.read_bytes().decode("utf-8"))

    def test_new_reader_requires_new_registry(self) -> None:
        original = DocumentReader(self.plugins)
        self.install_plugin("custom.py", "EXTENSIONS = ('.custom',)\ndef read(path):\n    return path.read_text()\n")
        path = self.root / "invoice.custom"
        path.write_text("Vendor: Example")
        with self.assertRaises(DocumentReadError):
            original.read(path)
        self.assertEqual(DocumentReader(self.plugins).read(path), "Vendor: Example")

    def test_plugin_runs_in_fresh_process(self) -> None:
        self.install_plugin("custom.py", "EXTENSIONS = ('.custom',)\ndef read(path):\n    return path.read_text()\n")
        path = self.root / "invoice.custom"
        path.write_text("Invoice source")
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; from document_reader import DocumentReader; "
             "print(DocumentReader(sys.argv[1]).read(sys.argv[2]))",
             str(self.plugins), str(path)],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "Invoice source")

    def test_builtin_reader_cannot_be_overridden(self) -> None:
        self.install_plugin("override.py", "EXTENSIONS = ('.txt',)\ndef read(path):\n    return 'changed'\n")
        with self.assertRaisesRegex(ReaderPluginError, "already registered for .txt"):
            DocumentReader(self.plugins)

    def test_plugins_cannot_claim_same_extension(self) -> None:
        source = "EXTENSIONS = ('.custom',)\ndef read(path):\n    return 'source'\n"
        self.install_plugin("first.py", source)
        self.install_plugin("second.py", source)
        with self.assertRaisesRegex(ReaderPluginError, "second.py.*already registered"):
            DocumentReader(self.plugins)

    def test_invalid_contracts_fail_at_startup(self) -> None:
        definitions = (
            "EXTENSIONS = '.custom'\ndef read(path): return 'text'",
            "EXTENSIONS = ('custom',)\ndef read(path): return 'text'",
            "EXTENSIONS = ('.CUSTOM',)\ndef read(path): return 'text'",
            "EXTENSIONS = ('.custom',)\nread = 'not callable'",
            "EXTENSIONS = ()\ndef read(path): return 'text'",
        )
        for index, source in enumerate(definitions):
            directory = self.plugins / str(index)
            directory.mkdir()
            (directory / "invalid.py").write_text(source)
            with self.subTest(source=source), self.assertRaises(ReaderPluginError):
                DocumentReader(directory)

    def test_dependency_error_identifies_plugin(self) -> None:
        self.install_plugin("broken.py", "raise ImportError('required plugin dependency missing')")
        with self.assertRaisesRegex(ReaderPluginError, "broken.py.*dependency missing"):
            DocumentReader(self.plugins)

    def test_read_failures_and_invalid_results_are_reported(self) -> None:
        for index, statement in enumerate(("raise RuntimeError('decode failed')", "return None", "return '  '")):
            directory = self.plugins / str(index)
            directory.mkdir()
            (directory / "reader.py").write_text(f"EXTENSIONS = ('.custom',)\ndef read(path):\n    {statement}\n")
            with self.subTest(statement=statement), self.assertRaises(DocumentReadError):
                DocumentReader(directory).read(self.root / "invoice.custom")

    def test_missing_plugin_directory_keeps_builtins(self) -> None:
        path = self.root / "invoice.txt"
        path.write_text("Invoice source")
        self.assertEqual(DocumentReader(self.root / "absent").read(path), "Invoice source")

"""Exercise source preservation and PDF reading with local fixtures."""

import tempfile
import unittest
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from document_reader import DocumentReadError, read_document


SAMPLES = Path(__file__).resolve().parents[1] / "data" / "invoices"


class DocumentReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def test_every_supplied_document_provides_text(self) -> None:
        paths = sorted(SAMPLES.iterdir())
        self.assertEqual(len(paths), 20)
        for path in paths:
            with self.subTest(document=path.name):
                self.assertTrue(read_document(path).strip())

    def test_structured_and_plain_text_are_preserved(self) -> None:
        for path in SAMPLES.iterdir():
            if path.suffix != ".pdf":
                with self.subTest(document=path.name):
                    self.assertEqual(read_document(path), path.read_bytes().decode("utf-8-sig"))

    def test_reader_does_not_parse_or_repair_invoice_content(self) -> None:
        source = '{"Vndr": "Example", "quantity": -5, BROKEN JSON\r\n'
        path = self.root / "invoice.json"
        path.write_bytes(source.encode("utf-8"))
        self.assertEqual(read_document(path), source)

    def test_utf8_bom_and_uppercase_extension(self) -> None:
        source = "Vendor: Fournisseur Européen\r\nTotal: €125.00"
        path = self.root / "invoice.TXT"
        path.write_bytes(source.encode("utf-8-sig"))
        self.assertEqual(read_document(path), source)

    def test_pdf_retains_identifying_content(self) -> None:
        expected = {
            "invoice_1011.pdf": ("Summit", "3,000"),
            "invoice_1012.pdf": ("QuickShip", "9,975"),
            "invoice_1013.pdf": ("Atlas", "22,562"),
        }
        for filename, fragments in expected.items():
            with self.subTest(document=filename):
                text = read_document(SAMPLES / filename)
                for fragment in fragments:
                    self.assertIn(fragment, text)

    def test_reads_multiple_pdf_pages_in_order(self) -> None:
        writer = PdfWriter()
        for filename in ("invoice_1011.pdf", "invoice_1013.pdf"):
            writer.add_page(PdfReader(SAMPLES / filename).pages[0])
        path = self.root / "multiple-pages.pdf"
        with path.open("wb") as stream:
            writer.write(stream)

        text = read_document(path)

        self.assertIn("Summit", text)
        self.assertIn("Atlas", text)
        self.assertLess(text.index("Summit"), text.index("Atlas"))

    def test_missing_file_and_directory_report_read_failures(self) -> None:
        missing = self.root / "missing.txt"
        directory = self.root / "directory.txt"
        directory.mkdir()
        for path in (missing, directory):
            with self.subTest(path=path), self.assertRaisesRegex(DocumentReadError, "Could not read"):
                read_document(path)

    def test_unsupported_format_is_rejected(self) -> None:
        with self.assertRaisesRegex(DocumentReadError, "Unsupported document format"):
            read_document(self.root / "invoice.docx")

    def test_empty_text_and_invalid_encoding_are_rejected(self) -> None:
        path = self.root / "invoice.txt"
        for content in (b"", b" \r\n\t", b"\xff\xfe\x00"):
            with self.subTest(content=content):
                path.write_bytes(content)
                with self.assertRaises(DocumentReadError):
                    read_document(path)

    def test_corrupt_pdf_is_rejected(self) -> None:
        path = self.root / "broken.pdf"
        path.write_bytes(b"%PDF-1.4\nnot a valid PDF\n%%EOF")
        with self.assertRaisesRegex(DocumentReadError, "Could not read"):
            read_document(path)

    def test_pdf_without_text_is_rejected(self) -> None:
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        path = self.root / "blank.pdf"
        with path.open("wb") as stream:
            writer.write(stream)
        with self.assertRaisesRegex(DocumentReadError, "No readable text"):
            read_document(path)

    def test_encrypted_pdf_is_rejected(self) -> None:
        writer = PdfWriter()
        writer.add_page(PdfReader(SAMPLES / "invoice_1011.pdf").pages[0])
        writer.encrypt("test-password")
        path = self.root / "encrypted.pdf"
        with path.open("wb") as stream:
            writer.write(stream)
        with self.assertRaisesRegex(DocumentReadError, "Encrypted PDF"):
            read_document(path)

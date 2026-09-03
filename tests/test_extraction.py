"""Exercise the Grok boundary with mocked responses, without API charges."""

import json
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

from grpc import RpcError

from extraction import ExtractionError, extract_invoice


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.sample = self.client.chat.create.return_value.sample

    def respond(self, content, reason="REASON_STOP"):
        self.sample.return_value = SimpleNamespace(content=content, finish_reason=reason)

    def test_extracts_fields_and_preserves_decimal_precision(self):
        self.respond(json.dumps({
            "vendor": "Example", "amount": "123456789.123456789",
            "currency": "EUR", "due_date": "2026-02-01",
            "items": [{"name": "WidgetA", "quantity": "-1.5"},
                      {"name": "WidgetA", "quantity": "2"}],
        }))
        invoice = extract_invoice("original source", self.client, "selected-model")
        self.assertEqual(invoice.amount, Decimal("123456789.123456789"))
        self.assertEqual(invoice.currency, "EUR")
        self.assertEqual(str(invoice.due_date), "2026-02-01")
        self.assertEqual([item.quantity for item in invoice.items], [Decimal("-1.5"), Decimal("2")])
        request = self.client.chat.create.call_args.kwargs
        self.assertEqual(request["model"], "selected-model")
        self.assertEqual(request["reasoning_effort"], "low")
        self.assertIn("original source", str(request["messages"][1]))
        schema = json.loads(request["response_format"].schema)
        self.assertEqual(schema["properties"]["amount"]["anyOf"][0]["type"], "string")
        self.assertNotIn("?!", request["response_format"].schema)
        self.sample.assert_called_once()

    def test_json_numbers_do_not_pass_through_float(self):
        self.respond('{"amount": 123456789.123456789}')
        self.assertEqual(extract_invoice("source", self.client).amount,
                         Decimal("123456789.123456789"))

    def test_missing_data_remains_unknown(self):
        self.respond('{}')
        invoice = extract_invoice("source", self.client)
        self.assertIsNone(invoice.currency)
        self.assertIsNone(invoice.amount)

    def test_malformed_outputs_are_rejected(self):
        for content in ('not JSON', '[]', '{"amount":"NaN"}',
                        '{"due_date":"yesterday"}', '{"unexpected":1}'):
            with self.subTest(content=content):
                self.respond(content)
                with self.assertRaises(ExtractionError):
                    extract_invoice("source", self.client)

    def test_incomplete_response_is_rejected_even_with_valid_json(self):
        self.respond('{}', "REASON_MAX_LEN")
        with self.assertRaises(ExtractionError):
            extract_invoice("source", self.client)

    def test_provider_error_is_reported_without_provider_details(self):
        self.sample.side_effect = RpcError("private provider details")
        with self.assertRaises(ExtractionError) as raised:
            extract_invoice("source", self.client)
        self.assertNotIn("private", str(raised.exception))
        self.assertIn("--offline", str(raised.exception))
        self.sample.assert_called_once()

    def test_empty_source_does_not_call_provider(self):
        with self.assertRaises(ExtractionError):
            extract_invoice("  ", self.client)
        self.client.chat.create.assert_not_called()

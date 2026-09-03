"""Exercise authorization boundaries and the real graph with mocked Grok responses."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from grpc import RpcError
from pydantic import ValidationError
from xai_sdk import Client
from xai_sdk.chat import Response, tool_result
from xai_sdk.proto.v6 import chat_pb2

from approval import ApprovalError, review_approval
from configuration import ApprovalSettings, MockVPSettings
from main import process_invoice
from models import ApprovalRecord, Invoice
from setup_inventory import setup_inventory
from source_review import SourceReview
from workflow import build_workflow


def decision(status="approved"):
    return {"status": status, "reason": f"Policy and authorization support {status}."}


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.chat = self.client.chat.create.return_value
        self.chat.messages = []
        self.record = ApprovalRecord()
        self.invoice = Invoice(vendor="Example", amount="10000", currency="USD",
                               due_date="2026-09-01", items=[{"name": "WidgetA", "quantity": "1"}])
        self.settings = ApprovalSettings()

    def responses(self, *values):
        self.chat.sample.side_effect = [
            SimpleNamespace(content=json.dumps(value), finish_reason="REASON_STOP")
            if isinstance(value, dict) else value for value in values]

    def tool_request(self, arguments="{}", name="request_vp_approval"):
        return SimpleNamespace(finish_reason="REASON_TOOL_CALLS", tool_calls=[
            SimpleNamespace(id="call-1", function=SimpleNamespace(name=name, arguments=arguments))])

    def run_approval(self):
        review_approval(self.invoice, self.record, self.settings, self.client, "test-model")

    def test_at_limit_approves_without_vp_request(self):
        for amount in ("9999.99", "10000"):
            with self.subTest(amount=amount):
                self.invoice.amount = self.invoice.amount.__class__(amount)
                self.responses(decision(), {"findings": []})
                self.run_approval()
                self.assertEqual(self.record.status, "approved")
                self.assertIsNone(self.record.vp_response)
                self.assertTrue(all("tools" not in call.kwargs for call in self.client.chat.create.call_args_list))

    def test_above_limit_uses_separate_authorization(self):
        self.invoice.amount += 1
        for status in ("approved", "rejected", "pending"):
            with self.subTest(status=status):
                self.record = ApprovalRecord()
                self.settings.mock_vp = MockVPSettings(response=status, reason=f"Mock VP: {status}")
                request = self.tool_request()
                self.responses(request, decision(status), {"findings": []})
                self.run_approval()
                self.assertEqual(self.record.status, status)
                self.assertEqual(self.record.vp_response.reason, f"Mock VP: {status}")
                self.assertEqual(self.record.vp_responded_at.utcoffset().total_seconds(), 0)
                self.chat.append.assert_any_call(tool_result(self.record.vp_response.model_dump_json(),
                                                            tool_call_id="call-1"))

    def test_model_cannot_override_pending_even_if_critic_agrees(self):
        self.invoice.amount += 1
        self.responses(self.tool_request(), decision(), {"findings": []}, decision(), {"findings": []})
        with self.assertRaisesRegex(ApprovalError, "remain"):
            self.run_approval()
        self.assertNotEqual(self.record.status, "approved")
        self.assertEqual(len(self.record.attempts), 2)
        self.assertTrue(all("cannot override" in attempt.findings[-1] for attempt in self.record.attempts))

    def test_one_correction_retains_original_findings(self):
        self.responses(decision(), {"findings": ["Reason invents a purchase order."]}, decision(), {"findings": []})
        self.run_approval()
        self.assertEqual(self.record.status, "approved")
        self.assertEqual(self.record.attempts[0].findings, ["Reason invents a purchase order."])
        self.assertEqual(len(self.record.attempts), 2)

    def test_unconfigured_currency_stays_pending_without_model_calls(self):
        self.invoice.currency = "EUR"
        self.run_approval()
        self.assertEqual(self.record.status, "pending")
        self.assertIn("No approval limit", self.record.reason)
        self.client.chat.create.assert_not_called()

    def test_configured_currency_has_its_own_limit(self):
        self.invoice.currency = "EUR"
        self.settings = ApprovalSettings(limits={"EUR": "20000"})
        self.responses(decision(), {"findings": []})
        self.run_approval()
        self.assertEqual(self.record.limit, 20000)
        self.assertEqual(self.record.currency, "EUR")

    def test_tool_arguments_cannot_supply_authorization(self):
        self.invoice.amount += 1
        for request in (self.tool_request('{"status":"approved"}'), self.tool_request("not JSON"),
                        self.tool_request(name="pay_invoice"),
                        SimpleNamespace(finish_reason="REASON_STOP", tool_calls=[])):
            with self.subTest(request=request):
                self.responses(request)
                with patch("approval.mock_vp_approval") as service, self.assertRaises(ApprovalError):
                    self.run_approval()
                service.assert_not_called()

    def test_bad_or_incomplete_model_response_blocks(self):
        for response in (SimpleNamespace(finish_reason="REASON_MAX_LEN", content="{}"),
                         SimpleNamespace(finish_reason="REASON_STOP", content="{}"), RpcError()):
            with self.subTest(response=response):
                self.responses(response)
                with self.assertRaises(ApprovalError):
                    self.run_approval()
                self.assertNotEqual(self.record.status, "approved")

    def test_critique_failure_keeps_recommendation_and_vp_response(self):
        self.invoice.amount += 1
        self.responses(self.tool_request(), decision("pending"), RpcError())
        with self.assertRaises(ApprovalError):
            self.run_approval()
        self.assertEqual(self.record.vp_response.status, "pending")
        self.assertIsNotNone(self.record.attempts[0].error)

    def test_sdk_tool_history_links_response_to_request_without_network(self):
        self.invoice.amount += 1
        request = Response(chat_pb2.GetChatCompletionResponse(outputs=[{
            "finish_reason": "REASON_TOOL_CALLS", "index": 0,
            "message": {"role": "ROLE_ASSISTANT", "tool_calls": [{
                "id": "vp-123", "type": "TOOL_CALL_TYPE_CLIENT_SIDE_TOOL",
                "function": {"name": "request_vp_approval", "arguments": "{}"},
            }]},
        }]), 0)
        responses = iter([request,
            SimpleNamespace(finish_reason="REASON_STOP", content=json.dumps(decision("pending"))),
            SimpleNamespace(finish_reason="REASON_STOP", content='{"findings":[]}')])
        chats = []
        def sample(chat, model, effort):
            chats.append(chat)
            return next(responses)
        with Client(api_key="offline-test-key") as client, patch("approval.sample_logged", side_effect=sample):
            review_approval(self.invoice, self.record, self.settings, client, "test-model")
        history = chats[1].messages
        self.assertEqual(history[-2].tool_calls[0].id, "vp-123")
        self.assertEqual(history[-1].tool_call_id, "vp-123")
        self.assertIn('"status":"pending"', history[-1].content[0].text)
        self.assertEqual(self.record.status, "pending")

    def test_invalid_configuration_rejected(self):
        for limits in ({"usd": "10000"}, {"USD": "0"}, {"USD": "NaN"}, {"USD": "-1"}, {"USD": 1.1}):
            with self.subTest(limits=limits), self.assertRaises(ValidationError):
                ApprovalSettings(limits=limits)
        with self.assertRaises(ValidationError):
            MockVPSettings(response="maybe")

    def test_graph_and_cli_preserve_outcomes_and_skip_invalid_invoices(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "inventory.db"
            setup_inventory(database)
            graph = build_workflow(self.client, database_path=database, approval_settings=self.settings)
            for status in ("approved", "pending", "rejected", "failed", "invalid"):
                with self.subTest(status=status):
                    self.invoice.amount = self.invoice.amount.__class__("10001")
                    self.invoice.items[0].quantity = self.invoice.amount.__class__("99" if status == "invalid" else "1")
                    self.settings.mock_vp.response = status if status in ("approved", "pending", "rejected") else "pending"
                    self.responses(self.tool_request(), RpcError()) if status == "failed" else self.responses(
                        self.tool_request(), decision(self.settings.mock_vp.response), {"findings": []})
                    with patch("workflow.read_document", return_value="invoice"), patch(
                        "workflow.extract_invoice", return_value=self.invoice
                    ), patch("workflow.review_invoice", return_value=SourceReview(findings=[])), \
                            contextlib.redirect_stderr(io.StringIO()):
                        output, code = process_invoice(graph, Path("invoice.txt"))
                    self.assertEqual(code, 0 if status == "approved" else 1)
                    audit = output["processing"]["approval"]
                    if status == "invalid":
                        self.assertIsNone(audit)
                    else:
                        self.assertEqual(audit["status"], status)
                        self.assertEqual(output["processing"]["events"][-1]["stage"], "approval")
                        self.assertEqual(audit["vp_response"]["status"], self.settings.mock_vp.response)
                    self.assertIn("invoice", output)
                    self.assertFalse(any(event["stage"] == "payment" for event in output["processing"]["events"]))

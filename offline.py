"""Explicit fixture-backed simulation of model responses; never contacts xAI."""

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from xai_sdk.chat import Response, assistant
from xai_sdk.proto import chat_pb2

from approval import ApprovalCritique
from extraction import ExtractionError
from models import ApprovalDecision, Invoice
from source_review import SourceReview


FIXTURES_PATH = Path(__file__).resolve().parent / "data/offline_demo/responses.json"


def source_digest(text: str) -> str:
    """Normalize line endings only; edited content must not reuse canned answers."""
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def response(content=None, tool_calls=None):
    return Response(chat_pb2.GetChatCompletionResponse(outputs=[{
        "finish_reason": "REASON_TOOL_CALLS" if tool_calls else "REASON_STOP",
        "index": 0, "message": {"role": "ROLE_ASSISTANT",
            "content": json.dumps(content) if content is not None else "",
            "tool_calls": tool_calls or []},
    }]), 0)


class OfflineClient:
    """Provide only the chat operations used by the existing workflow."""

    is_offline = True

    def __init__(self):
        self.fixtures = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))
        self.chat = self

    def create(self, **kwargs):
        return OfflineChat(self.fixtures, kwargs)


class OfflineChat:
    is_offline = True

    def __init__(self, fixtures, options):
        self.fixtures = fixtures
        self.options = options
        self.messages = list(options["messages"])

    def append(self, message):
        if isinstance(message, Response):
            converted = assistant(message.content)
            converted.tool_calls.extend(message.tool_calls)
            message = converted
        self.messages.append(message)

    def fixture(self, text):
        fixture = self.fixtures.get(source_digest(text))
        if fixture is None:
            raise ExtractionError("Offline mode has no fixture for this document. Use an unchanged bundled "
                                  "invoice, or run without --offline for live Grok extraction.")
        return fixture

    def sample(self):
        # These are local scripted responses, not extraction or reasoning by an LLM.
        users = ["".join(part.text for part in message.content)
                 for message in self.messages if message.role == chat_pb2.ROLE_USER]
        schema = self.options.get("response_format")
        if self.options.get("tools"):
            return response(tool_calls=[{"id": str(uuid4()), "type": "TOOL_CALL_TYPE_CLIENT_SIDE_TOOL",
                "function": {"name": "request_vp_approval", "arguments": "{}"}}])
        if schema is SourceReview:
            context = json.loads(users[0])
            fixture = self.fixture(context["source"])
            expected = Invoice.model_validate(fixture["invoice"])
            actual = Invoice.model_validate(context["invoice"])
            if actual == expected:
                return response({"findings": []})
            if "initial_invoice" in fixture and actual == Invoice.model_validate(fixture["initial_invoice"]):
                return response({"findings": fixture["findings"]})
            raise ExtractionError("Offline review received data outside its scripted scenario.")
        if schema in (ApprovalDecision, ApprovalCritique):
            context = json.loads(users[-1])
            authorization = context.get("vp_response")
            for message in self.messages:
                if message.role == chat_pb2.ROLE_TOOL:
                    authorization = json.loads("".join(part.text for part in message.content))
            above_limit = Invoice.model_validate(context["invoice"]).amount > Decimal(context["limit"])
            expected = authorization["status"] if authorization else ("pending" if above_limit else "approved")
            if schema is ApprovalCritique:
                findings = [] if context["recommendation"]["status"] == expected else ["Decision conflicts with authorization."]
                return response({"findings": findings})
            return response({"status": expected, "reason":
                f"Offline simulation: mock VP response is {expected}." if above_limit else
                "Offline simulation: amount is within the configured approval limit."})
        fixture = self.fixture(users[0])
        invoice = fixture["invoice"] if len(users) > 1 else fixture.get("initial_invoice", fixture["invoice"])
        return response(invoice)

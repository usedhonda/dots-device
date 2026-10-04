import json
import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from .bridge_client import BridgeClient
from .events import DeviceAnswerEvents, EventError, resolve_public_https, standard_webhooks_signature
from .server import MCPServer


class FakeBridge:
    def __init__(self): self.answers = []
    def publish_question(self, text, choices, question_id=None): return {"status": "pending", "interaction": {"id": question_id or "q1", "source": "real"}}
    def read_answers(self): return list(self.answers)
    def record_receipt(self, *args): return {"status": "recorded"}
    def status(self): return {"count": 1}


class DeviceMCPTests(unittest.TestCase):
    def test_tools_are_human_text_and_bridge_adapters(self):
        bridge = FakeBridge(); server = MCPServer(bridge)
        response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "device_publish_question", "arguments": {"text": "Choose", "choices": [{"id": "yes", "label": "Yes"}], "question_id": "q1"}}})
        self.assertEqual(response["result"]["content"][0]["text"], "pending")
        self.assertEqual(server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "device_status", "arguments": {}}})["result"]["structuredContent"]["count"], 1)

    def test_subscribe_challenge_no_history_dedup_and_retry(self):
        bridge = FakeBridge(); bridge.answers = [{"interaction_id": "old", "choice_id": "yes", "source": "real"}]
        with tempfile.TemporaryDirectory() as d:
            events = DeviceAnswerEvents(bridge, Path(d) / "events.json"); delivered = []
            def first_post(url, secret, payload, sid):
                delivered.append(payload)
                return (200, {"challenge": payload["challenge"]}) if payload.get("type") == "verification" else (500, None)
            events.post = first_post
            secret = "whsec_" + base64.b64encode(b"x" * 32).decode()
            events.subscribe("https://example.com/callback", secret)
            self.assertEqual(events.pump_once(), 0)
            bridge.answers.append({"interaction_id": "new", "choice_id": "no", "source": "real"})
            events.post = lambda url, secret, payload, sid: ((delivered.append(payload) or (200, {"challenge": payload["challenge"]})) if payload.get("type") == "verification" else (200, {}))
            self.assertEqual(events.pump_once(), 1); self.assertEqual(events.pump_once(), 0)
            self.assertTrue(any(item.get("data", {}).get("questionId") == "new" for item in delivered)
                            or any(item.get("payload", {}).get("data", {}).get("questionId") == "new" for item in events._load()["outbox"].values()))
            events.subscribe("https://example.com/callback", secret)
            bridge.answers.append({"interaction_id": "pending", "choice_id": "later", "source": "real"})
            self.assertEqual(events.pump_once(), 1)
            events2 = DeviceAnswerEvents(bridge, Path(d) / "events.json"); self.assertEqual(events2.pump_once(), 0)

    def test_unsubscribe_and_ssrf(self):
        with self.assertRaises(EventError): resolve_public_https("http://127.0.0.1/callback")
        with self.assertRaises(EventError): resolve_public_https("https://localhost/callback")
        bridge = FakeBridge()
        with tempfile.TemporaryDirectory() as d:
            events = DeviceAnswerEvents(bridge, Path(d) / "events.json")
            events.post = lambda *args: (200, {"challenge": args[2]["challenge"]})
            secret = "whsec_" + base64.b64encode(b"x" * 32).decode()
            info = events.subscribe("https://example.com/callback", secret)
            events.unsubscribe(info["id"]); self.assertEqual(events._load()["subscriptions"], {})
        with self.assertRaises(EventError): standard_webhooks_signature("secret", "e", 1, b"x")


if __name__ == "__main__": unittest.main()

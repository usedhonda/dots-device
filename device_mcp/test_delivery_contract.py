import base64
import hashlib
import hmac
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from .events import DeviceAnswerEvents
from .server import MCPServer
from .test_device_mcp import FakeBridge

SECRET = "whsec_" + base64.b64encode(b"x" * 32).decode()


class DeliveryContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bridge = FakeBridge()
        self.events = DeviceAnswerEvents(self.bridge, Path(self.tmp.name) / "state.json")
        self.dns = patch("device_mcp.events.resolve_public_https", return_value=("receiver.example", 443, ["93.184.216.34"]))
        self.dns.start()
        self.addCleanup(self.dns.stop)

    def subscribe(self):
        self.events.post = lambda u, s, p, i: (200, {"challenge": p["challenge"]})
        return self.events.subscribe("https://receiver.example/callback?route=kai", SECRET)["id"]

    def test_actual_verification_post_preserves_query_and_signature(self):
        context, connection = MagicMock(), MagicMock()
        response = connection.getresponse.return_value
        response.status = 200
        response.read.return_value = b'{"challenge":"one-use"}'
        with patch("device_mcp.events.ssl.create_default_context", return_value=context), patch("device_mcp.events.socket.create_connection"), patch("http.client.HTTPSConnection", return_value=connection):
            status, _ = self.events._post_webhook("https://receiver.example/callback?route=kai", SECRET, {"type": "verification", "challenge": "one-use"}, "sub_test")
        self.assertEqual(status, 200)
        args, kwargs = connection.request.call_args
        self.assertEqual(args, ("POST", "/callback?route=kai"))
        headers, body = kwargs["headers"], kwargs["body"]
        signed = (headers["webhook-id"] + "." + headers["webhook-timestamp"] + ".").encode() + body
        expected = "v1," + base64.b64encode(hmac.new(b"x" * 32, signed, hashlib.sha256).digest()).decode()
        self.assertEqual(headers["webhook-signature"], expected)
        self.assertEqual(json.loads(body)["type"], "verification")

    def test_refresh_keeps_pending_answer_and_receipt_does_not_reemit(self):
        self.subscribe()
        self.bridge.answers.append({"interaction_id": "q", "choice_id": "yes", "request_id": "r", "source": "real", "selected_at": 1000})
        self.subscribe()
        self.events.post = lambda *a: (200, {})
        self.assertEqual(self.events.pump_once(), 1)
        self.bridge.answers[0]["receipt_id"] = "received"
        self.assertEqual(self.events.pump_once(), 0)
        item = next(iter(self.events._load()["outbox"].values()))
        self.assertEqual(item["payload"]["timestamp"], "1970-01-01T00:16:40Z")

    def test_expiry_stops_pending_and_permanent_failure_is_terminal(self):
        sid = self.subscribe()
        self.bridge.answers.append({"interaction_id": "q", "choice_id": "yes", "source": "real"})
        self.events.post = lambda *a: (500, {})
        self.events.pump_once()
        state = self.events._load()
        state["subscriptions"][sid]["expiresAt"] = 0
        next(iter(state["outbox"].values()))["nextAt"] = 0
        self.events._save(state)
        self.events.post = MagicMock(return_value=(200, {}))
        self.events.pump_once()
        self.events.post.assert_not_called()
        self.subscribe()
        self.bridge.answers.append({"interaction_id": "q2", "choice_id": "yes", "source": "real"})
        self.events.post = lambda *a: (410, {})
        self.events.pump_once()
        self.assertIn("terminal", [x["status"] for x in self.events._load()["outbox"].values()])

    def test_malformed_delivery_is_protocol_error_and_next_call_survives(self):
        server = MCPServer(self.bridge, self.events)
        result = server.handle({"id": 1, "method": "events/unsubscribe", "params": {"name": "device.answer", "delivery": []}})
        self.assertIn("error", result)
        self.assertIn("result", server.handle({"id": 2, "method": "ping"}))


if __name__ == "__main__":
    unittest.main()

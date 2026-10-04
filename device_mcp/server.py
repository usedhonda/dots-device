from __future__ import annotations

import json
import sys
import threading
from typing import Any, TextIO

from .bridge_client import BridgeClient, BridgeError
from .events import DeviceAnswerEvents, EventError

PROTOCOL_VERSION = "2026-07-28"
TOOLS = {
    "device_publish_question": {"name": "device_publish_question", "description": "Publish a real question to the KAI device.", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}, "choices": {"type": "array", "items": {"type": "object"}}, "question_id": {"type": "string"}}, "required": ["text", "choices", "question_id"], "additionalProperties": False}},
    "device_read_answer": {"name": "device_read_answer", "description": "Read selected real answers from the KAI device.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    "device_record_receipt": {"name": "device_record_receipt", "description": "Record a receipt for a selected real device answer.", "inputSchema": {"type": "object", "properties": {"interaction_id": {"type": "string"}, "choice_id": {"type": "string"}, "receipt_id": {"type": "string"}, "summary": {"type": "string"}}, "required": ["interaction_id", "choice_id", "receipt_id", "summary"], "additionalProperties": False}},
    "device_status": {"name": "device_status", "description": "Read local KAI device connectivity status.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
}


def _error(req_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    error = {"code": code, "message": message}
    if data is not None: error["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": error}


class MCPServer:
    def __init__(self, bridge: BridgeClient | None = None, events: DeviceAnswerEvents | None = None):
        self.bridge, self.events = bridge, events

    def _call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if self.bridge is None: raise BridgeError("device bridge unavailable")
        if name == "device_publish_question": return self.bridge.publish_question(args["text"], args["choices"], args["question_id"])
        if name == "device_read_answer": return {"answers": self.bridge.read_answers()}
        if name == "device_record_receipt": return self.bridge.record_receipt(args["interaction_id"], args["choice_id"], args["receipt_id"], args["summary"])
        if name == "device_status": return self.bridge.status()
        raise ValueError("unknown tool")

    @staticmethod
    def _content(result: dict[str, Any]) -> str:
        if "answers" in result: return f"Found {len(result['answers'])} real device answer(s)."
        if result.get("status"): return str(result["status"])
        return "Device operation completed."

    def handle(self, request: Any) -> dict[str, Any] | None:
        if not isinstance(request, dict) or not isinstance(request.get("method"), str): return _error(None, -32600, "Invalid Request")
        req_id, method, params = request.get("id"), request["method"], request.get("params", {})
        if method.startswith("notifications/"): return None
        if not isinstance(params, dict): return _error(req_id, -32602, "Invalid params")
        if method == "initialize": return {"jsonrpc": "2.0", "id": req_id, "result": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {"listChanged": False}, "events": {} if self.events else {}}, "serverInfo": {"name": "kai-device", "version": "1.0.0"}}}
        if method == "ping": return {"jsonrpc": "2.0", "id": req_id, "result": {}}
        if method == "server/discover": return {"jsonrpc": "2.0", "id": req_id, "result": {"resultType": "complete", "supportedVersions": [PROTOCOL_VERSION], "capabilities": {"tools": {}, "events": {}}}}
        if method == "tools/list": return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": list(TOOLS.values())}}
        if method == "events/list":
            if not self.events: return _error(req_id, -32601, "Method not found")
            return {"jsonrpc": "2.0", "id": req_id, "result": {"events": [self.events.definition()], "nextCursor": None}}
        if method == "events/subscribe":
            try:
                if not self.events or params.get("name") != "device.answer" or params.get("arguments", {}) != {}: raise EventError("invalid event")
                if params.get("cursor") is not None: return _error(req_id, -32014, "Replay is not supported")
                delivery = params.get("delivery")
                if not isinstance(delivery, dict) or delivery.get("mode") != "webhook" or not isinstance(delivery.get("url"), str): raise EventError("invalid delivery")
                result = self.events.subscribe(delivery["url"], delivery["secret"], params.get("ttlMs", 86400000))
                return {"jsonrpc": "2.0", "id": req_id, "result": result}
            except (KeyError, ValueError, TypeError, EventError, BridgeError, OSError): return _error(req_id, -32015, "CallbackEndpointError", {"reason": "challenge_failed"})
        if method == "events/unsubscribe":
            try:
                if not self.events or params.get("name") != "device.answer" or params.get("arguments", {}) != {}: raise EventError("events unavailable")
                delivery = params.get("delivery")
                if not isinstance(delivery, dict) or delivery.get("mode") != "webhook" or not isinstance(delivery.get("url"), str): raise EventError("invalid delivery")
                self.events.unsubscribe(delivery["url"])
                return {"jsonrpc": "2.0", "id": req_id, "result": {}}
            except (EventError, TypeError): return _error(req_id, -32602, "Invalid unsubscribe request")
        if method != "tools/call": return _error(req_id, -32601, "Method not found")
        name, args = params.get("name"), params.get("arguments", {})
        if name not in TOOLS or not isinstance(args, dict): return _error(req_id, -32602, "Invalid tool name or arguments")
        try: result = self._call(name, args)
        except (BridgeError, KeyError, ValueError): return _error(req_id, -32000, "Device operation failed")
        return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": self._content(result)}], "structuredContent": result}}


def run_stdio(server: MCPServer, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> int:
    stop = threading.Event(); pump = getattr(server.events, "pump_once", None)
    def deliver() -> None:
        while not stop.wait(1):
            if callable(pump):
                try: pump()
                except Exception: pass
    worker = threading.Thread(target=deliver, daemon=True); worker.start() if callable(pump) else None
    try:
        for line in stdin:
            try: request = json.loads(line); response = server.handle(request)
            except (ValueError, TypeError): response = _error(None, -32700, "Parse error")
            if response is not None: stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n"); stdout.flush()
    finally: stop.set(); worker.join(timeout=2)
    return 0


def main() -> int:
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    bridge = BridgeClient(root)
    events = DeviceAnswerEvents(bridge, root / ".local" / "device-mcp-events.json")
    return run_stdio(MCPServer(bridge, events))


if __name__ == "__main__": raise SystemExit(main())

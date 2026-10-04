from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import socket
import ssl
import tempfile
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable

EVENT_NAME = "device.answer"
MAX_ATTEMPTS = 5


class EventError(RuntimeError):
    pass


def resolve_public_https(url: str) -> tuple[str, int, list[str]]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise EventError("callback must be HTTPS without credentials or fragments")
    port = parsed.port or 443
    if port != 443:
        raise EventError("callback must use HTTPS port 443")
    try:
        infos = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise EventError("callback hostname could not be resolved") from exc
    addresses = sorted({item[4][0] for item in infos})
    if not addresses or any(not (ipaddress.ip_address(address).is_global) for address in addresses):
        raise EventError("callback resolves to a non-public address")
    return parsed.hostname, port, addresses


def _payload_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def standard_webhooks_signature(secret: str, webhook_id: str, timestamp: int, body: bytes) -> str:
    import base64
    if not isinstance(secret, str) or not secret.startswith("whsec_"):
        raise EventError("invalid webhook secret")
    try: key = base64.b64decode(secret[6:], validate=True)
    except Exception as exc: raise EventError("invalid webhook secret") from exc
    if not 24 <= len(key) <= 64: raise EventError("invalid webhook secret")
    signed = f"{webhook_id}.{timestamp}.".encode() + body
    return "v1," + __import__("base64").b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()


class DeviceAnswerEvents:
    def __init__(self, bridge: Any, state_path: str | Path):
        self.bridge = bridge
        self.path = Path(state_path)
        if self.path.is_symlink() or self.path.parent.is_symlink():
            raise EventError("unsafe event state path")
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        self.lock = threading.RLock()
        self.post = self._post_webhook

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"subscriptions": {}, "outbox": {}}
        value = json.loads(self.path.read_text())
        if not isinstance(value, dict) or not isinstance(value.get("subscriptions"), dict) or not isinstance(value.get("outbox"), dict):
            raise EventError("invalid event state")
        return value

    def _save(self, value: dict[str, Any]) -> None:
        fd, tmp = tempfile.mkstemp(prefix=self.path.name + ".", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":")); stream.flush(); os.fsync(stream.fileno())
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)

    def definition(self) -> dict[str, Any]:
        return {"name": EVENT_NAME, "description": "A new real answer was selected on the KAI device.",
                "delivery": ["webhook"], "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
                "payloadSchema": {"type": "object", "properties": {"answerId": {"type": "string"}, "questionId": {"type": "string"}, "choiceId": {"type": "string"}}, "required": ["answerId", "questionId", "choiceId"], "additionalProperties": True}}

    def _post_webhook(self, url: str, secret: str, event: dict[str, Any], sid: str) -> tuple[int, dict[str, Any] | None]:
        # Validation is performed on every delivery; urllib's default redirect handler is disabled.
        host, port, addresses = resolve_public_https(url)
        parsed = urllib.parse.urlparse(url)
        body = _payload_bytes(event); timestamp = int(time.time()); eid = event.get("eventId") or "ver_" + secrets.token_urlsafe(16)
        headers = {"Content-Type": "application/json", "webhook-id": eid, "webhook-timestamp": str(timestamp),
                   "webhook-signature": standard_webhooks_signature(secret, eid, timestamp, body), "X-MCP-Subscription-Id": sid}
        if len(body) > 262144:
            raise EventError("event payload too large")
        with self.lock:
            previous = self._load()["subscriptions"].get(sid, {})
            if previous.get("rotationUntil", 0) > time.time() and previous.get("previousSecret") and event.get("type") != "verification":
                headers["webhook-signature"] += " " + standard_webhooks_signature(previous["previousSecret"], eid, timestamp, body)
        context = ssl.create_default_context()
        # Pin resolution while preserving hostname for TLS verification.
        sock = socket.create_connection((addresses[0], port), timeout=10)
        try:
            tls = context.wrap_socket(sock, server_hostname=host)
        except Exception:
            sock.close()
            raise
        try:
            import http.client
            conn = http.client.HTTPSConnection(host, port, context=context, timeout=10)
            conn.sock = tls
            target = parsed.path or "/"
            if parsed.query: target += "?" + parsed.query
            conn.request("POST", target, body=body, headers=headers)
            response = conn.getresponse(); raw = response.read(64 * 1024)
            try: data = json.loads(raw) if raw else None
            except ValueError: data = None
            return response.status, data
        finally:
            try: tls.close()
            except OSError: pass

    def subscribe(self, url: str, secret: str, ttl_ms: int = 86400000) -> dict[str, Any]:
        if ttl_ms is None: ttl_ms = 86400000
        if not isinstance(secret, str) or not secret.startswith("whsec_") or not isinstance(ttl_ms, int) or not 60000 <= ttl_ms <= 30 * 86400000:
            raise EventError("invalid subscription")
        standard_webhooks_signature(secret, "check", 0, b"")
        resolve_public_https(url)
        sid = "sub_" + hashlib.sha256((EVENT_NAME + "\0" + url).encode()).hexdigest()[:32]
        challenge = secrets.token_urlsafe(24)
        status, response = self.post(url, secret, {"type": "verification", "challenge": challenge}, sid)
        if not 200 <= status < 300 or not isinstance(response, dict) or not isinstance(response.get("challenge"), str) or not hmac.compare_digest(response["challenge"], challenge):
            raise EventError("callback verification failed")
        current = {self.answer_id(item) for item in self.bridge.read_answers()}
        with self.lock:
            state = self._load(); old = state["subscriptions"].get(sid)
            state["subscriptions"][sid] = {"id": sid, "url": url, "secret": secret, "expiresAt": time.time() + ttl_ms / 1000,
                "baseline": (old or {}).get("baseline", sorted(current)), "delivered": (old or {}).get("delivered", [])}
            if old and old.get("secret") != secret:
                state["subscriptions"][sid].update(previousSecret=old["secret"], rotationUntil=time.time() + 60)
            self._save(state)
        return {"id": sid, "refreshBefore": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + ttl_ms / 1000)), "cursor": None, "truncated": False}

    def unsubscribe(self, value: str) -> None:
        with self.lock:
            state = self._load(); sid = value if value in state["subscriptions"] else "sub_" + hashlib.sha256((EVENT_NAME + "\0" + value).encode()).hexdigest()[:32]
            state["subscriptions"].pop(sid, None)
            for item in state["outbox"].values():
                if item.get("subscription") == sid and item.get("status") not in ("sent", "terminal"): item["status"] = "revoked"
            self._save(state)

    @staticmethod
    def answer_id(answer: dict[str, Any]) -> str:
        return str(answer.get("interaction_id")) + ":" + str(answer.get("choice_id")) + ":" + str(answer.get("request_id") or "")

    def pump_once(self) -> int:
        answers = [a for a in self.bridge.read_answers() if isinstance(a, dict) and a.get("source") == "real"]
        sent = 0; now = time.time()
        with self.lock:
            state = self._load()
            for sid, sub in state["subscriptions"].items():
                if sub.get("expiresAt", 0) <= now: continue
                baseline = set(sub.get("baseline", [])); delivered = set(sub.get("delivered", []))
                for answer in answers:
                    aid = self.answer_id(answer)
                    if aid in baseline or aid in delivered: continue
                    event_id = "evt_" + hashlib.sha256((sid + "\0" + aid).encode()).hexdigest()[:32]
                    if event_id not in state["outbox"]:
                        occurred = answer.get("selected_at") or time.time()
                        if isinstance(occurred, (int, float)): occurred = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(occurred))
                        payload = {"eventId": event_id, "name": EVENT_NAME, "timestamp": occurred, "data": {"answerId": aid, "questionId": str(answer.get("interaction_id")), "choiceId": str(answer.get("choice_id")), "requestId": answer.get("request_id"), "summary": answer.get("receipt_summary")}, "cursor": None}
                        state["outbox"][event_id] = {"subscription": sid, "payload": payload, "attempts": 0, "nextAt": now, "status": "pending"}
            self._save(state)
            for eid, item in state["outbox"].items():
                if sent >= 50 or item.get("status") in ("sent", "terminal", "revoked") or item.get("nextAt", 0) > now: continue
                sub = state["subscriptions"].get(item["subscription"])
                if not sub or sub.get("expiresAt", 0) <= now: item["status"] = "revoked"; continue
                item["attempts"] += 1; item["status"] = "unknown"; self._save(state)
                try: status, _ = self.post(sub["url"], sub["secret"], item["payload"], item["subscription"])
                except Exception: status = 599
                if 200 <= status < 300:
                    item["status"] = "sent"; sub.setdefault("delivered", []).append(item["payload"]["data"]["answerId"]); sent += 1
                elif status in (410, 413) or (400 <= status < 500 and status not in (408, 429)): item["status"] = "terminal"
                elif item["attempts"] >= MAX_ATTEMPTS: item["status"] = "terminal"
                else: item["status"] = "pending"; item["nextAt"] = now + min(300, 2 ** item["attempts"])
                self._save(state)
        return sent

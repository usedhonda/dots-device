#!/usr/bin/env python3
"""Small authenticated HTTP bridge for the KAI prototype.

The bridge deliberately has no shell execution or external messaging.  It records
device requests and exposes a local dashboard; work needing KAI is represented as
pending_agent until an operator supplies a reply through /admin/reply.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import sqlite3
import subprocess
import threading
import time
import urllib.parse
import webbrowser
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCAL = ROOT / ".local"
TOKEN_FILE = LOCAL / "bridge-token"
CONFIG_FILE = LOCAL / "bridge-config.json"
DB_FILE = LOCAL / "bridge.sqlite3"
MAX_BODY = 16 * 1024
SUMMARY_MAX_AGE = 30 * 60
NEUTRAL_SUMMARY = "接続できました。確認したい項目を選んでください。"
BUTTONS = [
    {"id": "schedule", "label": "予定"},
    {"id": "messages", "label": "メッセージ"},
    {"id": "approvals", "label": "承認待ち"},
    {"id": "progress", "label": "作業状況"},
]
VISIBLE_BUTTON_IDS = {item["id"] for item in BUTTONS}
# Kept for firmware/client compatibility, but intentionally omitted from state.buttons.
LEGACY_BUTTON_IDS = {"summary", "details", "open_kai", "focus", "refresh"}
BUTTON_IDS = VISIBLE_BUTTON_IDS | LEGACY_BUTTON_IDS
KAI_COMMANDS = set()  # Future KAI-dependent commands must be added explicitly.
_DEVICE_STATS_INIT_LOCK = threading.Lock()


def now() -> float:
    return time.time()


def iso(ts: float | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts or now()))


def uptime_seconds() -> int:
    try:
        out = subprocess.run(["sysctl", "-n", "kern.boottime"], capture_output=True,
                             text=True, timeout=1, check=True).stdout
        sec = int(out.split("sec =", 1)[1].split(",", 1)[0].strip())
        return max(0, int(now() - sec))
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        try:
            return int(float(Path("/proc/uptime").read_text().split()[0]))
        except (OSError, ValueError, IndexError):
            return 0


class Store:
    """SQLite store whose shared connection is serialized by ``self.lock``."""

    def __init__(self, path: Path = DB_FILE):
        LOCAL.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.db.executescript("""
              CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS requests (
                request_id TEXT PRIMARY KEY, command_id TEXT NOT NULL,
                status TEXT NOT NULL, summary TEXT NOT NULL, response TEXT NOT NULL,
                created_at REAL NOT NULL, updated_at REAL NOT NULL
              );
              CREATE TABLE IF NOT EXISTS measurements (
                boot_id TEXT NOT NULL, seq INTEGER NOT NULL, received_at REAL NOT NULL,
                sample TEXT NOT NULL, PRIMARY KEY(boot_id, seq)
              );
              CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
                summary TEXT NOT NULL, created_at REAL NOT NULL
              );
              CREATE TABLE IF NOT EXISTS interactions (
                interaction_id TEXT PRIMARY KEY, text TEXT NOT NULL,
                choices TEXT NOT NULL, status TEXT NOT NULL,
                selected_choice_id TEXT, selected_request_id TEXT,
                source TEXT NOT NULL, created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                receipt_id TEXT, receipt_summary TEXT, receipt_at REAL
              );
            """)
            columns = {row[1] for row in self.db.execute("PRAGMA table_info(interactions)")}
            if "origin_request_id" not in columns:
                self.db.execute("ALTER TABLE interactions ADD COLUMN origin_request_id TEXT")
            if "receipt_id" not in columns:
                self.db.execute("ALTER TABLE interactions ADD COLUMN receipt_id TEXT")
            if "receipt_summary" not in columns:
                self.db.execute("ALTER TABLE interactions ADD COLUMN receipt_summary TEXT")
            if "receipt_at" not in columns:
                self.db.execute("ALTER TABLE interactions ADD COLUMN receipt_at REAL")
            self.db.commit()

    def save_measurements(self, samples):
        if not isinstance(samples, list) or not 1 <= len(samples) <= 32:
            raise ValueError("expected 1..32 samples")
        bounds = {"seq": (0, 4294967295), "uptime_ms": (0, 4294967295),
                  "battery_mv": (0, 6000), "min_battery_mv": (0, 6000),
                  "wifi_status": (0, 255), "rssi": (-127, 0),
                  "http_code": (-32768, 599), "reset_reason": (0, 32)}
        normalized = []
        for sample in samples:
            if not isinstance(sample, dict): raise ValueError("invalid sample")
            boot = sample.get("boot_id")
            if not isinstance(boot, str) or not 1 <= len(boot) <= 64 or not all(c.isalnum() or c in "-_" for c in boot):
                raise ValueError("invalid boot_id")
            item = {"boot_id": boot}
            for key, (low, high) in bounds.items():
                value = sample.get(key)
                if type(value) is not int or not low <= value <= high: raise ValueError("invalid " + key)
                item[key] = value
            if sample.get("stage") not in {"boot", "before_wifi", "sample", "reconnect"}: raise ValueError("invalid stage")
            item["stage"] = sample["stage"]
            normalized.append(item)
        with self.lock, self.db:
            for item in normalized:
                self.db.execute("INSERT OR IGNORE INTO measurements VALUES(?,?,?,?)",
                                (item["boot_id"], item["seq"], now(), json.dumps(item)))
        return len(normalized)

    def measurements(self, limit=1000):
        with self.lock:
            rows = self.db.execute("SELECT received_at,sample FROM measurements ORDER BY received_at DESC, rowid DESC LIMIT ?", (limit,)).fetchall()
        return [{**json.loads(row["sample"]), "received_at": row["received_at"]} for row in rows]

    def meta(self, key: str, default: str = "") -> str:
        with self.lock:
            row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self.lock:
            self.db.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
            self.db.commit()

    def event(self, kind: str, summary: str) -> None:
        with self.lock:
            self.db.execute("INSERT INTO events(kind,summary,created_at) VALUES(?,?,?)", (kind, summary[:500], now()))
            self.db.commit()

    def request(self, request_id: str):
        with self.lock:
            return self.db.execute("SELECT * FROM requests WHERE request_id=?", (request_id,)).fetchone()

    def save_request(self, request_id: str, command_id: str, status: str, summary: str, response: dict) -> dict:
        ts = now()
        raw = json.dumps(response, separators=(",", ":"), sort_keys=True)
        with self.lock:
            self.db.execute("INSERT INTO requests VALUES(?,?,?,?,?,?,?)", (request_id, command_id, status, summary[:500], raw, ts, ts))
            self.db.commit()
        return response

    def update_request(self, request_id: str, status: str, summary: str) -> bool:
        with self.lock:
            row = self.db.execute("SELECT response FROM requests WHERE request_id=?", (request_id,)).fetchone()
            if not row: return False
            response = json.loads(row["response"])
            response.update({"status": status, "summary": summary[:500]})
            cur = self.db.execute("UPDATE requests SET status=?,summary=?,response=?,updated_at=? WHERE request_id=?", (status, summary[:500], json.dumps(response, separators=(",", ":")), now(), request_id))
            self.db.commit()
            return cur.rowcount == 1

    def recent_requests(self, limit=50):
        with self.lock:
            return self.db.execute("SELECT request_id,command_id,status,summary,created_at,updated_at FROM requests ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()

    def recent_events(self, limit=50):
        with self.lock:
            return self.db.execute("SELECT kind,summary,created_at FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    def interaction(self):
        with self.lock:
            row = self.db.execute("SELECT * FROM interactions ORDER BY created_at DESC LIMIT 1").fetchone()
        if not row:
            return None
        return {"id": row["interaction_id"], "text": row["text"],
                "choices": json.loads(row["choices"]), "status": row["status"],
                "selected_choice_id": row["selected_choice_id"], "source": row["source"],
                "request_id": row["origin_request_id"], "receipt_id": row["receipt_id"]}

    def selected_choices(self, limit=50):
        with self.lock:
            rows = self.db.execute("SELECT * FROM interactions WHERE status='selected' ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        return [{"interaction_id": row["interaction_id"], "choice_id": row["selected_choice_id"],
                 "request_id": row["selected_request_id"], "origin_request_id": row["origin_request_id"],
                 "source": row["source"], "selected_at": row["updated_at"], "receipt_id": row["receipt_id"],
                 "receipt_summary": row["receipt_summary"], "receipt_at": row["receipt_at"]} for row in rows]

    def create_interaction(self, text, choices, source, interaction_id=None, request_id=None):
        interaction_id = interaction_id or uuid.uuid4().hex
        ts = now()
        with self.lock, self.db:
            self.db.execute("INSERT INTO interactions(interaction_id,text,choices,status,selected_choice_id,selected_request_id,source,created_at,updated_at,origin_request_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (interaction_id, text, json.dumps(choices, ensure_ascii=False),
                             "pending", None, None, source, ts, ts, request_id))
        return self.interaction()

    def record_choice(self, interaction_id, choice_id, request_id):
        with self.lock, self.db:
            row = self.db.execute("SELECT * FROM interactions WHERE interaction_id=?", (interaction_id,)).fetchone()
            if not row:
                raise LookupError("stale interaction")
            current = self.db.execute("SELECT interaction_id FROM interactions ORDER BY created_at DESC LIMIT 1").fetchone()
            if not current or current["interaction_id"] != interaction_id:
                raise LookupError("stale interaction")
            choices = json.loads(row["choices"])
            valid = {choice["id"] for choice in choices}
            if choice_id not in valid:
                raise ValueError("unknown choice")
            if row["status"] == "selected":
                if row["selected_choice_id"] == choice_id and row["selected_request_id"] == request_id:
                    return False
                raise RuntimeError("choice already recorded")
            cur = self.db.execute("UPDATE interactions SET status='selected', selected_choice_id=?, selected_request_id=?, updated_at=? WHERE interaction_id=? AND status='pending'",
                                 (choice_id, request_id, now(), interaction_id))
            if cur.rowcount != 1:
                raise RuntimeError("choice already recorded")
            return True

    def record_receipt(self, interaction_id, choice_id, receipt_id, summary):
        """Persist a real KAI receipt, updating the top summary only if current."""
        with self.lock, self.db:
            row = self.db.execute("SELECT * FROM interactions WHERE interaction_id=?", (interaction_id,)).fetchone()
            if not row or row["source"] != "real" or row["status"] != "selected":
                raise LookupError("real selected interaction required")
            if row["selected_choice_id"] != choice_id:
                raise ValueError("choice does not match selected choice")
            if row["receipt_id"] is not None:
                if row["receipt_id"] == receipt_id and row["receipt_summary"] == summary:
                    current = self.db.execute("SELECT interaction_id FROM interactions ORDER BY created_at DESC LIMIT 1").fetchone()
                    return False, bool(current and current["interaction_id"] == interaction_id)
                raise RuntimeError("receipt already recorded")
            received_at = now()
            self.db.execute("UPDATE interactions SET receipt_id=?, receipt_summary=?, receipt_at=? WHERE interaction_id=?",
                            (receipt_id, summary, received_at, interaction_id))
            current = self.db.execute("SELECT interaction_id FROM interactions ORDER BY created_at DESC LIMIT 1").fetchone()
            is_current = bool(current and current["interaction_id"] == interaction_id)
            if is_current:
                self.set_meta("summary", summary)
                self.set_meta("summary_source", "real")
                self.set_meta("summary_updated_at", str(received_at))
                self.set_meta("demo_hidden", "0")
                self.set_meta("updated_at", str(received_at))
            return True, is_current

    def dismiss_pending_simulation(self):
        with self.lock, self.db:
            self.db.execute("UPDATE interactions SET status='dismissed', updated_at=? WHERE status='pending' AND source='simulation'", (now(),))

    def set_demo_enabled(self, enabled):
        self.set_meta("demo_enabled", "1" if enabled else "0")


def token_value() -> str:
    try:
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        token = ""
    return token


def config() -> dict:
    try:
        value = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def state(store: Store) -> dict:
    focus_until = float(store.meta("focus_until", "0") or 0)
    last = store.meta("last_device_request", "")
    requests = store.recent_requests()
    summary_ts = store.meta("summary_updated_at", "")
    try:
        summary_age = max(0.0, now() - float(summary_ts)) if summary_ts else None
    except ValueError:
        summary_age = None
    stored_summary = store.meta("summary", "")
    fresh = summary_age is not None and summary_age <= SUMMARY_MAX_AGE
    if store.meta("demo_hidden", "0") == "1" and store.meta("summary_source", "") == "simulation":
        fresh = False
    summary = stored_summary if fresh else NEUTRAL_SUMMARY
    interaction = store.interaction()
    if interaction and interaction["status"] == "dismissed":
        interaction = None
    return {
        "status": "focus active" if focus_until > now() else "ready",
        "summary": summary,
        "summary_age_seconds": summary_age,
        "summary_source": store.meta("summary_source", "unknown") if fresh else "unknown",
        "demo_enabled": store.meta("demo_enabled", "0") == "1",
        "updated_at": iso(float(store.meta("updated_at", str(now())))),
        "buttons": BUTTONS,
        "interaction": interaction,
        "uptime_seconds": uptime_seconds(),
        "focus_until": iso(focus_until) if focus_until > now() else None,
        "last_device_request": last or None,
        "reply_request_id": store.meta("reply_request_id"),
        "reply_status": store.meta("reply_status"),
        "reply_summary": store.meta("reply_summary"),
        "pending_requests": [dict(row) for row in requests if row["status"] == "pending_agent"],
        "events": [dict(row) for row in store.recent_events(20)],
    }


def execute(store: Store, command_id: str, request_id: str) -> dict:
    if command_id == "schedule":
        return {"status": "pending_agent", "summary": "予定確認の依頼をMacに記録。KAIへの連携待ち"}
    if command_id == "messages":
        return {"status": "pending_agent", "summary": "返信確認の依頼をMacに記録。KAIへの連携待ち"}
    if command_id == "approvals":
        interaction = store.interaction()
        if interaction and interaction["status"] == "pending":
            return {"status": "pending_agent", "summary": "デバイス確認待ち。プラットフォーム権限の承認ではありません。", "interaction": interaction}
        return {"status": "completed", "summary": "デバイス確認待ちの項目はありません。"}
    if command_id == "summary":
        summary = state(store)["summary"]
        last = store.meta("last_device_request", "none")
        return {"status": "completed", "summary": summary, "uptime_seconds": uptime_seconds(), "last_device_request": last}
    if command_id == "details":
        events = len(store.recent_events())
        return {"status": "completed", "summary": f"Macは動作中。記録は{events}件。KAIへの送信はまだです。", "uptime_seconds": uptime_seconds(), "events": events}
    if command_id == "progress":
        return {"status": "pending_agent", "summary": "Macに記録。KAIへの連携待ち", "state_summary": state(store)["summary"]}
    if command_id == "refresh":
        store.set_meta("updated_at", str(now()))
        return {"status": "completed", "summary": "保存された状況を更新しました。"}
    if command_id == "focus":
        until = now() + 25 * 60
        store.set_meta("focus_until", str(until))
        store.set_meta("updated_at", str(now()))
        return {"status": "completed", "summary": "25分の集中タイマーを開始しました。", "focus_until": iso(until)}
    if command_id == "open_kai":
        url = config().get("codex_url")
        if not isinstance(url, str) or not url.startswith("codex://threads/"):
            return {"status": "unavailable", "summary": "KAIのリンクが未設定です。"}
        opened = webbrowser.open(url)
        return {"status": "completed", "summary": "MacでKAIを開くよう依頼しました。", "open_requested": bool(opened)}
    if command_id in KAI_COMMANDS:
        return {"status": "pending_agent", "summary": "KAIへの問い合わせを受け付けました", "request_id": request_id}
    raise ValueError("unsupported command")


class Handler(BaseHTTPRequestHandler):
    server_version = "KaiBridge/1.0"
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(20)

    def handle(self):
        try:
            super().handle()
        except (ConnectionError, TimeoutError, OSError):
            return

    def _json(self, code: int, value: dict) -> bool:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(raw)
        except OSError:
            return False
        return True

    def _is_loopback(self) -> bool:
        return self.client_address[0] in {"127.0.0.1", "::1", "::ffff:127.0.0.1"}

    def _device_stats(self):
        stats = getattr(self.server, "device_stats", None)
        if stats is None:
            with _DEVICE_STATS_INIT_LOCK:
                stats = getattr(self.server, "device_stats", None)
                if stats is None:
                    stats = {"lock": threading.Lock(), "count": 0, "last_seen": None}
                    self.server.device_stats = stats
        return stats

    def _record_device_state(self) -> None:
        stats = self._device_stats()
        with stats["lock"]:
            stats["count"] += 1
            stats["last_seen"] = now()
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            metrics = {}
            for key, low, high in (("uptime_ms", 0, 4294967295), ("reset_reason", 0, 32), ("wifi_rssi", -127, 0)):
                try:
                    value = int(query.get(key, [""])[0])
                except (ValueError, TypeError):
                    continue
                if low <= value <= high:
                    metrics[key] = value
            stats["metrics"] = metrics

    def _device_status(self) -> dict:
        stats = self._device_stats()
        with stats["lock"]:
            last_seen = stats["last_seen"]
            count = stats["count"]
            metrics = dict(stats.get("metrics", {}))
        return {
            "last_seen": last_seen,
            "age_seconds": max(0.0, now() - last_seen) if last_seen is not None else None,
            "count": count,
            "metrics": metrics,
        }

    def _auth(self, loopback=False) -> bool:
        if loopback and not self._is_loopback():
            self._json(HTTPStatus.FORBIDDEN, {"error": "loopback only"})
            return False
        supplied = self.headers.get("Authorization", "")
        good = "Bearer " + self.server.token
        if self.server.token and hmac.compare_digest(supplied, good):
            return True
        self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
        return False

    def _body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = MAX_BODY + 1
        if length <= 0 or length > MAX_BODY:
            raise ValueError("request body too large or empty")
        self.connection.settimeout(20)
        raw = self.rfile.read(length)
        if len(raw) != length: raise ValueError("incomplete request body")
        return json.loads(raw)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/dashboard":
            if not self._is_loopback():
                self._json(HTTPStatus.FORBIDDEN, {"error": "loopback only"}); return
            raw = DASHBOARD.encode()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw); return
        if path == "/state":
            if self._auth():
                value = state(self.server.store)
                query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                if query.get("compact") == ["1"]:
                    keys = ("summary", "summary_age_seconds", "summary_source", "demo_enabled", "interaction", "reply_request_id", "reply_status", "reply_summary")
                    value = {key: value[key] for key in keys}
                if self._json(200, value) and not self._is_loopback():
                    self._record_device_state()
            return
        if path == "/admin/state":
            if self._auth(loopback=True): self._json(200, state(self.server.store))
            return
        if path == "/admin/requests":
            if self._auth(loopback=True):
                status_filter = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("status", [None])[0]
                rows = self.server.store.recent_requests()
                if status_filter: rows = [row for row in rows if row["status"] == status_filter]
                self._json(200, {"requests": [dict(x) for x in rows]})
            return
        if path == "/admin/choices":
            if self._auth(loopback=True):
                self._json(200, {"choices": self.server.store.selected_choices()})
            return
        if path == "/admin/device/measurements":
            if self._auth(loopback=True): self._json(200, {"samples": self.server.store.measurements()})
            return
        if path == "/admin/device":
            if self._auth(loopback=True): self._json(200, self._device_status())
            return
        self._json(404, {"error": "not found"})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if not self._auth(loopback=path.startswith("/admin/")): return
        try: body = self._body()
        except (ConnectionError, TimeoutError, OSError): return
        except (ValueError, json.JSONDecodeError) as exc: self._json(400, {"error": str(exc)}); return
        try:
            if path == "/admin/state":
                summary, source = body.get("summary"), body.get("source", "simulation")
                if not isinstance(summary, str) or not (1 <= len(summary) <= 500): raise ValueError("invalid summary")
                if source not in {"real", "simulation"}: raise ValueError("invalid source")
                self.server.store.set_meta("summary", summary)
                self.server.store.set_meta("summary_source", source)
                self.server.store.set_meta("summary_updated_at", str(now()))
                self.server.store.set_meta("demo_hidden", "0")
                self.server.store.set_meta("updated_at", str(now()))
                self.server.store.event(source, f"Summary updated by local {source} admin")
                self._json(200, {"status": "updated", "summary": summary, "source": source, "simulation": source == "simulation"}); return
            if path == "/admin/demo":
                kind = body.get("kind")
                demos = {
                    "short": ("確認用サンプルです。下書きを送信しますか？", [{"id": "send", "label": "送信する"}, {"id": "cancel", "label": "やめる"}]),
                    "four": ("予定のサンプルを選択してください。これはテスト表示です。", [{"id": "meeting", "label": "打合せ"}, {"id": "travel", "label": "出張"}, {"id": "deadline", "label": "締切"}, {"id": "personal", "label": "私用"}]),
                    "scroll": ("確認用サンプル：これは長い説明を複数行に分けて表示するためのテストです。詳細を確認しても外部には送信されず、Mac上の記録だけが更新されます。", [{"id": "inspect", "label": "確認する"}, {"id": "cancel", "label": "やめる"}]),
                }
                if kind == "off":
                    self.server.store.dismiss_pending_simulation()
                    self.server.store.set_demo_enabled(False)
                    self.server.store.set_meta("demo_hidden", "1")
                    self._json(200, {"status": "disabled", "demo_enabled": False, "summary": NEUTRAL_SUMMARY}); return
                if kind not in demos: raise ValueError("kind must be short, four, scroll, or off")
                text, choices = demos[kind]
                interaction = self.server.store.create_interaction(text, choices, "simulation")
                self.server.store.set_demo_enabled(True)
                self.server.store.set_meta("demo_hidden", "0")
                self.server.store.event("demo", f"{kind}: simulation interaction enabled")
                self._json(200, {"status": "pending", "demo_enabled": True, "interaction": interaction}); return
            if path == "/admin/interaction":
                text, choices, source = body.get("text"), body.get("choices"), body.get("source")
                interaction_id, request_id = body.get("id"), body.get("request_id")
                if not isinstance(text, str) or not (1 <= len(text) <= 240) or any(ord(c) < 32 or c in "\r\n" for c in text):
                    raise ValueError("invalid interaction text")
                if source not in {"real", "simulation"}: raise ValueError("source is required")
                if not isinstance(choices, list) or not 1 <= len(choices) <= 4: raise ValueError("expected 1..4 choices")
                normalized, ids = [], set()
                for choice in choices:
                    if not isinstance(choice, dict): raise ValueError("invalid choice")
                    cid, label = choice.get("id"), choice.get("label")
                    if not isinstance(cid, str) or not (1 <= len(cid) <= 48) or cid in ids or any(ord(c) < 32 for c in cid): raise ValueError("invalid choice id")
                    if not isinstance(label, str) or not (1 <= len(label) <= 8) or any(ord(c) < 32 for c in label): raise ValueError("invalid choice label")
                    ids.add(cid); normalized.append({"id": cid, "label": label})
                if interaction_id is not None and (not isinstance(interaction_id, str) or not (1 <= len(interaction_id) <= 128)): raise ValueError("invalid interaction id")
                if request_id is not None and (not isinstance(request_id, str) or not (1 <= len(request_id) <= 128)): raise ValueError("invalid request_id")
                try:
                    interaction = self.server.store.create_interaction(text, normalized, source, interaction_id, request_id)
                except sqlite3.IntegrityError:
                    self._json(409, {"error": "interaction id already exists"}); return
                self.server.store.event("interaction", f"{interaction['id']}: interaction recorded ({source})")
                self._json(200, {"status": "pending", "interaction": interaction}); return
            if path == "/command":
                command_id, request_id = body.get("id"), body.get("request_id")
                if command_id not in BUTTON_IDS or not isinstance(request_id, str) or not (1 <= len(request_id) <= 128): raise ValueError("invalid command or request_id")
                with self.server.store.lock:
                    old = self.server.store.request(request_id)
                    if old:
                        if old["command_id"] != command_id: self._json(409, {"error": "request_id already used for another command"}); return
                        self._json(200, json.loads(old["response"])); return
                    self.server.store.set_meta("last_device_request", request_id)
                    result = execute(self.server.store, command_id, request_id)
                    status, summary = result.get("status", "completed"), result.get("summary", "")
                    response = {"request_id": request_id, "command": command_id, **result}
                    self.server.store.save_request(request_id, command_id, status, summary, response)
                    self.server.store.event("command", f"{command_id}: {summary}")
                    self.server.store.set_meta("updated_at", str(now()))
                    self._json(200, response); return
            if path == "/device/measurements":
                count = self.server.store.save_measurements(body.get("samples"))
                self._json(200, {"status": "recorded", "accepted": count}); return
            if path == "/choice":
                interaction_id = body.get("interaction_id")
                choice_id = body.get("choice_id")
                request_id = body.get("request_id")
                if not all(isinstance(value, str) and 1 <= len(value) <= 128 for value in (interaction_id, choice_id, request_id)):
                    raise ValueError("invalid choice request")
                try:
                    recorded = self.server.store.record_choice(interaction_id, choice_id, request_id)
                except LookupError:
                    self._json(409, {"error": "stale interaction"}); return
                except ValueError:
                    self._json(400, {"error": "unknown choice"}); return
                except RuntimeError as exc:
                    self._json(409, {"error": str(exc)}); return
                if recorded: self.server.store.event("choice", f"{interaction_id}: {choice_id} recorded")
                interaction = self.server.store.interaction()
                if recorded and interaction and interaction["source"] == "simulation":
                    label = next(choice["label"] for choice in interaction["choices"] if choice["id"] == choice_id)
                    summary = f"サンプル：{label}を選びました。実際の操作は行いません。"
                    self.server.store.set_meta("summary", summary)
                    self.server.store.set_meta("summary_source", "simulation")
                    self.server.store.set_meta("summary_updated_at", str(now()))
                    self.server.store.set_meta("demo_hidden", "0")
                    self.server.store.event("simulation", summary)
                self._json(200, {"status": "recorded", "interaction_id": interaction_id, "choice_id": choice_id}); return
            if path == "/telemetry":
                self.server.store.event("telemetry", "Telemetry received from device")
                self.server.store.set_meta("updated_at", str(now()))
                self._json(200, {"status": "recorded", "summary": "Telemetry recorded locally."}); return
            if path == "/admin/reply":
                rid, status, summary = body.get("request_id"), body.get("status"), body.get("summary")
                if not isinstance(rid, str) or status not in {"completed", "failed", "pending_agent"} or not isinstance(summary, str): raise ValueError("invalid reply")
                if not self.server.store.update_request(rid, status, summary): self._json(404, {"error": "request not found"}); return
                self.server.store.set_meta("reply_request_id", rid)
                self.server.store.set_meta("reply_status", status)
                self.server.store.set_meta("reply_summary", summary)
                if status == "completed":
                    self.server.store.set_meta("summary", summary)
                    self.server.store.set_meta("summary_source", "real")
                    self.server.store.set_meta("summary_updated_at", str(now()))
                    self.server.store.set_meta("updated_at", str(now()))
                self.server.store.event("reply", f"{rid}: {summary}")
                self._json(200, {"request_id": rid, "status": status, "summary": summary}); return
            if path == "/admin/choice-receipt":
                interaction_id = body.get("interaction_id")
                choice_id = body.get("choice_id")
                receipt_id = body.get("receipt_id")
                summary = body.get("summary")
                if not isinstance(interaction_id, str) or not 1 <= len(interaction_id) <= 128:
                    raise ValueError("invalid interaction_id")
                if not isinstance(choice_id, str) or not 1 <= len(choice_id) <= 48:
                    raise ValueError("invalid choice_id")
                if not isinstance(receipt_id, str) or not 1 <= len(receipt_id) <= 128:
                    raise ValueError("invalid receipt_id")
                if not isinstance(summary, str) or not 1 <= len(summary) <= 500 or any(ord(c) < 32 and c not in "\t" for c in summary):
                    raise ValueError("invalid summary")
                try:
                    recorded, current = self.server.store.record_receipt(interaction_id, choice_id, receipt_id, summary)
                except LookupError:
                    self._json(409, {"error": "real selected interaction required"}); return
                except ValueError as exc:
                    self._json(409, {"error": str(exc)}); return
                except RuntimeError as exc:
                    self._json(409, {"error": str(exc)}); return
                if recorded:
                    self.server.store.event("receipt", f"{interaction_id}: real KAI receipt recorded")
                self._json(200, {"status": "recorded", "interaction_id": interaction_id, "choice_id": choice_id,
                                 "receipt_id": receipt_id, "summary": summary, "current": current, "idempotent": not recorded}); return
            self._json(404, {"error": "not found"})
        except (ValueError, AttributeError, TypeError) as exc:
            self._json(400, {"error": str(exc)})

    def log_message(self, *_args):
        return


DASHBOARD = """<!doctype html><meta charset=utf-8><title>KAI Bridge</title>
<style>body{font:16px system-ui;margin:2rem;max-width:760px}button{padding:.7rem;margin:.2rem}pre{background:#f3f3f3;padding:1rem;white-space:pre-wrap}</style>
<h1>KAI Bridge</h1><p>This local dashboard shows bridge state. It never claims KAI delivery.</p>
<label>Token <input id=t type=password autocomplete=off></label><input id=s placeholder="Local simulation summary"><div id=b><button onclick="load()">Refresh</button><button onclick="save()">Set summary</button></div><pre id=o>Enter the local token to view state.</pre><script>
const out=document.querySelector('#o'), auth=()=>({'Authorization':'Bearer '+document.querySelector('#t').value,'Content-Type':'application/json'});
async function load(){try{let r=await fetch('/admin/state',{headers:auth()}); out.textContent=JSON.stringify(await r.json(),null,2)}catch(e){out.textContent='Unable to read authenticated local state.'}}
async function save(){let r=await fetch('/admin/state',{method:'POST',headers:auth(),body:JSON.stringify({summary:document.querySelector('#s').value})}); out.textContent=JSON.stringify(await r.json(),null,2)}
</script>"""


def serve(host: str, port: int):
    token = token_value()
    if not token: raise SystemExit(f"missing token: {TOKEN_FILE}")
    server = ThreadingHTTPServer((host, port), Handler)
    server.token, server.store = token, Store()
    server.device_stats = {"lock": threading.Lock(), "count": 0, "last_seen": None}
    server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KAI Mac HTTP bridge")
    parser.add_argument("--host", default="0.0.0.0"); parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args(); serve(args.host, args.port)
